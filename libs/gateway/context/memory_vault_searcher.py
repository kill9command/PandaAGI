"""
Memory Vault Searcher — BM25 + Embedding hybrid search with RRF fusion.

Search-First Context Gatherer Phase 2.1 v2.0: replaces LLM-based selection
with code-only search. The LLM never sees the full memory index.

Architecture Reference:
    architecture/main-system-patterns/phase2.1-context-gathering-retrieval.md
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from rank_bm25 import BM25Okapi

from libs.gateway.context.search_results import SearchResultItem, SearchResults

logger = logging.getLogger(__name__)

# Import embedding service with graceful fallback
try:
    from apps.services.tool_server.shared_state.embedding_service import EMBEDDING_SERVICE
    _EMBEDDING_AVAILABLE = True
except ImportError:
    EMBEDDING_SERVICE = None
    _EMBEDDING_AVAILABLE = False
    logger.info("[MemoryVaultSearcher] Embedding service not available, BM25-only mode")


# Source-type weights for RRF score.
# Original source material (Knowledge, Beliefs, preferences) is always preferred
# over LLM-generated turn summaries to prevent error compounding over time.
# A turn summary must score 2x higher in raw RRF to beat a Knowledge file.
_SOURCE_TYPE_WEIGHT = {
    "fact": 1.0,            # Knowledge, Beliefs — original source material
    "preference": 1.0,      # User's own stated preferences
    "research_cache": 0.9,  # Tool-gathered data, slight staleness discount
    "turn_summary": 0.5,    # LLM-generated — only if strongly matching
    "visit_record": 0.7,    # Cached page content — useful but secondary
}

# Simple stop words for BM25 tokenization
_STOP_WORDS = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "can",
    "had", "her", "was", "one", "our", "out", "has", "have", "been",
    "would", "could", "should", "will", "just", "what", "with", "this",
    "that", "from", "they", "which", "their", "there", "about", "into",
    "more", "some", "than", "them", "then", "these", "when", "where",
    "your", "also", "each", "other", "been", "like", "very", "most",
})

# Regex for _meta block stripping
_META_BLOCK_RE = re.compile(r"^---\n.*?\n---\n?", re.MULTILINE | re.DOTALL)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HEADING_RE = re.compile(r"^#+\s+.*$", re.MULTILINE)


def _tokenize(text: str) -> List[str]:
    """Tokenize text into lowercased words, removing stop words."""
    words = re.findall(r"\b[a-z]{2,}\b", text.lower())
    return [w for w in words if w not in _STOP_WORDS]


def _strip_meta(text: str) -> str:
    """Strip YAML front matter, HTML comments, and markdown headings for clean BM25 indexing."""
    text = _META_BLOCK_RE.sub("", text)
    text = _HTML_COMMENT_RE.sub("", text)
    text = _HEADING_RE.sub("", text)
    return text.strip()


class MemoryVaultSearcher:
    """
    Hybrid BM25 + embedding searcher over the user's memory vault.

    Scans turns, knowledge, beliefs, and preferences. Does NOT call any LLM.

    Usage:
        searcher = MemoryVaultSearcher(user_id, session_id, turns_dir, sessions_dir)
        results = searcher.search(
            search_terms=["syrian hamster", "hamster price"],
            include_preferences=True,
            include_n_minus_1=False,
            current_turn=237,
        )
    """

    def __init__(
        self,
        user_id: str,
        session_id: str,
        turns_dir: Path,
        sessions_dir: Path,
    ):
        self.user_id = user_id
        self.session_id = session_id
        self.turns_dir = turns_dir
        self.sessions_dir = sessions_dir

        # Resolve user-level directories
        from libs.gateway.persistence.user_paths import UserPathResolver
        resolver = UserPathResolver(user_id)
        self.knowledge_dir = resolver.knowledge_dir
        self.beliefs_dir = resolver.beliefs_dir
        self.preferences_file = resolver.preferences_file

    def search(
        self,
        search_terms: List[str],
        include_preferences: bool,
        include_n_minus_1: bool,
        current_turn: int,
        top_k: int = 15,
        reference_turns: Optional[List[int]] = None,
        forever_memory_results: Optional[List[Any]] = None,
        research_index_results: Optional[List[Dict[str, Any]]] = None,
        index_limit: int = 20,
    ) -> SearchResults:
        """
        Run hybrid search over the memory vault.

        Args:
            search_terms: 3-5 search phrases from LLM
            include_preferences: whether to force-include user preferences
            include_n_minus_1: whether to force-include the previous turn
            current_turn: current turn number (excluded from search)
            top_k: max results to return
            reference_turns: explicitly referenced turn numbers to always include
            forever_memory_results: pre-loaded obsidian memory results
            research_index_results: pre-loaded research index results
            index_limit: how many recent turns to scan

        Returns:
            SearchResults with ranked results
        """
        if not search_terms:
            return SearchResults(
                search_terms_used=[],
                results=[],
                stats={"total_documents_searched": 0, "bm25_matches": 0, "embedding_matches": 0, "final_results": 0},
                include_preferences=include_preferences,
                include_n_minus_1=include_n_minus_1,
            )

        # Truncate to 5 terms max per spec
        search_terms = search_terms[:5]

        # Step 1: Build corpus
        corpus = self._build_corpus(
            current_turn=current_turn,
            index_limit=index_limit,
            include_preferences=include_preferences,
            forever_memory_results=forever_memory_results,
            research_index_results=research_index_results,
        )

        if not corpus:
            logger.info("[MemoryVaultSearcher] Empty corpus — new user or no documents")
            return SearchResults(
                search_terms_used=search_terms,
                results=[],
                stats={"total_documents_searched": 0, "bm25_matches": 0, "embedding_matches": 0, "final_results": 0},
                include_preferences=include_preferences,
                include_n_minus_1=include_n_minus_1,
            )

        # Step 2: RRF fusion search
        ranked = self._rrf_fusion(search_terms, corpus)

        # Step 3: Dedup by document_path (highest score wins)
        seen_paths = set()
        deduped = []
        for item in ranked:
            if item.document_path not in seen_paths:
                seen_paths.add(item.document_path)
                deduped.append(item)

        # Step 4: Collect always-include items (may be ranked low)
        always_include = self._collect_always_include(
            all_results=deduped,
            include_preferences=include_preferences,
            include_n_minus_1=include_n_minus_1,
            current_turn=current_turn,
            reference_turns=reference_turns,
            corpus=corpus,
        )

        # Step 5: Build final list — always-include items get reserved slots
        # Take top-(K - reserved) search results, then append always-include
        always_node_ids = {item.node_id for item in always_include}
        search_only = [r for r in deduped if r.node_id not in always_node_ids]
        search_slots = max(0, top_k - len(always_include))
        final = search_only[:search_slots] + always_include

        # Load full content for results
        for item in final:
            if not item.content:
                item.content = self._load_content(item.document_path)

        stats = {
            "total_documents_searched": len(corpus),
            "bm25_matches": sum(1 for r in final if r.bm25_rank < len(corpus)),
            "embedding_matches": sum(1 for r in final if r.embedding_rank < len(corpus)),
            "final_results": len(final),
        }

        logger.info(
            f"[MemoryVaultSearcher] {len(final)} results from {len(corpus)} docs, "
            f"terms={search_terms}"
        )

        return SearchResults(
            search_terms_used=search_terms,
            results=final,
            stats=stats,
            include_preferences=include_preferences,
            include_n_minus_1=include_n_minus_1,
        )

    def _build_corpus(
        self,
        current_turn: int,
        index_limit: int,
        include_preferences: bool,
        forever_memory_results: Optional[List[Any]] = None,
        research_index_results: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, str]]:
        """
        Build searchable corpus from all memory sources.

        Each doc = {"text": str, "document_path": str, "source_type": str, "node_id": str}
        """
        corpus = []

        # 1. Recent turns (context.md files)
        corpus.extend(self._scan_turns(current_turn, index_limit))

        # 2. Knowledge files
        corpus.extend(self._scan_directory(self.knowledge_dir, "fact", "memory:Knowledge"))

        # 3. Belief files
        corpus.extend(self._scan_directory(self.beliefs_dir, "fact", "memory:Beliefs"))

        # 4. User preferences
        if include_preferences and self.preferences_file.exists():
            try:
                text = self.preferences_file.read_text()
                if text.strip():
                    corpus.append({
                        "text": _strip_meta(text),
                        "document_path": str(self.preferences_file),
                        "source_type": "preference",
                        "node_id": f"preference:user:{self.user_id}",
                    })
            except Exception as e:
                logger.warning(f"[MemoryVaultSearcher] Error reading preferences: {e}")

        # 5. Session preferences (separate from global)
        session_pref = self.sessions_dir / self.session_id / "preferences.md"
        if session_pref.exists() and str(session_pref) != str(self.preferences_file):
            try:
                text = session_pref.read_text()
                if text.strip():
                    corpus.append({
                        "text": _strip_meta(text),
                        "document_path": str(session_pref),
                        "source_type": "preference",
                        "node_id": "session:preferences",
                    })
            except Exception as e:
                logger.warning(f"[MemoryVaultSearcher] Error reading session preferences: {e}")

        # 6. Pre-loaded forever memory results (already fetched by gather())
        if forever_memory_results:
            for result in forever_memory_results:
                path = getattr(result, "path", "") or ""
                full_path = str(Path("panda_system_docs") / path) if path else ""
                text = getattr(result, "summary", "") or getattr(result, "topic", "") or ""
                if not text:
                    continue
                source_type = "preference" if getattr(result, "artifact_type", "") == "preference" else "fact"
                corpus.append({
                    "text": text,
                    "document_path": full_path,
                    "source_type": source_type,
                    "node_id": f"memory:{path}",
                })

        # 7. Pre-loaded research index results
        if research_index_results:
            for idx, doc in enumerate(research_index_results):
                doc_path = doc.get("doc_path", "")
                if not doc_path:
                    continue
                text_parts = [doc.get("topic", "")]
                keywords = doc.get("keywords") or []
                if keywords:
                    text_parts.append(" ".join(keywords))
                corpus.append({
                    "text": " ".join(text_parts),
                    "document_path": doc_path,
                    "source_type": "research_cache",
                    "node_id": f"research:{idx}",
                })

        return corpus

    def _scan_turns(self, current_turn: int, index_limit: int) -> List[Dict[str, str]]:
        """Scan recent turn context.md files."""
        docs = []
        if not self.turns_dir.exists():
            return docs

        # Get turn directories sorted descending by number
        turn_dirs = []
        for d in self.turns_dir.iterdir():
            if not d.is_dir() or not d.name.startswith("turn_"):
                continue
            try:
                num = int(d.name.split("_")[1])
            except (ValueError, IndexError):
                continue
            if num >= current_turn:
                continue  # skip current and future turns
            turn_dirs.append((num, d))

        turn_dirs.sort(key=lambda x: x[0], reverse=True)
        turn_dirs = turn_dirs[:index_limit]

        for num, d in turn_dirs:
            context_path = d / "context.md"
            if not context_path.exists():
                continue
            try:
                text = context_path.read_text()
                if text.strip():
                    docs.append({
                        "text": _strip_meta(text),
                        "document_path": str(context_path),
                        "source_type": "turn_summary",
                        "node_id": f"turn:{num}",
                    })
            except Exception as e:
                logger.warning(f"[MemoryVaultSearcher] Error reading {context_path}: {e}")

        return docs

    def _scan_directory(
        self, directory: Path, source_type: str, node_prefix: str
    ) -> List[Dict[str, str]]:
        """Recursively scan a directory for .md files."""
        docs = []
        if not directory.exists():
            return docs

        for md_file in directory.rglob("*.md"):
            try:
                text = md_file.read_text()
                if not text.strip():
                    continue
                # Build node_id from path relative to the directory itself
                # e.g. Knowledge/Facts/foo.md → "memory:Knowledge/Facts/foo.md"
                try:
                    rel = md_file.relative_to(directory)
                except ValueError:
                    rel = md_file.name
                docs.append({
                    "text": _strip_meta(text),
                    "document_path": str(md_file),
                    "source_type": source_type,
                    "node_id": f"{node_prefix}/{rel}",
                })
            except Exception as e:
                logger.warning(f"[MemoryVaultSearcher] Error reading {md_file}: {e}")

        return docs

    def _rrf_fusion(
        self,
        search_terms: List[str],
        corpus: List[Dict[str, str]],
        k: int = 60,
    ) -> List[SearchResultItem]:
        """
        Reciprocal Rank Fusion over BM25 + embedding search per term.

        RRF_score(doc) = sum over terms:
            1/(k + bm25_rank) + 1/(k + embed_rank)

        Args:
            search_terms: search phrases
            corpus: list of document dicts
            k: RRF parameter (higher = more weight to lower ranks)

        Returns:
            Sorted list of SearchResultItems (descending RRF score)
        """
        n = len(corpus)
        if n == 0:
            return []

        # Tokenize corpus for BM25
        tokenized_corpus = [_tokenize(doc["text"]) for doc in corpus]

        # Check for empty tokenized docs (BM25Okapi needs at least one non-empty)
        if all(len(t) == 0 for t in tokenized_corpus):
            logger.warning("[MemoryVaultSearcher] All documents empty after tokenization")
            return []

        bm25 = BM25Okapi(tokenized_corpus)

        # Pre-compute corpus embeddings if available
        embeddings_available = (
            _EMBEDDING_AVAILABLE
            and EMBEDDING_SERVICE is not None
            and EMBEDDING_SERVICE.is_available()
        )
        corpus_embeddings = None
        if embeddings_available:
            try:
                texts = [doc["text"][:512] for doc in corpus]  # truncate for efficiency
                corpus_embeddings = EMBEDDING_SERVICE.embed_batch(texts)
            except Exception as e:
                logger.warning(f"[MemoryVaultSearcher] Embedding batch failed, BM25-only: {e}")
                embeddings_available = False

        # Accumulate RRF scores per document
        rrf_scores = np.zeros(n)
        best_bm25_rank = np.full(n, n)   # track best rank across terms
        best_embed_rank = np.full(n, n)

        for term in search_terms:
            # BM25 scores for this term
            tokenized_term = _tokenize(term)
            if tokenized_term:
                bm25_scores = bm25.get_scores(tokenized_term)
                bm25_order = np.argsort(-bm25_scores)  # descending
                bm25_ranks = np.empty_like(bm25_order)
                bm25_ranks[bm25_order] = np.arange(n)

                for i in range(n):
                    rrf_scores[i] += 1.0 / (k + bm25_ranks[i])
                    best_bm25_rank[i] = min(best_bm25_rank[i], bm25_ranks[i])
            else:
                bm25_ranks = np.arange(n)  # neutral if no tokens

            # Embedding scores for this term
            if embeddings_available and corpus_embeddings is not None:
                try:
                    term_embedding = EMBEDDING_SERVICE.embed(term)
                    if term_embedding is not None:
                        # Cosine similarity
                        norms = np.linalg.norm(corpus_embeddings, axis=1) * np.linalg.norm(term_embedding)
                        norms = np.where(norms == 0, 1e-10, norms)
                        cosine_scores = np.dot(corpus_embeddings, term_embedding) / norms
                        embed_order = np.argsort(-cosine_scores)
                        embed_ranks = np.empty_like(embed_order)
                        embed_ranks[embed_order] = np.arange(n)

                        for i in range(n):
                            rrf_scores[i] += 1.0 / (k + embed_ranks[i])
                            best_embed_rank[i] = min(best_embed_rank[i], embed_ranks[i])
                except Exception as e:
                    logger.warning(f"[MemoryVaultSearcher] Embedding search failed for '{term}': {e}")

        # Apply source-type weights to prevent LLM telephone:
        # Original source material (Knowledge, Beliefs) ranks above
        # LLM-generated turn summaries unless turns score much higher.
        for i in range(n):
            weight = _SOURCE_TYPE_WEIGHT.get(corpus[i]["source_type"], 0.8)
            rrf_scores[i] *= weight

        # Sort by weighted RRF score descending
        sorted_indices = np.argsort(-rrf_scores)

        results = []
        for idx in sorted_indices:
            score = rrf_scores[idx]
            if score <= 0:
                continue
            doc = corpus[idx]
            results.append(SearchResultItem(
                document_path=doc["document_path"],
                source_type=doc["source_type"],
                node_id=doc["node_id"],
                rrf_score=float(score),
                bm25_rank=int(best_bm25_rank[idx]),
                embedding_rank=int(best_embed_rank[idx]),
                snippet=doc["text"][:200],
                source="search",
            ))

        return results

    def _collect_always_include(
        self,
        all_results: List[SearchResultItem],
        include_preferences: bool,
        include_n_minus_1: bool,
        current_turn: int,
        reference_turns: Optional[List[int]],
        corpus: List[Dict[str, str]],
    ) -> List[SearchResultItem]:
        """Collect always-include items, promoting them from ranked results or corpus.

        Returns a list of items that MUST appear in final results regardless of
        their search rank. Items already in the ranked results are promoted
        (keeping their search score); items not found in results are created
        from the corpus with source="always_include".
        """
        # Build lookups
        results_by_node = {r.node_id: r for r in all_results}
        corpus_by_node = {doc["node_id"]: doc for doc in corpus}

        collected = []
        seen = set()

        def _ensure(node_id: str) -> None:
            if node_id in seen:
                return
            seen.add(node_id)

            # Promote from ranked results if present (keeps search score)
            existing = results_by_node.get(node_id)
            if existing:
                # Mark as always_include so caller knows it has a reserved slot
                existing.source = "always_include"
                collected.append(existing)
                return

            # Not in results — create from corpus
            doc = corpus_by_node.get(node_id)
            if not doc:
                return
            collected.append(SearchResultItem(
                document_path=doc["document_path"],
                source_type=doc["source_type"],
                node_id=doc["node_id"],
                rrf_score=0.0,
                bm25_rank=len(corpus),
                embedding_rank=len(corpus),
                snippet=doc["text"][:200],
                source="always_include",
            ))

        # Always-include: preferences
        if include_preferences:
            _ensure(f"preference:user:{self.user_id}")
            _ensure("session:preferences")

        # Always-include: N-1 turn
        if include_n_minus_1 and current_turn > 1:
            n1 = current_turn - 1
            _ensure(f"turn:{n1}")

        # Always-include: explicitly referenced turns
        if reference_turns:
            for turn_num in reference_turns:
                _ensure(f"turn:{turn_num}")

        return collected

    def _load_content(self, document_path: str) -> str:
        """Load full content from a document path."""
        try:
            p = Path(document_path)
            if p.exists():
                return p.read_text()[:3000]  # cap at 3000 chars for synthesis
        except Exception as e:
            logger.warning(f"[MemoryVaultSearcher] Error loading {document_path}: {e}")
        return ""
