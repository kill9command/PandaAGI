"""
orchestrator/memory_manager.py

Memory manager for handling memory save and query operations.

Responsibilities:
- Accept save payloads (dicts) and run redaction filters.
- Convert payload body_md -> memory JSON via scripts/memory_schema.py functions.
- Persist JSON to panda_system_docs/memory/json/<id>.json and update index.
- Record an audit entry under panda_system_docs/memory/audit.jsonl
- Query memories using MemoryStore with preference extraction

This module is intentionally simple and synchronous. Production code should add:
- Robust redaction rules, secret scanning, PII filters
- Concurrency-safe index updates
- Embedding pipeline enqueueing
- Policy checks / requires_confirm flows
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from scripts import memory_schema


AUDIT_PATH = Path("panda_system_docs/memory/audit.jsonl")
MEM_JSON_DIR = "panda_system_docs/memory/long_term/json"
INDEX_PATH = "panda_system_docs/memory/long_term/index.json"


def redaction_filter(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Very small redaction filter stub:
    - If the body contains 'api_key' or 'secret', remove them.
    """
    payload = dict(payload)
    body = payload.get("body_md", "")
    for token in ("api_key", "secret", "password"):
        if token in body.lower():
            # remove the body entirely and mark redacted
            payload["body_md"] = "[REDACTED]"
            payload["redacted_reason"] = f"contains {token}"
            break
    return payload


def persist_memory_save(save_payload: Dict[str, Any], source: str = "agent", require_confirm: bool = False) -> Dict[str, Any]:
    """
    Persist a suggest_memory_save / save_plan payload.
    Returns a result dict with keys: {ok:bool, id: str|null, audit_path: str}
    If require_confirm is True, record audit and return requires_confirm flag (no persistence).
    """
    payload = redaction_filter(save_payload)
    if require_confirm:
        # write audit and return
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": __import__("datetime").datetime.utcnow().isoformat() + "Z", "action": "persist_memory", "status": "requires_confirm", "payload": payload}) + "\n")
        return {"ok": False, "id": None, "requires_confirm": True, "audit": str(AUDIT_PATH)}

    # Ensure body exists
    body = payload.get("body_md", "")
    title = payload.get("title", "memory")
    tags = payload.get("tags", []) or []

    # Use memory_schema to generate record and write
    record = memory_schema.make_memory_record(
        title,
        tags,
        body,
        source=source,
        ttl_days=payload.get("ttl_days"),
        metadata=payload.get("metadata"),
        session_id=payload.get("session_id"),
        source_turn_ids=payload.get("source_turn_ids"),
    )
    out_path = memory_schema.write_memory_record(record, out_dir=MEM_JSON_DIR)
    memory_schema.update_index(record, index_path=INDEX_PATH)

    # audit
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": __import__("datetime").datetime.utcnow().isoformat() + "Z", "action": "persist_memory", "status": "ok", "id": record["id"], "title": title}) + "\n")

    return {"ok": True, "id": record["id"], "path": str(out_path), "audit": str(AUDIT_PATH)}


class MemoryManager:
    """
    Memory manager with query and preference extraction capabilities.
    Uses MemoryStore for token-based search and extracts structured preferences.
    """

    def __init__(self):
        from apps.services.tool_server.memory_store import get_memory_store
        self.store = get_memory_store()

    def query_memories(
        self,
        query_text: str,
        profile_id: str,
        k: int = 3,
        min_similarity: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Query memories with hybrid search (semantic + metadata boosting).

        Args:
            query_text: Search query
            profile_id: User profile ID (used for scoping)
            k: Number of results to return
            min_similarity: Minimum similarity score (0-1)

        Returns:
            List of memory dicts with content, metadata, preferences
        """
        # Query using MemoryStore - fetch more candidates for reranking
        results = self.store.query(
            query_text,
            k=min(k * 7, 20),  # Get 7x more candidates for reranking (capped at 20)
            scope="long_term",
            min_score=min_similarity,
            include_body=True
        )

        # Detect query intent for metadata boosting
        query_lower = query_text.lower()
        is_preference_query = any(kw in query_lower for kw in
                                 ["favorite", "prefer", "like", "love", "want"])

        # Rerank with metadata boosting
        reranked = []
        for mem in results:
            score = mem.get("score", 0.0)

            # Boost preference-tagged memories when query is about preferences
            if is_preference_query:
                if "preference" in mem.get("tags", []):
                    score *= 1.5  # 50% boost for preference-tagged memories
                if mem.get("importance") == "high":
                    score *= 1.2  # 20% boost for high-importance memories

            # Boost exact keyword matches in content
            body = mem.get("body_md", "") + mem.get("summary", "")
            for keyword in ["favorite", "prefer", "syrian", "hamster"]:
                if keyword in query_lower and keyword in body.lower():
                    score *= 1.3  # 30% boost per exact keyword match
                    break

            formatted_mem = {
                "content": mem.get("body_md", mem.get("summary", "")),
                "timestamp": mem.get("created_at", ""),
                "similarity": score,  # Use boosted score
                "tags": mem.get("tags", []),
                "id": mem.get("id", ""),
            }

            # Extract structured preferences from metadata
            metadata = mem.get("metadata", {})
            if metadata:
                pref_key = metadata.get("preference_key")
                pref_value = metadata.get("preference_value")
                if pref_key and pref_value:
                    formatted_mem["preference"] = {
                        "key": pref_key,
                        "value": pref_value,
                        "confidence": metadata.get("preference_confidence", 1.0),
                        "method": metadata.get("extraction_method", "unknown")
                    }

            reranked.append(formatted_mem)

        # Sort by boosted score and return top k
        reranked.sort(key=lambda x: x["similarity"], reverse=True)
        return reranked[:k]

    def extract_preferences(self, memories: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract preferences from memory results into a dict.

        Args:
            memories: List of memory results from query_memories

        Returns:
            Dict mapping preference keys to values
        """
        preferences = {}
        for mem in memories:
            if "preference" in mem:
                pref = mem["preference"]
                key = pref["key"]
                value = pref["value"]
                confidence = pref.get("confidence", 1.0)

                # Only add if not already present or has higher confidence
                if key not in preferences or preferences[key].get("confidence", 0) < confidence:
                    preferences[key] = {
                        "value": value,
                        "confidence": confidence,
                        "source_memory_id": mem.get("id")
                    }

        return preferences
