"""
TurnSearchIndex: Semantic + keyword search over turn documents.

This module provides search capabilities for the Context Gatherer to find
relevant prior turns and documents. It supports:
- Semantic search using embeddings
- Keyword filtering using metadata
- Session scoping (users only see their own turns) - via SQLite index
- Recency weighting
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
import logging

from libs.gateway.context.context_document import TurnMetadata, ContextDocument
from .turn_index_db import get_turn_index_db, TurnIndexDB

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result from the turn index."""
    turn_number: int
    session_id: str
    document_path: str
    relevance_score: float
    snippet: str
    metadata: Optional[TurnMetadata] = None

    def to_dict(self) -> dict:
        return {
            "turn_number": self.turn_number,
            "session_id": self.session_id,
            "document_path": self.document_path,
            "relevance_score": self.relevance_score,
            "snippet": self.snippet,
            "metadata": self.metadata.to_dict() if self.metadata else None
        }


class TurnSearchIndex:
    """
    Semantic + keyword search over turn documents.

    Provides session-scoped search with recency weighting.

    Usage:
        index = TurnSearchIndex(session_id="default")
        results = index.search("What's my favorite hamster?", limit=10)

        # Results are scoped to the session and sorted by relevance
        for result in results:
            print(f"Turn {result.turn_number}: {result.snippet}")
    """

    def __init__(
        self,
        session_id: str,
        turns_dir: Path = None,
        sessions_dir: Path = None,
        memory_dir: Path = None,
        embedding_service: Any = None,
        use_sqlite_index: bool = True,
        user_id: str = None
    ):
        self.session_id = session_id
        self.user_id = user_id or "default"
        # Use new consolidated path structure under obsidian_memory/Users/
        self.turns_dir = turns_dir or Path(f"panda_system_docs/obsidian_memory/Users/{self.user_id}/turns")
        self.sessions_dir = sessions_dir or Path(f"panda_system_docs/obsidian_memory/Users/{self.user_id}/sessions")
        self.memory_dir = memory_dir or Path(f"panda_system_docs/obsidian_memory/Users/{self.user_id}/memory")
        self.embedding_service = embedding_service
        self.use_sqlite_index = use_sqlite_index

        # SQLite index for efficient session-scoped queries
        self._index_db: Optional[TurnIndexDB] = None
        if use_sqlite_index:
            try:
                self._index_db = get_turn_index_db()
            except Exception as e:
                logger.warning(f"[TurnSearchIndex] SQLite index unavailable, falling back to directory scan: {e}")
                self._index_db = None

        # Cache for loaded metadata
        self._metadata_cache: Dict[int, TurnMetadata] = {}

    def search(
        self,
        query: str,
        limit: int = 10,
        min_relevance: float = 0.3,
        recency_weight: float = 0.1,
        keyword_boost: float = 0.2
    ) -> List[SearchResult]:
        """
        Search for relevant turns matching the query.

        Args:
            query: The search query
            limit: Maximum number of results
            min_relevance: Minimum relevance score (0-1)
            recency_weight: Weight for recency (higher = prefer recent)
            keyword_boost: Boost for keyword matches

        Returns:
            List of SearchResult sorted by relevance
        """
        results = []

        # Get all turn directories for this session
        turn_dirs = self._get_session_turns()

        if not turn_dirs:
            logger.debug(f"No turns found for session {self.session_id}")
            return []

        # Extract query keywords for keyword matching
        query_keywords = self._extract_keywords(query.lower())

        for turn_dir in turn_dirs:
            turn_number = self._parse_turn_number(turn_dir.name)
            if turn_number is None:
                continue

            # Load metadata
            metadata = self._load_metadata(turn_dir, turn_number)
            if metadata is None:
                continue

            # Skip turns from other sessions
            if metadata.session_id != self.session_id:
                continue

            # Calculate relevance score
            relevance = self._calculate_relevance(
                query=query,
                query_keywords=query_keywords,
                turn_dir=turn_dir,
                metadata=metadata,
                recency_weight=recency_weight,
                keyword_boost=keyword_boost
            )

            if relevance >= min_relevance:
                # Generate snippet from context.md
                snippet = self._generate_snippet(turn_dir, query)

                results.append(SearchResult(
                    turn_number=turn_number,
                    session_id=self.session_id,
                    document_path=str(turn_dir / "context.md"),
                    relevance_score=relevance,
                    snippet=snippet,
                    metadata=metadata
                ))

        # Sort by relevance (descending)
        results.sort(key=lambda r: r.relevance_score, reverse=True)

        return results[:limit]

    def search_preferences(self) -> Dict[str, Any]:
        """
        Load user preferences from the session directory.

        Returns:
            Dictionary of preferences
        """
        prefs_file = self.sessions_dir / self.session_id / "preferences.md"
        if not prefs_file.exists():
            return {}

        # Parse preferences.md
        content = prefs_file.read_text()
        prefs = {}

        for line in content.split("\n"):
            if line.startswith("- **") and ":**" in line:
                # Parse "- **key:** value" format
                parts = line.split(":**", 1)
                if len(parts) == 2:
                    key = parts[0].replace("- **", "").strip()
                    value = parts[1].strip()
                    prefs[key] = value

        return prefs

    def search_facts(self) -> List[str]:
        """
        Load user facts from the session directory.

        Returns:
            List of fact strings
        """
        facts_file = self.sessions_dir / self.session_id / "facts.md"
        if not facts_file.exists():
            return []

        content = facts_file.read_text()
        facts = []

        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("- "):
                facts.append(line[2:])

        return facts

    def search_memory(self, query: str, limit: int = 5) -> List[SearchResult]:
        """
        Search long-term memory for relevant documents.

        Args:
            query: The search query
            limit: Maximum number of results

        Returns:
            List of SearchResult from memory
        """
        results = []
        memory_long_term = self.memory_dir / "long_term" / "json"

        if not memory_long_term.exists():
            return []

        query_keywords = self._extract_keywords(query.lower())

        for memory_file in memory_long_term.glob("*.json"):
            try:
                data = json.loads(memory_file.read_text())
                content = data.get("body_md", "") or data.get("summary", "") or ""
                if not content:
                    continue

                # Simple keyword matching for memory
                content_lower = content.lower()
                keyword_matches = sum(1 for kw in query_keywords if kw in content_lower)

                if keyword_matches > 0:
                    relevance = min(keyword_matches / len(query_keywords), 1.0) if query_keywords else 0.3
                    snippet = content[:200] + "..." if len(content) > 200 else content

                    results.append(SearchResult(
                        turn_number=0,  # Memory doesn't have turn numbers
                        session_id=self.session_id,
                        document_path=str(memory_file),
                        relevance_score=relevance,
                        snippet=snippet,
                        metadata=None
                    ))
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to load memory file {memory_file}: {e}")
                continue

        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[:limit]

    def _get_session_turns(self) -> List[Path]:
        """
        Get turn directories for this session.

        Uses SQLite index for O(1) session filtering when available,
        falls back to O(n) directory scan otherwise.
        """
        # Try SQLite index first (efficient O(1) lookup)
        if self._index_db is not None:
            try:
                indexed_turns = self._index_db.get_session_turns(
                    session_id=self.session_id,
                    limit=100
                )
                if indexed_turns:
                    # Convert to Path objects
                    return [Path(entry.turn_dir) for entry in indexed_turns]
                # Fall through to directory scan if no indexed turns
                logger.debug(f"[TurnSearchIndex] No indexed turns for {self.session_id}, falling back to scan")
            except Exception as e:
                logger.warning(f"[TurnSearchIndex] SQLite query failed: {e}")

        # Fallback: Directory scan (O(n) - slow for many turns)
        if not self.turns_dir.exists():
            return []

        turn_dirs = []
        for item in self.turns_dir.iterdir():
            if item.is_dir() and item.name.startswith("turn_"):
                turn_dirs.append(item)

        # Sort by turn number (descending, most recent first)
        turn_dirs.sort(key=lambda p: self._parse_turn_number(p.name) or 0, reverse=True)
        return turn_dirs

    def _parse_turn_number(self, dir_name: str) -> Optional[int]:
        """Parse turn number from directory name like 'turn_000743'."""
        try:
            # Handle both 'turn_000743' and 'turn_000743_test' formats
            parts = dir_name.replace("turn_", "").split("_")
            return int(parts[0])
        except (ValueError, IndexError):
            return None

    def _load_metadata(self, turn_dir: Path, turn_number: int) -> Optional[TurnMetadata]:
        """Load metadata from cache or disk."""
        if turn_number in self._metadata_cache:
            return self._metadata_cache[turn_number]

        metadata = TurnMetadata.load(turn_dir)
        if metadata:
            self._metadata_cache[turn_number] = metadata

        return metadata

    def _calculate_relevance(
        self,
        query: str,
        query_keywords: List[str],
        turn_dir: Path,
        metadata: TurnMetadata,
        recency_weight: float,
        keyword_boost: float
    ) -> float:
        """
        Calculate relevance score for a turn.

        Components:
        - Keyword match score (0-1) - REQUIRED for relevance
        - Content match score (0-1) - checked if metadata doesn't match
        - Topic similarity (if available)
        - Recency score - ONLY applied as boost when there's relevance signal
        - Quality score - weights the final relevance (degraded turns rank lower)

        Key principle: Recency alone should NOT make a turn relevant.
        A turn must have SOME keyword/topic/content match to be considered.

        Quality score integration:
        The quality_score (0.0-1.0) from metadata is used as a multiplier on
        the final relevance. This ensures that turns degraded by the Freshness
        Analyzer (due to outdated information) rank lower than fresh turns.
        """
        relevance_signal = 0.0  # Signal from keyword/topic/content matching
        has_relevance = False

        # Keyword matching against metadata keywords
        if metadata.keywords and query_keywords:
            matching_keywords = set(query_keywords) & set(kw.lower() for kw in metadata.keywords)
            if matching_keywords:
                keyword_score = len(matching_keywords) / len(query_keywords)
                relevance_signal += keyword_score * keyword_boost
                has_relevance = True

        # Keyword matching against topic
        if metadata.topic:
            topic_keywords = self._extract_keywords(metadata.topic.lower())
            topic_matches = set(query_keywords) & set(topic_keywords)
            if topic_matches:
                relevance_signal += 0.3  # Topic match boost
                has_relevance = True

        # ALWAYS check content if no metadata match yet
        # This catches cases where metadata is incomplete but content is relevant
        if not has_relevance:
            context_file = turn_dir / "context.md"
            if context_file.exists():
                content = context_file.read_text().lower()
                content_matches = sum(1 for kw in query_keywords if kw in content)
                if content_matches > 0:
                    content_score = min(content_matches / len(query_keywords), 1.0) if query_keywords else 0
                    relevance_signal += content_score * 0.3
                    has_relevance = True

        # If no relevance signal at all, return 0 (recency alone is NOT enough)
        if not has_relevance:
            return 0.0

        # Now add content boost if we haven't checked yet (had metadata match)
        if has_relevance and relevance_signal < 0.3:
            context_file = turn_dir / "context.md"
            if context_file.exists():
                content = context_file.read_text().lower()
                content_matches = sum(1 for kw in query_keywords if kw in content)
                if content_matches > 0:
                    content_score = min(content_matches / len(query_keywords), 1.0) if query_keywords else 0
                    relevance_signal += content_score * 0.3

        # Add recency boost ONLY when there's already relevance
        # Recency helps rank RELEVANT turns, not make irrelevant turns appear relevant
        if metadata.timestamp and has_relevance:
            age_hours = (datetime.now().timestamp() - metadata.timestamp) / 3600
            recency_score = math.exp(-age_hours * recency_weight / 24)  # Decay over 24 hours
            relevance_signal += recency_score * 0.2

        # Normalize to 0-1
        base_relevance = min(relevance_signal, 1.0)

        # Apply quality_score as a weighting factor
        # This ensures degraded turns (from Freshness Analyzer) rank lower
        # quality_score of 1.0 = no change, 0.3 = 70% reduction in relevance
        quality_score = getattr(metadata, 'quality_score', None)
        if quality_score is not None and quality_score < 1.0:
            # Use sqrt to soften the impact (0.3 quality → 0.55 multiplier instead of 0.3)
            # This prevents completely burying degraded turns, but still ranks them lower
            quality_multiplier = max(0.2, quality_score ** 0.5)
            final_relevance = base_relevance * quality_multiplier
        else:
            final_relevance = base_relevance

        return final_relevance

    def _generate_snippet(self, turn_dir: Path, query: str, max_length: int = 200) -> str:
        """Generate a snippet from context.md relevant to the query."""
        context_file = turn_dir / "context.md"
        if not context_file.exists():
            return ""

        content = context_file.read_text()

        # Try to find the most relevant section
        query_keywords = self._extract_keywords(query.lower())

        # Split into paragraphs
        paragraphs = content.split("\n\n")

        best_paragraph = ""
        best_score = 0

        for para in paragraphs:
            if len(para) < 10:
                continue
            para_lower = para.lower()
            matches = sum(1 for kw in query_keywords if kw in para_lower)
            if matches > best_score:
                best_score = matches
                best_paragraph = para

        if best_paragraph:
            snippet = best_paragraph[:max_length]
            if len(best_paragraph) > max_length:
                snippet += "..."
            return snippet

        # Fallback: first meaningful paragraph
        for para in paragraphs:
            if len(para) > 20 and not para.startswith("#"):
                return para[:max_length] + ("..." if len(para) > max_length else "")

        return content[:max_length]

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text for matching."""
        import re

        # Tokenize
        words = re.findall(r'\b[a-z]{3,}\b', text)

        # Remove stop words
        stop_words = {
            'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had',
            'her', 'was', 'one', 'our', 'out', 'has', 'have', 'been', 'would',
            'could', 'should', 'will', 'just', 'what', 'with', 'this', 'that',
            'from', 'they', 'which', 'their', 'there', 'about', 'into', 'more',
            'some', 'than', 'them', 'then', 'these', 'when', 'where', 'your',
            'what', 'whats', 'favorite', 'find', 'tell', 'know', 'want'
        }

        return [w for w in words if w not in stop_words]

    def index_turn(self, turn_dir: Path, metadata: TurnMetadata):
        """
        Add a turn to the index.

        Saves metadata to disk and SQLite index for efficient retrieval.
        Includes learning fields (validation_outcome, quality_score, strategy_summary)
        for future turn similarity search and learning from past turns.
        """
        # Save metadata to disk
        metadata.save(turn_dir)
        self._metadata_cache[metadata.turn_number] = metadata

        # Add to SQLite index for efficient session-scoped queries
        if self._index_db is not None:
            try:
                self._index_db.index_turn(
                    turn_number=metadata.turn_number,
                    session_id=metadata.session_id,
                    timestamp=metadata.timestamp,
                    topic=metadata.topic,
                    intent=metadata.action_needed,
                    keywords=metadata.keywords,
                    # turn_dir removed in schema v4 - paths are computed from user_id + turn_number
                    user_id=self.user_id,
                    # Learning fields (per MEMORY_ARCHITECTURE.md)
                    validation_outcome=metadata.validation_outcome,
                    strategy_summary=metadata.strategy_summary,
                    quality_score=metadata.quality_score
                )
            except Exception as e:
                logger.warning(f"[TurnSearchIndex] Failed to add to SQLite index: {e}")
