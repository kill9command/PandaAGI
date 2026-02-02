#!/usr/bin/env python3
"""
scripts/memory_schema.py

Utility to convert a Markdown file (or a plain text string) into a minimal memory JSON
record suitable for `panda_system_docs/memory/json/<id>.json` and to update the index.

Usage (CLI):
  python scripts/memory_schema.py --input path/to/file.md --title "Short title" --tags tag1,tag2
  python scripts/memory_schema.py --stdin --title "From stdin" --tags a,b

Behavior:
- Reads input text (file or stdin)
- Generates a uuid4 id and ISO8601 created_at
- Produces a short summary (first paragraph or first 200 chars)
- Estimates tokens via chars/4 heuristic
- Writes JSON to panda_system_docs/memory/json/<id>.json
- Updates panda_system_docs/memory/index.json (mapping tags -> list of metadata entries)
"""
from __future__ import annotations
import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional


CHAR_PER_TOKEN = 4


def token_estimate(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + CHAR_PER_TOKEN - 1) // CHAR_PER_TOKEN)


def extract_summary(body_md: str, max_chars: int = 200) -> str:
    # Prefer first paragraph (split on double newline); fallback to truncation
    parts = [p.strip() for p in body_md.split("\n\n") if p.strip()]
    if parts:
        first = parts[0]
        return first if len(first) <= max_chars else first[: max_chars - 3].rstrip() + "..."
    # fallback
    txt = body_md.strip().replace("\n", " ")
    return txt[: max_chars - 3].rstrip() + "..." if len(txt) > max_chars else txt


def make_memory_record(
    title: str,
    tags: List[str],
    body_md: str,
    source: str = "imported",
    ttl_days: Optional[int] = None,
    *,
    topic: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    importance: str = "normal",
    metadata: Optional[Dict[str, Any]] = None,
    source_turn_ids: Optional[List[str]] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    mid = uuid.uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    summary = extract_summary(body_md)
    token_est = token_estimate(body_md)
    record = {
        "id": mid,
        "title": title,
        "created_at": created_at,
        "tags": tags,
        "summary": summary,
        "facts": [],  # caller may populate facts if available
        "body_md": body_md,
        "source": source,
        "token_est": token_est,
        "ttl_days": ttl_days,
    }
    if topic:
        record["topic"] = topic
    if keywords:
        record["keywords"] = keywords
    if importance:
        record["importance"] = importance
    if metadata:
        record["metadata"] = metadata
    if source_turn_ids:
        record["source_turn_ids"] = source_turn_ids
    if session_id:
        record["session_id"] = session_id
    return record


def write_memory_record(record: Dict[str, Any], out_dir: str = "panda_system_docs/memory/long_term/json") -> Path:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    file_path = out_path / f"{record['id']}.json"
    file_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return file_path


def load_index(index_path: Path) -> Dict[str, Any]:
    if not index_path.exists():
        return {"tags": {}}
    try:
        return json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return {"tags": {}}


def update_index(record: Dict[str, Any], index_path: str = "panda_system_docs/memory/long_term/index.json") -> None:
    ip = Path(index_path)
    ip.parent.mkdir(parents=True, exist_ok=True)
    idx = load_index(ip)
    tags = record.get("tags") or []
    entry_meta = {
        "id": record["id"],
        "title": record.get("title"),
        "created_at": record.get("created_at"),
        "summary": record.get("summary"),
        "token_est": record.get("token_est"),
        "source": record.get("source"),
    }
    for t in tags:
        if t not in idx["tags"]:
            idx["tags"][t] = []
        idx["tags"][t].append(entry_meta)
    # also add a global listing
    if "all" not in idx["tags"]:
        idx["tags"]["all"] = []
    idx["tags"]["all"].append(entry_meta)
    ip.write_text(json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8")


def convert_file_to_memory(path: Path, title: Optional[str], tags: List[str], source: str = "imported") -> Path:
    txt = path.read_text(encoding="utf-8", errors="replace")
    used_title = title or path.stem
    record = make_memory_record(used_title, tags, txt, source=source)
    written = write_memory_record(record)
    update_index(record)
    return written


def convert_stdin_to_memory(title: str, tags: List[str], source: str = "imported") -> Path:
    import sys

    txt = sys.stdin.read()
    record = make_memory_record(title, tags, txt, source=source)
    written = write_memory_record(record)
    update_index(record)
    return written


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Convert markdown/plain text to memory JSON record and update index.")
    p.add_argument("--input", type=str, help="Path to a markdown or text file to convert.")
    p.add_argument("--title", type=str, help="Short title for the memory record.", default=None)
    p.add_argument("--tags", type=str, help="Comma-separated tags", default="")
    p.add_argument("--source", type=str, help="Source string (agent|imported|manual)", default="imported")
    p.add_argument("--ttl-days", type=int, help="Optional TTL days", default=None)
    p.add_argument("--stdin", action="store_true", help="Read content from stdin instead of a file.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    if args.stdin:
        if not args.title:
            raise SystemExit("When using --stdin you must provide --title")
        out = convert_stdin_to_memory(args.title, tags, source=args.source)
        print(str(out))
        return
    if not args.input:
        raise SystemExit("Either --input or --stdin is required.")
    path = Path(args.input)
    if not path.exists():
        raise SystemExit(f"Input file not found: {path}")
    out = convert_file_to_memory(path, args.title, tags, source=args.source)
    print(str(out))


if __name__ == "__main__":
    main()
