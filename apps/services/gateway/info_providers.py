"""
Information Providers for Reflection Loop

Provides various information sources that meta-reflection can request:
- Memory: Long-term user memories and preferences
- Quick Search: Fast web search for current facts
- Claims: Previously verified claims from claim registry

Author: Pandora Team
Created: 2025-11-10
"""

from typing import Dict, List, Any, Callable, Optional
from dataclasses import dataclass
import logging
import json

logger = logging.getLogger(__name__)


@dataclass
class InfoResult:
    """Result from an information provider"""
    source: str  # "memory", "search", etc.
    query: str
    results: List[Dict[str, Any]]
    success: bool
    error: Optional[str] = None
    tokens_used: int = 0


class InfoProviderRegistry:
    """Registry of information providers for reflection loop"""

    def __init__(self):
        self.providers: Dict[str, Callable] = {}
        self.stats: Dict[str, int] = {}  # Track usage
        logger.info("[InfoProvider] Registry initialized")

    def register(self, name: str, provider: Callable):
        """Register an information provider"""
        self.providers[name] = provider
        self.stats[name] = 0
        logger.info(f"[InfoProvider] Registered: {name}")

    async def query(self, info_type: str, query: str, **kwargs) -> InfoResult:
        """Query an information provider"""
        if info_type not in self.providers:
            return InfoResult(
                source=info_type,
                query=query,
                results=[],
                success=False,
                error=f"Unknown provider: {info_type}"
            )

        try:
            provider = self.providers[info_type]
            results = await provider(query, **kwargs)

            self.stats[info_type] += 1

            return InfoResult(
                source=info_type,
                query=query,
                results=results,
                success=True,
                tokens_used=self._estimate_tokens(results)
            )

        except Exception as e:
            logger.error(f"[InfoProvider] Error in {info_type}: {e}")
            return InfoResult(
                source=info_type,
                query=query,
                results=[],
                success=False,
                error=str(e)
            )

    def _estimate_tokens(self, results: List[Dict]) -> int:
        """Rough token estimate"""
        try:
            return len(json.dumps(results)) // 4  # ~4 chars per token
        except:
            return 0

    def get_stats(self) -> Dict[str, int]:
        """Get usage statistics"""
        return self.stats.copy()


# Global registry
_registry: Optional[InfoProviderRegistry] = None


def get_info_registry() -> InfoProviderRegistry:
    """Get or create global info provider registry"""
    global _registry
    if _registry is None:
        _registry = InfoProviderRegistry()
    return _registry


# ========================================
# Provider Implementations
# ========================================


async def memory_provider(query: str, profile_id: str, k: int = 3, **kwargs) -> List[Dict[str, Any]]:
    """
    Query long-term memory for relevant information.

    Args:
        query: Search query
        profile_id: User profile ID
        k: Number of results

    Returns:
        List of memory results with content, metadata, and structured preferences
    """
    from apps.services.tool_server.memory_manager import MemoryManager

    memory_mgr = MemoryManager()

    try:
        memories = memory_mgr.query_memories(
            query_text=query,
            profile_id=profile_id,
            k=k,
            min_similarity=0.0  # Let MemoryStore handle scoring
        )

        # Format for reflection context
        formatted = []
        for mem in memories:
            result = {
                "content": mem.get("content", ""),
                "timestamp": mem.get("timestamp", ""),
                "relevance": mem.get("similarity", 0.0),
                "tags": mem.get("tags", []),
                "id": mem.get("id", "")
            }

            # Include structured preference if present
            if "preference" in mem:
                result["preference"] = mem["preference"]

            formatted.append(result)

        logger.info(f"[MemoryProvider] Found {len(formatted)} memories for: {query}")
        return formatted

    except Exception as e:
        logger.error(f"[MemoryProvider] Error: {e}")
        return []


async def quick_search_provider(query: str, max_results: int = 3, **kwargs) -> List[Dict[str, Any]]:
    """
    Perform quick web search for current facts.

    Args:
        query: Search query
        max_results: Max results to return

    Returns:
        List of search results with title, snippet, url
    """
    import aiohttp

    # Call tool server search endpoint
    orch_url = kwargs.get("orch_url", "http://127.0.0.1:8090")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{orch_url}/commerce.search",
                json={"query": query, "num_results": max_results},
                timeout=aiohttp.ClientTimeout(total=5.0)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("products", [])[:max_results]

                    logger.info(f"[QuickSearchProvider] Found {len(results)} results for: {query}")
                    return results
                else:
                    logger.warning(f"[QuickSearchProvider] Search failed: {resp.status}")
                    return []

    except Exception as e:
        logger.error(f"[QuickSearchProvider] Error: {e}")
        return []


async def claims_provider(query: str, k: int = 3, **kwargs) -> List[Dict[str, Any]]:
    """
    Query claim registry for verified claims.

    Args:
        query: Search query
        k: Number of claims

    Returns:
        List of claims with content and confidence
    """
    from apps.services.tool_server.shared_state.claims import ClaimRegistry

    try:
        registry = ClaimRegistry()
        claims = registry.query(query, k=k)

        logger.info(f"[ClaimsProvider] Found {len(claims)} claims for: {query}")
        return claims

    except Exception as e:
        logger.error(f"[ClaimsProvider] Error: {e}")
        return []


async def session_history_provider(query: str, session_id: str, n: int = 5, **kwargs) -> List[Dict[str, Any]]:
    """
    Get recent conversation turns from session history.

    Args:
        query: Not used (context-based)
        session_id: Session identifier
        n: Number of recent turns

    Returns:
        List of recent turns with role and content
    """
    # This would integrate with session storage
    # For now, return empty - can be implemented later
    logger.info(f"[SessionHistoryProvider] Called for session {session_id}")
    return []
