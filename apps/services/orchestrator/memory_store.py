"""orchestrator.memory_store

Centralized memory persistence and retrieval helpers for chat short-term and
long-term storage. The store keeps a lightweight JSONL log for short-term
entries and persists long-term entries as structured JSON records using the
`scripts.memory_schema` helpers.

Responsibilities
- Classify incoming memory payloads into short-term (session/ephemeral) or
  long-term (durable knowledge) scopes.
- Persist memories to `panda_system_docs/memory/short_term/*.jsonl` or
  `panda_system_docs/memory/long_term/json/<id>.json`.
- Maintain simple indexes to accelerate retrieval without an external vector
  database.
- Provide a scoring routine that favors topic/tag matches and recent short-term
  notes, so Solver retrieval can ask for relevant memories only when they are a
  good fit for the current question (e.g., hamster topics).

The implementation intentionally avoids heavyweight dependencies so it can run
inside the orchestrator process without additional services. When a vector
index is available later, this module can be extended to emit embeddings in the
audit payloads while keeping backwards-compatible file formats.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from scripts import memory_schema

# Small English stopword list to reduce noise for keyword generation/scoring.
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "has",
    "have",
    "if",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "was",
    "were",
    "will",
    "with",
}


class MemoryStore:
    """Persist and query chat memories across short- and long-term scopes."""

    SHORT_DEFAULT_TTL_DAYS = 2

    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.audit_path = self.base_dir / "audit.jsonl"

        # Long-term layout mirrors the memory_schema defaults.
        self.long_term_dir = self.base_dir / "long_term"
        self.long_term_dir.mkdir(parents=True, exist_ok=True)
        self.long_json_dir = self.long_term_dir / "json"
        self.long_json_dir.mkdir(parents=True, exist_ok=True)
        self.long_index_path = self.long_term_dir / "index.json"

        # Short-term layout keeps append-only JSONL plus a materialized index.
        self.short_term_dir = self.base_dir / "short_term"
        self.short_term_dir.mkdir(parents=True, exist_ok=True)
        self.short_records_path = self.short_term_dir / "records.jsonl"
        self.short_index_path = self.short_term_dir / "index.json"
        self._promoted_cache: set[str] = set()

    # ------------------------------------------------------------------
    # Public API

    def save_memory(
        self,
        *,
        title: str,
        body_md: str,
        tags: Optional[Sequence[str]] = None,
        scope: str | None = None,
        ttl_days: Optional[int] = None,
        importance: str = "normal",
        source: str = "agent",
        metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        source_turn_ids: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """
        Persist a memory payload and return the canonical record metadata.

        The caller may request `scope` explicitly with ``short_term`` or
        ``long_term``. When omitted/``auto`` the store infers scope using
        heuristic signals (TTL, tags, body length, importance).
        """

        tags_list = list(tags or [])
        resolved_scope = self._resolve_scope(scope, ttl_days, tags_list, body_md, importance)

        created_at = _now()
        summary = memory_schema.extract_summary(body_md)
        keywords = self._extract_keywords(f"{title}\n{body_md}")
        topic = self._infer_topic(tags_list, summary, keywords)
        record_common = {
            "id": uuid.uuid4().hex,
            "title": title,
            "summary": summary,
            "topic": topic,
            "keywords": keywords,
            "tags": tags_list,
            "importance": importance,
            "source": source,
            "metadata": metadata or {},
            "created_at": created_at.isoformat(),
            "session_id": session_id,
            "source_turn_ids": list(source_turn_ids or []),
        }

        if resolved_scope == "long_term":
            record = memory_schema.make_memory_record(
                title,
                tags_list,
                body_md,
                source=source,
                ttl_days=ttl_days,
                topic=topic,
                keywords=keywords,
                importance=importance,
                metadata=metadata or {},
                source_turn_ids=list(source_turn_ids or []),
                session_id=session_id,
            )
            record["scope"] = "long_term"
            # Persist
            path = memory_schema.write_memory_record(record, out_dir=str(self.long_json_dir))
            memory_schema.update_index(record, index_path=str(self.long_index_path))
            self._write_audit(
                {
                    "action": "memory.save",
                    "scope": "long_term",
                    "id": record["id"],
                    "title": record.get("title"),
                    "path": str(path),
                }
            )
            return {"scope": "long_term", "record": record, "path": str(path)}

        # short_term flow
        ttl_effective = ttl_days if ttl_days is not None else self.SHORT_DEFAULT_TTL_DAYS
        expires_at = (created_at + timedelta(days=max(0, ttl_effective))).isoformat()
        trimmed_body = _truncate(body_md, 4000)
        record = {
            **record_common,
            "scope": "short_term",
            "ttl_days": ttl_days,
            "expires_at": expires_at,
            "body_md": trimmed_body,
        }
        self._append_short_record(record)
        self._refresh_short_index()
        self._write_audit(
            {
                "action": "memory.save",
                "scope": "short_term",
                "id": record["id"],
                "title": title,
                "expires_at": expires_at,
            }
        )
        return {"scope": "short_term", "record": record, "path": None}

    def save_search_preference(
        self,
        key: str,
        value: str,
        category: str,
    ) -> Dict[str, Any]:
        """Save a search preference to the memory store."""
        return self.save_memory(
            title=f"Search Preference: {key} = {value}",
            body_md=f"User has set a search preference to {key} {value}.",
            tags=["search_preference", category],
            scope="long_term",
            metadata={"key": key, "value": value, "category": category},
        )

    def get_search_preferences(self) -> List[Dict[str, Any]]:
        """Return all search preference memories for the user."""
        preferences = []
        for record in self._iter_long_term_records():
            if "search_preference" in record.get("tags", []):
                preferences.append(record)
        return preferences

    def save_source_discovery(
        self,
        item_type: str,
        category: str,
        discovery_data: Dict[str, Any],
        *,
        ttl_days: int = 30
    ) -> Dict[str, Any]:
        """
        Cache source discovery results for an item type/category.
        
        Args:
            item_type: "live_animal", "electronics", etc.
            category: "pet:hamster", "computing:laptop", etc.
            discovery_data: SourceDiscoveryResult dict
            ttl_days: How long to cache (default 30 days)
        
        Returns:
            Result of save_memory call
        """
        title = f"Trusted sources for {category}"
        
        trusted_sources = discovery_data.get("trusted_sources", [])
        seller_guidance = discovery_data.get("seller_type_guidance", [])
        avoid_signals = discovery_data.get("avoid_signals", [])
        search_strategies = discovery_data.get("search_strategies", [])
        
        # Build body markdown
        body_parts = [f"# Source Discovery: {category}"]
        
        if trusted_sources:
            body_parts.append("\n## Trusted Sources")
            for src in trusted_sources:
                domain = src.get("domain", "unknown")
                source_type = src.get("source_type", "unknown")
                trust_score = src.get("trust_score", 0.0)
                reasons = src.get("reasons", [])
                body_parts.append(f"- **{domain}** ({source_type}, score: {trust_score:.2f})")
                if reasons:
                    body_parts.append(f"  - {'; '.join(reasons)}")
        
        if seller_guidance:
            body_parts.append("\n## Seller Guidance")
            for guidance in seller_guidance:
                body_parts.append(f"- {guidance}")
        
        if avoid_signals:
            body_parts.append("\n## Avoid Signals")
            for signal in avoid_signals:
                body_parts.append(f"- {signal}")
        
        if search_strategies:
            body_parts.append("\n## Search Strategies")
            for strategy in search_strategies:
                body_parts.append(f"- {strategy}")
        
        body = "\n".join(body_parts)
        
        # Extract trusted domains for metadata
        trusted_domains = [src.get("domain") for src in trusted_sources if src.get("domain")]
        
        return self.save_memory(
            title=title,
            body_md=body,
            tags=["source_discovery", item_type, category],
            scope="long_term",
            ttl_days=ttl_days,
            importance="high",
            source="research.discover_sources",
            metadata={
                "item_type": item_type,
                "category": category,
                "trusted_domains": trusted_domains,
                "discovery_date": discovery_data.get("discovered_at"),
            }
        )

    def get_source_discovery(
        self,
        item_type: str,
        category: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached source discovery if available and fresh.
        
        Args:
            item_type: "live_animal", "electronics", etc.
            category: "pet:hamster", "computing:laptop", etc.
        
        Returns:
            Cached discovery data or None if not found/expired
        """
        results = self.query(
            query=f"source discovery {category}",
            k=1,
            scope="long_term",
            include_body=True
        )
        
        if not results:
            return None
        
        result = results[0]
        
        # Verify it's actually a source discovery for this category
        metadata = result.get("metadata", {})
        if metadata.get("item_type") != item_type or metadata.get("category") != category:
            return None
        
        # Check if still fresh (not expired)
        created_at = result.get("created_at")
        if created_at:
            try:
                created_dt = _parse_ts(created_at)
                days_old = (_now() - created_dt).total_seconds() / 86400.0
                if days_old > 30:  # Expired after 30 days
                    return None
            except ValueError:
                pass
        
        return result

    def query(
        self,
        query: str,
        *,
        k: int = 8,
        scope: str | None = None,
        min_score: float = 0.0,
        include_body: bool = True,
    ) -> List[Dict[str, Any]]:
        """Return the top-k matching memories ordered by a heuristic score."""

        q = (query or "").strip()
        if not q:
            return []

        self.prune_expired()

        scopes = self._resolve_scopes_for_query(scope)
        tokens = self._tokenize(q)
        if not tokens:
            tokens = set(_tokenize_text(q))

        results: List[Tuple[float, Dict[str, Any]]] = []
        match_tokens: Dict[str, List[str]] = {}

        if "long_term" in scopes:
            for record in self._iter_long_term_records():
                if "search_preference" in record.get("tags", []):
                    continue
                score, reasons = self._score_record(record, tokens, q)
                if score >= min_score:
                    match_tokens[record["id"]] = reasons
                    results.append((score, record))

        if "short_term" in scopes:
            for record in self._iter_short_term_records():
                score, reasons = self._score_record(record, tokens, q)
                if score >= min_score:
                    match_tokens[record["id"]] = reasons
                    results.append((score, record))

        results.sort(key=lambda tup: tup[0], reverse=True)

        out: List[Dict[str, Any]] = []
        for score, record in results[:k]:
            payload = {
                "memory_id": record.get("id"),
                "scope": record.get("scope"),
                "title": record.get("title"),
                "summary": record.get("summary"),
                "topic": record.get("topic"),
                "tags": record.get("tags", []),
                "keywords": record.get("keywords", []),
                "score": round(score, 4),
                "source": record.get("source"),
                "importance": record.get("importance"),
                "created_at": record.get("created_at"),
                "expires_at": record.get("expires_at"),
                "metadata": record.get("metadata", {}),
                "match_reasons": match_tokens.get(record.get("id"), []),
            }
            if include_body and record.get("body_md"):
                body = record.get("body_md", "")
                payload["body_md"] = body if len(body) <= 2000 else body[:2000] + "..."
            payload["excerpt"] = payload.get("summary") or (record.get("body_md", "")[:180] if record.get("body_md") else None)
            out.append(payload)

        if out:
            self._write_audit(
                {
                    "action": "memory.query",
                    "query": q,
                    "results": [
                        {
                            "id": item["memory_id"],
                            "scope": item["scope"],
                            "score": item["score"],
                        }
                        for item in out
                    ],
                }
            )

        return out

    def prune_expired(self) -> None:
        """Remove expired short-term records and rebuild the index if needed."""

        if not self.short_records_path.exists():
            return

        now = _now()
        changed = False
        records: List[Dict[str, Any]] = []
        with self.short_records_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    changed = True
                    continue
                expires_at = record.get("expires_at")
                if expires_at and _is_expired(expires_at, now):
                    try:
                        self._promote_short_record(record)
                    except Exception:
                        pass
                    changed = True
                    continue
                records.append(record)

        if changed:
            with self.short_records_path.open("w", encoding="utf-8") as f:
                for record in records:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._refresh_short_index(records)

    # ------------------------------------------------------------------
    # Internal helpers

    def _resolve_scope(
        self,
        scope: Optional[str],
        ttl_days: Optional[int],
        tags: List[str],
        body_md: str,
        importance: str,
    ) -> str:
        if scope:
            scl = scope.lower()
            if "short" in scl:
                return "short_term"
            if "long" in scl:
                return "long_term"

        # Auto inference heuristics
        tags_lower = {t.lower() for t in tags}
        if any(t in tags_lower for t in {"session", "ephemeral", "scratch"}):
            return "short_term"
        if ttl_days is not None and ttl_days <= 3:
            return "short_term"
        if importance.lower() in {"high", "critical", "long_term"}:
            return "long_term"
        if len(body_md) >= 160:
            return "long_term"
        if any(t in tags_lower for t in {"knowledge", "topic", "faq", "long_term"}):
            return "long_term"
        # Default bias: store durable knowledge
        return "long_term"

    def _promote_short_record(self, record: Dict[str, Any]) -> Optional[str]:
        short_id = record.get("id")
        if short_id and short_id in self._promoted_cache:
            return None
        meta = record.get("metadata") or {}
        if meta.get("promoted_to"):
            self._promoted_cache.add(short_id or meta.get("promoted_to"))
            return meta.get("promoted_to")
        if short_id and self._has_promoted_from(short_id):
            return None

        title = record.get("title") or "Conversation memory"
        tags = list(record.get("tags") or [])
        # remove short-term/session markers, add long-term flag
        tags = [t for t in tags if t not in {"session", "short_term"}]
        if "conversation" not in tags:
            tags.append("conversation")
        if "long_term" not in tags:
            tags.append("long_term")

        topic = meta.get("topic") or record.get("topic")
        body = record.get("body_md") or record.get("summary") or ""
        if not body:
            body = f"Summary: {record.get('summary', '')}"

        new_metadata = dict(meta)
        if short_id:
            new_metadata["promoted_from"] = short_id
        new_metadata["scope"] = "long_term"
        new_metadata.pop("ttl_days", None)
        new_metadata.pop("expires_at", None)

        long_record = memory_schema.make_memory_record(
            title,
            tags,
            body,
            source=record.get("source") or meta.get("source") or "agent",
            ttl_days=None,
            topic=topic,
            keywords=record.get("keywords"),
            importance=record.get("importance", "normal"),
            metadata=new_metadata,
            source_turn_ids=record.get("source_turn_ids"),
            session_id=record.get("session_id"),
        )
        long_record["scope"] = "long_term"
        path = memory_schema.write_memory_record(long_record, out_dir=str(self.long_json_dir))
        memory_schema.update_index(long_record, index_path=str(self.long_index_path))

        self._write_audit(
            {
                "action": "memory.promote",
                "id": long_record.get("id"),
                "from_id": short_id,
                "title": long_record.get("title"),
                "path": str(path),
            }
        )
        if short_id:
            self._promoted_cache.add(short_id)
        return long_record.get("id")

    def _has_promoted_from(self, short_id: str) -> bool:
        if not short_id:
            return False
        if short_id in self._promoted_cache:
            return True
        for path in self.long_json_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            meta = data.get("metadata") or {}
            if meta.get("promoted_from") == short_id:
                self._promoted_cache.add(short_id)
                return True
        return False

    def _resolve_scopes_for_query(self, scope: Optional[str]) -> List[str]:
        if not scope or scope.lower() == "auto":
            return ["short_term", "long_term"]
        scl = scope.lower()
        scopes: List[str] = []
        if "short" in scl:
            scopes.append("short_term")
        if "long" in scl:
            scopes.append("long_term")
        if not scopes:
            scopes = ["short_term", "long_term"]
        return scopes

    def _append_short_record(self, record: Dict[str, Any]) -> None:
        with self.short_records_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _refresh_short_index(self, records: Optional[List[Dict[str, Any]]] = None) -> None:
        if records is None:
            records = list(self._iter_short_term_records(raw=True))
        index = {"items": []}
        for rec in records:
            index["items"].append(
                {
                    "id": rec.get("id"),
                    "title": rec.get("title"),
                    "summary": rec.get("summary"),
                    "topic": rec.get("topic"),
                    "created_at": rec.get("created_at"),
                    "expires_at": rec.get("expires_at"),
                }
            )
        self.short_index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")

    def _iter_short_term_records(self, raw: bool = False) -> Iterable[Dict[str, Any]]:
        if not self.short_records_path.exists():
            return []
        records: List[Dict[str, Any]] = []
        with self.short_records_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not raw:
                    record = self._normalize_record(record)
                records.append(record)
        return records

    def _iter_long_term_records(self) -> Iterable[Dict[str, Any]]:
        if not self.long_json_dir.exists():
            return []
        records: List[Dict[str, Any]] = []
        for path in sorted(self.long_json_dir.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            record["scope"] = "long_term"
            records.append(self._normalize_record(record))
        return records

    def _normalize_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        record.setdefault("tags", [])
        record.setdefault("keywords", [])
        record.setdefault("importance", "normal")
        record.setdefault("metadata", {})
        record.setdefault("summary", memory_schema.extract_summary(record.get("body_md", "")))
        record.setdefault("topic", self._infer_topic(record.get("tags", []), record.get("summary", ""), record.get("keywords", [])))
        return record

    def _score_record(self, record: Dict[str, Any], tokens: set[str], query_text: str) -> Tuple[float, List[str]]:
        reasons: List[str] = []
        score = 0.0

        def _score_field(field_tokens: Iterable[str], weight: float, label: str) -> None:
            nonlocal score
            overlap = tokens.intersection(field_tokens)
            if overlap:
                score += weight * len(overlap)
                reasons.append(f"{label}: {', '.join(sorted(overlap))}")

        _score_field(_tokenize_text(record.get("topic", "")), 4.0, "topic")
        _score_field(_tokenize_text(record.get("title", "")), 3.0, "title")
        _score_field(_tokenize_text(" ".join(record.get("tags", []))), 2.0, "tags")
        _score_field(_tokenize_text(record.get("summary", "")), 2.5, "summary")
        _score_field(_tokenize_text(" ".join(record.get("keywords", []))), 2.0, "keywords")
        _score_field(_tokenize_text(record.get("body_md", "")), 0.5, "body")

        qlower = query_text.lower()
        if record.get("summary") and qlower in record["summary"].lower():
            score += 1.5
            reasons.append("summary contains query phrase")
        if record.get("topic") and qlower in record["topic"].lower():
            score += 1.0
            reasons.append("topic contains query phrase")

        recency_boost = self._recency_boost(record)
        if recency_boost:
            score += recency_boost
            reasons.append(f"recency+{recency_boost:.2f}")

        return score, reasons

    def _recency_boost(self, record: Dict[str, Any]) -> float:
        created_at = record.get("created_at")
        if not created_at:
            return 0.0
        try:
            created_dt = _parse_ts(created_at)
        except ValueError:
            return 0.0
        days_old = (_now() - created_dt).total_seconds() / 86400.0
        if record.get("scope") == "short_term":
            return max(0.0, 2.0 - days_old) * 0.5
        return max(0.0, 7.0 - days_old) * 0.1

    def _extract_keywords(self, text: str, max_keywords: int = 10) -> List[str]:
        tokens = _tokenize_text(text)
        counter = Counter(tokens)
        most_common = [word for word, _ in counter.most_common(max_keywords * 2)]
        keywords: List[str] = []
        for word in most_common:
            if word in STOPWORDS:
                continue
            if any(word in existing for existing in keywords):
                continue
            keywords.append(word)
            if len(keywords) >= max_keywords:
                break
        return keywords

    def _infer_topic(self, tags: Sequence[str], summary: str, keywords: Sequence[str]) -> str:
        for tag in tags:
            tl = tag.lower()
            if tl.startswith("topic:"):
                return tag.split(":", 1)[1].strip() or tag
            if tl in {"faq", "knowledge"} and summary:
                return summary.split(" ")[0]
        if keywords:
            return keywords[0]
        if summary:
            return summary.split(" ")[0]
        return "note"

    def _tokenize(self, text: str) -> set[str]:
        return set(_tokenize_text(text))

    def _write_audit(self, entry: Dict[str, Any]) -> None:
        entry = dict(entry or {})
        entry["ts"] = _now().isoformat()
        try:
            with self.audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass


def _tokenize_text(text: str) -> List[str]:
    return [tok for tok in re.findall(r"[a-z0-9]+", text.lower()) if tok not in STOPWORDS]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _is_expired(expires_at: str, now: Optional[datetime] = None) -> bool:
    now = now or _now()
    try:
        exp = _parse_ts(expires_at)
    except ValueError:
        return False
    return exp <= now


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _sanitize_user_id(user_id: str | None) -> str | None:
    if not user_id:
        return None
    lowered = user_id.lower().strip()
    cleaned = re.sub(r"[^a-z0-9_-]", "_", lowered)
    cleaned = cleaned.strip("_")
    return cleaned or "default"


def _hash_project_path(project_path: str) -> str:
    """Generate a short hash from absolute project path for directory naming."""
    import hashlib
    normalized = os.path.abspath(project_path)
    hash_obj = hashlib.sha256(normalized.encode("utf-8"))
    return hash_obj.hexdigest()[:12]


def _base_dir_for_user(user_id: str | None, project_path: str | None = None) -> str:
    """
    Get base directory for memory storage.
    - If project_path provided: users/{user}/projects/{hash}/
    - Otherwise: users/{user}/ (global)
    """
    base = Path(os.getenv("MEMORY_ROOT") or os.getenv("MEM_DIR") or "panda_system_docs/memory").resolve()
    sanitized = _sanitize_user_id(user_id)
    if sanitized:
        base = base / "users" / sanitized
    
    if project_path:
        project_hash = _hash_project_path(project_path)
        base = base / "projects" / project_hash
    
    return os.fspath(base)


@lru_cache(maxsize=None)
def _get_cached_store(base_dir: str) -> MemoryStore:
    return MemoryStore(base_dir)


def get_memory_store(user_id: str | None = None, project_path: str | None = None) -> MemoryStore:
    """
    Get memory store with optional project isolation.
    
    Args:
        user_id: User identifier (sanitized for directory naming)
        project_path: Absolute path to project for isolated memory (optional)
    
    Returns:
        MemoryStore instance for specified scope
    """
    base = _base_dir_for_user(user_id, project_path)
    return _get_cached_store(os.path.abspath(base))


def reset_memory_store_cache() -> None:
    _get_cached_store.cache_clear()


def get_project_metadata(user_id: str, project_path: str) -> Optional[Dict[str, Any]]:
    """
    Load project metadata from .project_meta.json
    
    Returns:
        Project metadata dict or None if not found
    """
    base = Path(_base_dir_for_user(user_id, project_path))
    meta_path = base / ".project_meta.json"
    
    if not meta_path.exists():
        return None
    
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_project_metadata(user_id: str, project_path: str, metadata: Dict[str, Any]) -> None:
    """Save project metadata to .project_meta.json"""
    base = Path(_base_dir_for_user(user_id, project_path))
    base.mkdir(parents=True, exist_ok=True)
    meta_path = base / ".project_meta.json"
    
    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")


def initialize_project_memory_bank(
    user_id: str,
    project_path: str,
    scan_repo: bool = True
) -> Dict[str, Any]:
    """
    Initialize memory-bank structure for a project.
    
    Creates 6 core files:
    - projectbrief.md
    - activeContext.md
    - systemPatterns.md
    - techContext.md
    - productContext.md
    - progress.md
    
    Args:
        user_id: User identifier
        project_path: Absolute path to project repository
        scan_repo: Whether to scan repo for initial content
    
    Returns:
        Dict with status and created file paths
    """
    project_path_abs = os.path.abspath(project_path)
    project_name = os.path.basename(project_path_abs)
    
    # Get or create memory store for this project
    store = get_memory_store(user_id, project_path_abs)
    base_dir = Path(store.base_dir)
    
    # Create memory-bank directory
    memory_bank_dir = base_dir / "memory-bank"
    memory_bank_dir.mkdir(parents=True, exist_ok=True)
    
    # Save project metadata
    now_iso = _now().isoformat()
    project_meta = {
        "path": project_path_abs,
        "name": project_name,
        "initialized": now_iso,
        "user_id": user_id,
    }
    
    # Scan repository if requested
    repo_info = {}
    if scan_repo and os.path.isdir(project_path_abs):
        repo_info = _scan_repository(project_path_abs)
        project_meta["scanned"] = True
        project_meta["scan_timestamp"] = now_iso
    
    save_project_metadata(user_id, project_path_abs, project_meta)
    
    # Initialize 6 core memory-bank files
    files_created = []
    
    # 1. projectbrief.md
    goals_default = '- Goal 1: To be defined\n- Goal 2: To be defined'
    projectbrief = f"""# Project Brief: {project_name}

Initialized: {now_iso}

## Overview
{repo_info.get('overview', 'Project overview to be documented.')}

## Goals
{repo_info.get('goals', goals_default)}

## Scope
{repo_info.get('scope', 'Project scope to be documented.')}

## Constraints
- Budget: To be defined
- Timeline: To be defined
- Resources: To be defined
"""
    (memory_bank_dir / "projectbrief.md").write_text(projectbrief, encoding="utf-8")
    files_created.append("projectbrief.md")
    
    # 2. activeContext.md
    activeContext = f"""# Active Context

Updated: {now_iso}

## Now
- Memory-bank initialized for {project_name}
- Ready to start tracking project work

## Next
- Begin documenting current objectives
- Capture key patterns as they emerge

## Risks
- None identified yet

## Questions
- None pending
"""
    (memory_bank_dir / "activeContext.md").write_text(activeContext, encoding="utf-8")
    files_created.append("activeContext.md")
    
    # 3. systemPatterns.md
    patterns_default = '## Patterns\n\nTo be documented as patterns emerge during development.'
    systemPatterns = f"""# System Patterns

Initialized: {now_iso}

{repo_info.get('patterns', patterns_default)}
"""
    (memory_bank_dir / "systemPatterns.md").write_text(systemPatterns, encoding="utf-8")
    files_created.append("systemPatterns.md")
    
    # 4. techContext.md
    tech_stack_default = '## Technology Stack\n\nTo be documented.'
    dependencies_default = '## Dependencies\n\nTo be documented.'
    techContext = f"""# Technical Context

Initialized: {now_iso}

{repo_info.get('tech_stack', tech_stack_default)}

{repo_info.get('dependencies', dependencies_default)}
"""
    (memory_bank_dir / "techContext.md").write_text(techContext, encoding="utf-8")
    files_created.append("techContext.md")
    
    # 5. productContext.md
    product_info_default = '## Product Information\n\nTo be documented.'
    productContext = f"""# Product Context

Initialized: {now_iso}

{repo_info.get('product_info', product_info_default)}
"""
    (memory_bank_dir / "productContext.md").write_text(productContext, encoding="utf-8")
    files_created.append("productContext.md")
    
    # 6. progress.md
    progress = f"""# Progress Log

## {now_iso}
Summary: Memory-bank initialized for {project_name}

- Change: Created 6 core memory-bank files
- Decision: Using centralized memory storage at {base_dir}
- Next: Begin documenting project work and patterns
"""
    (memory_bank_dir / "progress.md").write_text(progress, encoding="utf-8")
    files_created.append("progress.md")
    
    return {
        "status": "ok",
        "project_path": project_path_abs,
        "project_name": project_name,
        "memory_bank_dir": str(memory_bank_dir),
        "files_created": files_created,
        "scanned": scan_repo,
        "repo_info": repo_info if scan_repo else {},
    }


def _scan_repository(project_path: str) -> Dict[str, Any]:
    """
    Scan repository for initial content to populate memory-bank files.
    
    Looks for:
    - README.md for overview/goals
    - requirements.txt, package.json, environment.yml for dependencies
    - Directory structure for patterns
    """
    info = {}
    project_path = Path(project_path)
    
    # Read README
    readme_paths = ["README.md", "README.txt", "README", "readme.md"]
    for readme_name in readme_paths:
        readme_path = project_path / readme_name
        if readme_path.exists():
            try:
                readme_content = readme_path.read_text(encoding="utf-8", errors="ignore")
                # Extract first few paragraphs as overview
                lines = [l.strip() for l in readme_content.split("\n") if l.strip()]
                overview_lines = []
                for line in lines[:10]:
                    if line.startswith("#"):
                        continue
                    overview_lines.append(line)
                    if len(overview_lines) >= 3:
                        break
                info["overview"] = "\n".join(overview_lines) if overview_lines else "See README.md"
                break
            except Exception:
                pass
    
    # Detect tech stack
    tech_parts = []
    
    if (project_path / "requirements.txt").exists():
        tech_parts.append("- Python project (requirements.txt found)")
    if (project_path / "environment.yml").exists():
        tech_parts.append("- Conda environment (environment.yml found)")
    if (project_path / "package.json").exists():
        tech_parts.append("- Node.js project (package.json found)")
    if (project_path / "Cargo.toml").exists():
        tech_parts.append("- Rust project (Cargo.toml found)")
    if (project_path / "go.mod").exists():
        tech_parts.append("- Go project (go.mod found)")
    
    if tech_parts:
        info["tech_stack"] = "## Technology Stack\n\n" + "\n".join(tech_parts)
    
    # Directory structure patterns
    pattern_parts = []
    
    if (project_path / "tests").is_dir() or (project_path / "test").is_dir():
        pattern_parts.append("- Tests located in `tests/` or `test/` directory")
    if (project_path / "docs").is_dir():
        pattern_parts.append("- Documentation in `docs/` directory")
    if (project_path / "src").is_dir():
        pattern_parts.append("- Source code in `src/` directory")
    if (project_path / ".git").is_dir():
        pattern_parts.append("- Git repository (version controlled)")
    
    if pattern_parts:
        info["patterns"] = "## Observed Patterns\n\n" + "\n".join(pattern_parts)
    
    return info


def load_project_memory_bank(user_id: str, project_path: str) -> Dict[str, str]:
    """
    Load all memory-bank files for a project.
    
    Returns:
        Dict mapping filename to content
    """
    base = Path(_base_dir_for_user(user_id, project_path))
    memory_bank_dir = base / "memory-bank"
    
    if not memory_bank_dir.exists():
        return {}
    
    files = {}
    for filename in ["projectbrief.md", "activeContext.md", "systemPatterns.md", 
                     "techContext.md", "productContext.md", "progress.md"]:
        file_path = memory_bank_dir / filename
        if file_path.exists():
            try:
                files[filename] = file_path.read_text(encoding="utf-8")
            except Exception:
                files[filename] = f"# {filename}\n\n(Error reading file)"
    
    return files


def list_user_projects(user_id: str) -> List[Dict[str, Any]]:
    """
    List all projects with initialized memory-banks for a user.
    
    Returns:
        List of project metadata dicts
    """
    base = Path(_base_dir_for_user(user_id))
    projects_dir = base / "projects"
    
    if not projects_dir.exists():
        return []
    
    projects = []
    for project_hash_dir in projects_dir.iterdir():
        if not project_hash_dir.is_dir():
            continue
        
        meta_path = project_hash_dir / ".project_meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                meta["hash"] = project_hash_dir.name
                projects.append(meta)
            except Exception:
                pass
    
    return sorted(projects, key=lambda p: p.get("initialized", ""), reverse=True)
