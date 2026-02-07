"""
Search-First Context Gatherer result dataclasses.

Phase 2.1 v2.0: LLM generates search terms → code does BM25 + embedding
hybrid search → only matching documents go to synthesis.

Architecture Reference:
    architecture/main-system-patterns/phase2.1-context-gathering-retrieval.md
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class SearchResultItem:
    """A single result from hybrid search."""
    document_path: str
    source_type: str       # turn_summary | preference | fact | research_cache | visit_record
    node_id: str           # "turn:235", "memory:Knowledge/...", "preference:user:default"
    rrf_score: float
    bm25_rank: int
    embedding_rank: int
    snippet: str           # first 200 chars of matching content
    source: str            # "search" | "always_include"
    content: str = ""      # full document text (loaded for synthesis)


@dataclass
class SearchResults:
    """Aggregated search results from MemoryVaultSearcher."""
    search_terms_used: List[str]
    results: List[SearchResultItem]
    stats: Dict[str, int]
    include_preferences: bool
    include_n_minus_1: bool

    def to_observability_dict(self) -> dict:
        """Serialize for retrieval_plan.json observability output."""
        return {
            "version": "2.0_search_first",
            "search_terms_used": self.search_terms_used,
            "include_preferences": self.include_preferences,
            "include_n_minus_1": self.include_n_minus_1,
            "stats": self.stats,
            "results": [
                {
                    "document_path": r.document_path,
                    "source_type": r.source_type,
                    "node_id": r.node_id,
                    "rrf_score": round(r.rrf_score, 4),
                    "bm25_rank": r.bm25_rank,
                    "embedding_rank": r.embedding_rank,
                    "snippet": r.snippet[:200],
                    "source": r.source,
                }
                for r in self.results
            ],
        }
