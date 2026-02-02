#!/usr/bin/env python3
"""
scripts/run_full_hamster_trace.py

Clears staging, runs live discovery (SerpAPI) + fetch+stage, generates NoteFrames,
and asks the Solver model to synthesize a final answer for the user question:
  "What's the best hamster to buy for a first-time owner, where to buy it, and what are typical prices?"

Usage:
  set -a && source .env && PYTHONPATH=/home/henry/pythonprojects/pandaai conda run -n pandaai python scripts/run_full_hamster_trace.py

This script is destructive: it clears panda_system_docs/scrape_staging/* before running.
"""
from __future__ import annotations
import os
import json
import shutil
import subprocess
import traceback
import time
from pathlib import Path
from typing import List

STAGING_ROOT = Path("panda_system_docs/scrape_staging")

# Queries we will run for this example
SEARCH_QUERIES = [
    "best hamster for a first-time owner 2025 price USA",
    "where to buy hamster near me",
    "hamster price range shelter petstore breeder 2025"
]


def clear_staging() -> None:
    STAGING_ROOT.mkdir(parents=True, exist_ok=True)
    for p in STAGING_ROOT.iterdir():
        if p.is_dir():
            shutil.rmtree(p)


def run_discovery_and_stage(queries: List[str]) -> None:
    """
    Use context_builder.perform_search_request to run discovery via SerpAPI and stage results.
    """
    print("Running discovery + staging via orchestrator.context_builder.perform_search_request...")
    try:
        from apps.services.orchestrator import context_builder
    except Exception as e:
        print("Failed to import apps.services.orchestrator.context_builder:", e)
        traceback.print_exc()
        raise

    search_request = {
        "queries": queries,
        "fetch_mode": "search_api",
        "k_per_query": 3,
        "follow_links": False,
        "follow_links_depth": 0,
        "max_links_per_page": 0,
    }

    results = context_builder.perform_search_request(search_request, staged_root=str(STAGING_ROOT))
    print("Discovery/staging finished. Items returned:", len(results))


def generate_noteframes() -> None:
    """
    Run the noteframe generation script which will call the Thinking model and write noteframe.json files.
    """
    print("Running NoteFrame generation (scripts/generate_noteframes.py)...")
    # We run it in the same environment; assume .env has been sourced by caller
    subprocess.run(["python", "scripts/generate_noteframes.py"], check=True)
    print("NoteFrame generation completed.")


def collect_noteframe_facts(limit_per_noteframe: int = 3, max_noteframes: int = 12) -> List[str]:
    facts = []
    staged_dirs = sorted([d for d in STAGING_ROOT.iterdir() if d.is_dir()])
    for d in staged_dirs[:max_noteframes]:
        nf = d / "noteframe.json"
        if not nf.exists():
            continue
        try:
            j = json.loads(nf.read_text(encoding="utf-8"))
            ff = j.get("facts", [])
            for f in ff[:limit_per_noteframe]:
                # include simple source anchor
                facts.append(f"{f} (source: {d}/content.md)")
        except Exception:
            continue
    return facts


def call_solver_with_facts(facts: List[str]) -> None:
    """
    Call the Solver model endpoint with the aggregated facts and ask to answer the user question.
    """
    solver_url = os.environ.get("SOLVER_URL", "http://127.0.0.1:8001/v1/chat/completions")
    # Choose a model identifier: prefer THINK_MODEL_ID or SOLVER_MODEL_ID env entries (these may be local paths)
    model_id = os.environ.get("THINK_MODEL_ID") or os.environ.get("SOLVER_MODEL_ID") or "/home/henry/pythonprojects/pandaai/models/solver"

    # Build a compact facts blob
    facts_text = "\n".join(f"- {f}" for f in facts) if facts else "No web facts available."

    user_question = (
        "User question: What's the best hamster to buy for a first-time owner, where to buy it, and what are typical prices?\n\n"
        "Use the provided NoteFrame facts below as your sources. If price information is missing, say so rather than invent numbers. "
        "Provide (1) recommended hamster species for a first-time owner, (2) where to buy (shelter vs pet store vs breeder) with pros/cons, "
        "(3) typical price ranges with source citations, and (4) 1–2 actionable next steps for the user. Cite facts in-line using the source paths."
    )

    messages = [
        {"role": "system", "content": "You are a helpful assistant. Prefer cited sources and avoid hallucination."},
        {"role": "user", "content": user_question + "\n\nWeb facts:\n" + facts_text},
    ]

    payload = {
        "model": model_id,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 800,
    }

    # Try requests, fallback to urllib if missing
    try:
        import requests  # type: ignore
    except Exception:
        requests = None

    print("Calling solver model at:", solver_url, "model:", model_id)
    try:
        if requests:
            resp = requests.post(solver_url, json=payload, timeout=120)
            print("Status:", resp.status_code)
            try:
                print(json.dumps(resp.json(), indent=2))
            except Exception:
                print(resp.text)
        else:
            import urllib.request, json as _json
            data = _json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(solver_url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                body = r.read().decode("utf-8", errors="replace")
                try:
                    print(json.dumps(json.loads(body), indent=2))
                except Exception:
                    print(body)
    except Exception as e:
        print("Solver call failed:", e)
        traceback.print_exc()


def main():
    print("Clearing staging directory (this will delete panda_system_docs/scrape_staging/*)...")
    clear_staging()
    time.sleep(0.2)
    print("Starting discovery + staging...")
    try:
        run_discovery_and_stage(SEARCH_QUERIES)
    except Exception as e:
        print("Discovery/stage failed:", e)
        traceback.print_exc()
        return

    try:
        generate_noteframes()
    except subprocess.CalledProcessError as e:
        print("NoteFrame generation failed:", e)
        return

    facts = collect_noteframe_facts()
    print(f"Collected {len(facts)} facts from noteframes (showing up to first 20):")
    for i, f in enumerate(facts[:20], 1):
        print(f"{i}. {f}")

    call_solver_with_facts(facts)


if __name__ == "__main__":
    main()
