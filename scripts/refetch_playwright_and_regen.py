#!/usr/bin/env python3
"""
scripts/refetch_playwright_and_regen.py

Re-fetch staged pages that appear blocked or had extractive NoteFrame fallbacks using Playwright,
then re-run the NoteFrame generator to produce improved NoteFrames.

Usage:
  set -a && source .env && PYTHONPATH=/path/to/pandaagi python scripts/refetch_playwright_and_regen.py

Behavior:
- Scans panda_system_docs/scrape_staging/* for staged pages.
- Selects candidates where:
  - noteframe.json is missing OR
  - noteframe.json contains "__fallback": true OR
  - meta.json contains an "error" field OR
  - content.md is very small (< 500 bytes)
- For each candidate, reads meta.json to get the original URL and re-fetches it using orchestrator.web_fetcher.fetch_and_stage with fetch_mode="playwright".
- Keeps original staged folders (for audit) and creates new staged folders for Playwright results.
- Runs scripts/generate_noteframes.py to regenerate NoteFrames (uses whatever THINK_URL/THINK_MODEL_ID are configured).
- Prints a summary of re-fetched staged paths and generation results.
"""
from __future__ import annotations
import os
import json
import subprocess
import traceback
from pathlib import Path
from typing import List, Dict, Any

STAGING_ROOT = Path("panda_system_docs/scrape_staging")
GENERATE_SCRIPT = Path("scripts/generate_noteframes.py")
MIN_CONTENT_BYTES = 500  # treat very small content as candidate for re-fetch

def is_candidate(staged_dir: Path) -> bool:
    try:
        nf = staged_dir / "noteframe.json"
        meta = staged_dir / "meta.json"
        content = staged_dir / "content.md"
        if not nf.exists():
            return True
        try:
            nfd = json.loads(nf.read_text(encoding="utf-8"))
            if nfd.get("__fallback", False):
                return True
        except Exception:
            return True
        if meta.exists():
            try:
                m = json.loads(meta.read_text(encoding="utf-8"))
                if "error" in m:
                    return True
            except Exception:
                return True
        if content.exists():
            try:
                if content.stat().st_size < MIN_CONTENT_BYTES:
                    return True
            except Exception:
                return True
        return False
    except Exception:
        return True

def get_url_for_staged(staged_dir: Path) -> str:
    meta = staged_dir / "meta.json"
    if meta.exists():
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
            url = m.get("url") or m.get("source_url") or ""
            return url
        except Exception:
            return ""
    return ""

def refetch_url_with_playwright(url: str, staged_root: str = str(STAGING_ROOT)) -> Dict[str, Any]:
    try:
        from apps.services.tool_server import web_fetcher  # type: ignore
    except Exception as e:
        raise RuntimeError(f"orchestrator.web_fetcher not available: {e}") from e
    # Use fetch_mode "playwright" to render JS and avoid simple GET blocks
    return web_fetcher.fetch_and_stage(url, staged_root=staged_root, fetch_mode="playwright")

def main():
    if not STAGING_ROOT.exists():
        print(f"No staging root at {STAGING_ROOT}; nothing to do.")
        return

    staged_dirs = sorted([d for d in STAGING_ROOT.iterdir() if d.is_dir()])
    candidates = []
    for d in staged_dirs:
        if is_candidate(d):
            candidates.append(d)

    if not candidates:
        print("No candidates found for Playwright re-fetch.")
        return

    print(f"Found {len(candidates)} candidates for Playwright re-fetch:")
    for c in candidates:
        print(f" - {c}")

    re_staged_paths = []
    for c in candidates:
        try:
            url = get_url_for_staged(c)
            if not url:
                print(f"Skipping {c} - no URL found in meta.json")
                continue
            print(f"Re-fetching with Playwright: {url}")
            item = refetch_url_with_playwright(url, staged_root=str(STAGING_ROOT))
            staged_path = item.get("staged_path")
            if staged_path:
                print(f"  -> new staged path: {staged_path}")
                re_staged_paths.append(staged_path)
            else:
                print(f"  -> fetch_and_stage returned no staged_path, item: {item}")
        except Exception as e:
            print(f"Error re-fetching {c}: {e}")
            traceback.print_exc()

    if not re_staged_paths:
        print("No new staged paths created; skipping NoteFrame regeneration.")
        return

    # Re-run NoteFrame generation script to regenerate NoteFrames (will process all staged pages)
    try:
        print("Re-running NoteFrame generation script...")
        # Use shell to source .env so THINK_URL/THINK_MODEL_ID are available in environment
        cmd = 'set -a && source .env && PYTHONPATH=/path/to/pandaagi python scripts/generate_noteframes.py'
        subprocess.run(cmd, shell=True, check=True, executable="/bin/bash")
        print("NoteFrame generation completed.")
    except subprocess.CalledProcessError as e:
        print(f"NoteFrame generation script failed: {e}")
        return

    print("\nRe-fetch summary:")
    for p in re_staged_paths:
        print(f" - {p}")

if __name__ == "__main__":
    main()
