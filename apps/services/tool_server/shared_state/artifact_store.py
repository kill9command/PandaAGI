"""
Content-addressed artifact storage used by the shared-state backbone.

Artifacts may contain large tool outputs (tables, JSON responses, HTML) that
should not be injected directly into model prompts. Instead, we store them
under a deterministic `blob://<sha256>` identifier and hand references to the
Context Manager / Guide.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ArtifactRecord:
    blob_id: str
    path: Path
    kind: str
    size: int
    sha256: str
    metadata: Dict[str, Any]


class ArtifactStore:
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.blob_dir = self.base_dir / "blobs"
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.base_dir / "index.jsonl"
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Public helpers

    def store_bytes(
        self,
        data: bytes,
        *,
        kind: str = "binary",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactRecord:
        """Store raw bytes, returning an ArtifactRecord."""
        sha = hashlib.sha256(data).hexdigest()
        blob_id = f"blob://{sha}"
        path = self._path_for_hash(sha)
        size = len(data)

        with self._lock:
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            self._append_index(
                {
                    "blob_id": blob_id,
                    "kind": kind,
                    "size": size,
                    "sha256": sha,
                    "metadata": metadata or {},
                    "path": str(path),
                }
            )
        return ArtifactRecord(blob_id, path, kind, size, sha, metadata or {})

    def store_text(
        self,
        text: str,
        *,
        kind: str = "text",
        metadata: Optional[Dict[str, Any]] = None,
        encoding: str = "utf-8",
        preview_len: int = 600,
    ) -> ArtifactRecord:
        data = text.encode(encoding)
        meta = dict(metadata or {})
        meta.setdefault("encoding", encoding)
        if len(text) > preview_len:
            meta["preview"] = text[:preview_len] + "..."
        return self.store_bytes(data, kind=kind, metadata=meta)

    def store_json(
        self,
        payload: Dict[str, Any] | Any,
        *,
        kind: str = "json",
        metadata: Optional[Dict[str, Any]] = None,
        ensure_ascii: bool = False,
        preview_len: int = 600,
    ) -> ArtifactRecord:
        text_payload = json.dumps(payload, ensure_ascii=ensure_ascii, separators=(",", ":"))
        data = text_payload.encode("utf-8")
        meta = dict(metadata or {})
        meta.setdefault("content_type", "application/json")
        if len(text_payload) > preview_len:
            meta["preview"] = text_payload[:preview_len] + "..."
        return self.store_bytes(data, kind=kind, metadata=meta)

    def resolve_path(self, blob_id: str) -> Path:
        """Return the on-disk path for a `blob://` identifier."""
        sha = self._hash_from_blob(blob_id)
        path = self._path_for_hash(sha)
        if not path.exists():
            raise FileNotFoundError(f"artifact missing: {blob_id}")
        return path

    def read_bytes(self, blob_id: str) -> bytes:
        return self.resolve_path(blob_id).read_bytes()

    def read_text(self, blob_id: str, encoding: str = "utf-8") -> str:
        return self.resolve_path(blob_id).read_text(encoding=encoding)

    # ------------------------------------------------------------------ #
    # Internal

    def _path_for_hash(self, sha_hex: str) -> Path:
        prefix = sha_hex[:2]
        return self.blob_dir / prefix / sha_hex

    @staticmethod
    def _hash_from_blob(blob_id: str) -> str:
        if not blob_id.startswith("blob://"):
            raise ValueError(f"invalid blob id: {blob_id}")
        return blob_id.split("blob://", 1)[1]

    def _append_index(self, record: Dict[str, Any]) -> None:
        # Append-only JSONL; tolerate failures silently (best-effort audit trail)
        try:
            with self.index_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            # Logless fallback – in worst cases the blob still exists on disk.
            pass

