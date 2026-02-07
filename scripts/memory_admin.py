#!/usr/bin/env python3
"""Memory inspection CLI for chatbot short- and long-term entries.

Usage examples:
  python scripts/memory_admin.py list --scope short_term --limit 5
  python scripts/memory_admin.py list --scope auto --json
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from apps.services.tool_server.memory_store import get_memory_store, reset_memory_store_cache


def _format_ts(value: str | None) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.isoformat()
    except ValueError:
        return value


def _list_records(scope: str, limit: int, include_body: bool, user_id: str | None) -> list[dict]:
    store = get_memory_store(user_id)
    records: list[dict] = []
    if scope in {"short_term", "auto"}:
        for rec in store._iter_short_term_records():  # pylint: disable=protected-access
            records.append({**rec, "scope": "short_term"})
    if scope in {"long_term", "auto"}:
        for rec in store._iter_long_term_records():  # pylint: disable=protected-access
            records.append({**rec, "scope": "long_term"})
    records.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    sliced = records[:limit]
    if not include_body:
        for rec in sliced:
            rec.pop("body_md", None)
    return sliced


def cmd_list(args: argparse.Namespace) -> int:
    scope = args.scope
    limit = args.limit
    include_body = args.include_body
    user_id = args.user

    if args.reset_cache:
        reset_memory_store_cache()

    data = _list_records(scope, limit, include_body, user_id)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    if not data:
        print("(no records)")
        return 0

    for rec in data:
        print(f"[{rec.get('scope','?')}] {rec.get('id','')} :: {rec.get('title','(untitled)')}")
        print(f"  topic={rec.get('topic','-')} importance={rec.get('importance','-')} tags={','.join(rec.get('tags') or [])}")
        print(f"  created={_format_ts(rec.get('created_at'))} expires={_format_ts(rec.get('expires_at'))}")
        summary = rec.get("summary") or ""
        print(f"  summary={summary}")
        if include_body and rec.get("body_md"):
            body_preview = rec["body_md"]
            if len(body_preview) > 240:
                body_preview = body_preview[:237] + "..."
            print(f"  body={body_preview}")
        metadata = rec.get("metadata") or {}
        if metadata:
            promoted = metadata.get("promoted_from")
            note = f"  metadata={metadata}"
            if promoted:
                note += " (promoted)"
            print(note)
        print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect chatbot memories.")
    sub = parser.add_subparsers(dest="command")

    list_parser = sub.add_parser("list", help="List memory entries")
    list_parser.add_argument("--scope", choices=["auto", "short_term", "long_term"], default="auto")
    list_parser.add_argument("--limit", type=int, default=10)
    list_parser.add_argument("--json", action="store_true")
    list_parser.add_argument("--include-body", action="store_true")
    list_parser.add_argument("--user", default="default", help="Memory user/profile id (e.g. default, user2, shared)")
    list_parser.add_argument("--reset-cache", action="store_true", help="Clear MemoryStore cache before listing")
    list_parser.set_defaults(func=cmd_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
