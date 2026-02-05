"""
orchestrator/cache_mcp.py

Unified Cache MCP API
Provides MCP-style endpoints for cache operations across all cache layers.
"""
import logging
from typing import Dict, Any, Optional, List

from apps.services.tool_server.shared_state.cache_registry import get_cache_registry
from apps.services.tool_server.shared_state.context_fingerprint import compute_fingerprint
from apps.services.tool_server.shared_state.preference_snapshot import create_snapshot, get_snapshot

logger = logging.getLogger(__name__)


async def cache_fetch(
    cache_type: str,
    key: Optional[str] = None,
    session_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    query: Optional[str] = None,
    cascade: bool = False
) -> Dict[str, Any]:
    """
    Fetch entry from cache.

    MCP Endpoint: /cache.fetch

    Args:
        cache_type: Cache layer (response, claims, tools)
        key: Explicit cache key (if not provided, computed from session_id/context/query)
        session_id: Session identifier
        context: Session context
        query: Query string
        cascade: Use cascading lookup across layers

    Returns:
        {
            "found": bool,
            "cache_type": str,  # Which layer hit (if cascade)
            "entry": CacheEntry dict or None,
            "key": str  # Cache key used
        }
    """
    registry = await get_cache_registry()

    # Compute key if not provided
    if key is None:
        if session_id is None:
            return {
                "error": "Either key or session_id must be provided",
                "found": False
            }

        fingerprint_result = compute_fingerprint(
            session_id=session_id,
            context=context,
            query=query
        )
        key = fingerprint_result.primary

    # Cascading lookup
    if cascade:
        result = await registry.get_cascade(key)
        if result:
            entry, hit_cache_type = result
            return {
                "found": True,
                "cache_type": hit_cache_type,
                "entry": {
                    "key": entry.key,
                    "value": entry.value,
                    "created_at": entry.created_at,
                    "expires_at": entry.expires_at,
                    "hits": entry.hits,
                    "quality": entry.quality,
                    "ttl_remaining": entry.ttl_remaining,
                    "metadata": entry.metadata
                },
                "key": key
            }
        else:
            return {
                "found": False,
                "cache_type": None,
                "entry": None,
                "key": key
            }

    # Single-layer lookup
    entry = await registry.get(cache_type, key)
    if entry:
        return {
            "found": True,
            "cache_type": cache_type,
            "entry": {
                "key": entry.key,
                "value": entry.value,
                "created_at": entry.created_at,
                "expires_at": entry.expires_at,
                "hits": entry.hits,
                "quality": entry.quality,
                "ttl_remaining": entry.ttl_remaining,
                "metadata": entry.metadata
            },
            "key": key
        }
    else:
        return {
            "found": False,
            "cache_type": cache_type,
            "entry": None,
            "key": key
        }


async def cache_store(
    cache_type: str,
    value: Any,
    key: Optional[str] = None,
    session_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    query: Optional[str] = None,
    ttl: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
    quality: float = 0.0,
    claims: Optional[List[str]] = None,
    create_preference_snapshot: bool = False,
    turn_number: int = 0
) -> Dict[str, Any]:
    """
    Store entry in cache.

    MCP Endpoint: /cache.store

    Args:
        cache_type: Cache layer (response, claims, tools)
        value: Value to cache
        key: Explicit cache key (if not provided, computed from session_id/context/query)
        session_id: Session identifier
        context: Session context
        query: Query string
        ttl: Time-to-live in seconds
        metadata: Additional metadata
        quality: Quality score (0.0-1.0)
        claims: Related claim IDs
        create_preference_snapshot: Create preference snapshot
        turn_number: Turn number (for snapshot)

    Returns:
        {
            "stored": bool,
            "key": str,
            "snapshot_id": str or None  # If preference snapshot created
        }
    """
    registry = await get_cache_registry()

    # Create preference snapshot if requested
    snapshot_id = None
    if create_preference_snapshot and session_id and context:
        preferences = context.get('preferences', {})
        if preferences:
            snapshot_id = await create_snapshot(session_id, preferences, turn_number)
            # Add snapshot ID to metadata
            if metadata is None:
                metadata = {}
            metadata['preference_snapshot_id'] = snapshot_id
            logger.info(
                f"[CacheMCP] Created preference snapshot {snapshot_id} "
                f"for session {session_id[:8]}"
            )

    # Compute key if not provided
    if key is None:
        if session_id is None:
            return {
                "error": "Either key or session_id must be provided",
                "stored": False
            }

        fingerprint_result = compute_fingerprint(
            session_id=session_id,
            context=context,
            query=query
        )
        key = fingerprint_result.primary

    # Store entry
    entry = await registry.put(
        cache_type=cache_type,
        key=key,
        value=value,
        ttl=ttl,
        metadata=metadata,
        quality=quality,
        claims=claims
    )

    if entry:
        return {
            "stored": True,
            "key": key,
            "snapshot_id": snapshot_id,
            "size_bytes": entry.size_bytes
        }
    else:
        return {
            "stored": False,
            "error": f"Failed to store in {cache_type} cache",
            "key": key
        }


async def cache_invalidate(
    pattern: str = "*",
    cache_types: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Invalidate cache entries matching pattern.

    MCP Endpoint: /cache.invalidate

    Args:
        pattern: Glob pattern for keys (* = all)
        cache_types: Cache layers to invalidate (None = all)

    Returns:
        {
            "invalidated": bool,
            "pattern": str,
            "cache_types": List[str]
        }
    """
    registry = await get_cache_registry()

    await registry.invalidate(pattern=pattern, cache_types=cache_types)

    return {
        "invalidated": True,
        "pattern": pattern,
        "cache_types": cache_types or "all"
    }


async def cache_stats(
    cache_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get cache statistics.

    MCP Endpoint: /cache.stats

    Args:
        cache_type: Specific cache layer (None = global)

    Returns:
        Global stats or layer-specific stats
    """
    registry = await get_cache_registry()

    if cache_type:
        # Layer-specific stats
        stats = await registry.get_layer_stats(cache_type)
        if stats:
            return {
                "cache_type": cache_type,
                "stats": stats
            }
        else:
            return {
                "error": f"Cache type {cache_type} not found"
            }
    else:
        # Global stats
        global_stats = await registry.get_stats()
        return {
            "total_entries": global_stats.total_entries,
            "total_size_mb": global_stats.total_size_mb,
            "total_hits": global_stats.total_hits,
            "cascade_hit_rate": global_stats.cascade_hit_rate,
            "layers": {
                cache_type: {
                    "entry_count": layer_stats.entry_count,
                    "total_size_mb": layer_stats.total_size_mb,
                    "total_hits": layer_stats.total_hits,
                    "hit_rate": layer_stats.hit_rate,
                    "avg_quality": layer_stats.avg_quality,
                    "expired_count": layer_stats.expired_count
                }
                for cache_type, layer_stats in global_stats.layers.items()
            },
            "cascade_order": registry.get_cascade_order(),
            "cascade_hits": registry.get_cascade_stats()
        }


async def cache_list(
    cache_type: str,
    filters: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None
) -> Dict[str, Any]:
    """
    List cache entries with optional filters.

    MCP Endpoint: /cache.list

    Args:
        cache_type: Cache layer
        filters: Filter criteria (e.g., {"quality__gte": 0.8})
        limit: Maximum number of results

    Returns:
        {
            "entries": List[Dict],
            "count": int,
            "cache_type": str
        }
    """
    registry = await get_cache_registry()

    entries = await registry.list_entries(cache_type, filters=filters, limit=limit)

    return {
        "entries": [
            {
                "key": entry.key,
                "cache_type": entry.cache_type,
                "created_at": entry.created_at,
                "expires_at": entry.expires_at,
                "hits": entry.hits,
                "quality": entry.quality,
                "ttl_remaining": entry.ttl_remaining,
                "size_bytes": entry.size_bytes,
                "metadata": entry.metadata
            }
            for entry in entries
        ],
        "count": len(entries),
        "cache_type": cache_type
    }


async def preference_snapshot_get(snapshot_id: str) -> Dict[str, Any]:
    """
    Get preference snapshot by ID.

    MCP Endpoint: /preference.snapshot.get

    Args:
        snapshot_id: Snapshot identifier

    Returns:
        Snapshot data or error
    """
    snapshot = await get_snapshot(snapshot_id)

    if snapshot:
        return {
            "found": True,
            "snapshot": {
                "snapshot_id": snapshot.snapshot_id,
                "session_id": snapshot.session_id,
                "preferences": snapshot.preferences,
                "created_at": snapshot.created_at,
                "turn_number": snapshot.turn_number,
                "fingerprint": snapshot.fingerprint
            }
        }
    else:
        return {
            "found": False,
            "error": f"Snapshot {snapshot_id} not found"
        }


# MCP tool definitions for registration
MCP_TOOLS = [
    {
        "name": "cache.fetch",
        "description": "Fetch entry from cache (supports cascading lookup)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cache_type": {"type": "string", "description": "Cache layer (response, claims, tools)"},
                "key": {"type": "string", "description": "Cache key (optional if session_id provided)"},
                "session_id": {"type": "string", "description": "Session identifier"},
                "context": {"type": "object", "description": "Session context"},
                "query": {"type": "string", "description": "Query string"},
                "cascade": {"type": "boolean", "description": "Use cascading lookup", "default": False}
            }
        },
        "handler": cache_fetch
    },
    {
        "name": "cache.store",
        "description": "Store entry in cache with optional preference snapshot",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cache_type": {"type": "string", "description": "Cache layer (response, claims, tools)"},
                "value": {"description": "Value to cache"},
                "key": {"type": "string", "description": "Cache key (optional if session_id provided)"},
                "session_id": {"type": "string", "description": "Session identifier"},
                "context": {"type": "object", "description": "Session context"},
                "query": {"type": "string", "description": "Query string"},
                "ttl": {"type": "integer", "description": "Time-to-live in seconds"},
                "quality": {"type": "number", "description": "Quality score (0.0-1.0)", "default": 0.0},
                "create_preference_snapshot": {"type": "boolean", "default": False}
            },
            "required": ["cache_type", "value"]
        },
        "handler": cache_store
    },
    {
        "name": "cache.invalidate",
        "description": "Invalidate cache entries matching pattern",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (* = all)", "default": "*"},
                "cache_types": {"type": "array", "items": {"type": "string"}, "description": "Cache layers to invalidate"}
            }
        },
        "handler": cache_invalidate
    },
    {
        "name": "cache.stats",
        "description": "Get cache statistics (global or layer-specific)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cache_type": {"type": "string", "description": "Specific cache layer (optional)"}
            }
        },
        "handler": cache_stats
    },
    {
        "name": "cache.list",
        "description": "List cache entries with optional filters",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cache_type": {"type": "string", "description": "Cache layer"},
                "filters": {"type": "object", "description": "Filter criteria"},
                "limit": {"type": "integer", "description": "Maximum results"}
            },
            "required": ["cache_type"]
        },
        "handler": cache_list
    },
    {
        "name": "preference.snapshot.get",
        "description": "Get preference snapshot by ID",
        "inputSchema": {
            "type": "object",
            "properties": {
                "snapshot_id": {"type": "string", "description": "Snapshot identifier"}
            },
            "required": ["snapshot_id"]
        },
        "handler": preference_snapshot_get
    }
]
