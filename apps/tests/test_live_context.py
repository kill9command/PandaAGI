#!/usr/bin/env python3
"""
Test script for Living Session Context integration.

Tests the Syrian hamster conversation scenario:
1. First query: "I'm interested in Syrian hamsters"
2. Second query: "what do they eat?"
3. Third query: "can you find some for sale for me online?"

Expected behavior:
- Turn 1: Context created with topic="interested in Syrian hamsters"
- Turn 2: Context includes previous topic, adds care facts
- Turn 3: Context includes preferences and previous actions, meta-reflection confidence should be high
"""

import httpx
import json
import time
from pathlib import Path

GATEWAY_URL = "http://127.0.0.1:9000/v1/chat/completions"
PROFILE_ID = "test_live_context_user"

def send_query(query: str, profile_id: str = PROFILE_ID):
    """Send a query to the Gateway and return the response."""
    payload = {
        "model": "qwen3-coder",
        "messages": [{"role": "user", "content": query}],
        "profile": profile_id,
        "stream": False
    }

    print(f"\n{'='*80}")
    print(f"Query: {query}")
    print(f"{'='*80}")

    response = httpx.post(GATEWAY_URL, json=payload, timeout=120.0)
    response.raise_for_status()

    data = response.json()
    answer = data.get("choices", [{}])[0].get("message", {}).get("content", "")

    print(f"\nAnswer: {answer[:500]}...")

    # Get trace_id from response
    trace_id = data.get("id")
    if trace_id:
        # Check for live_context_stats in verbose trace
        day = time.strftime("%Y%m%d")
        verbose_path = Path(f"/path/to/pandaagi/transcripts/verbose/{day}/{trace_id}.json")

        if verbose_path.exists():
            with open(verbose_path, 'r') as f:
                trace = json.load(f)

            # Print meta-reflection result
            meta = trace.get("meta_reflection", {})
            if meta:
                print(f"\nMeta-Reflection:")
                print(f"  Confidence: {meta.get('confidence', 'N/A')}")
                print(f"  Action: {meta.get('action', 'N/A')}")
                print(f"  Reason: {meta.get('reason', 'N/A')}")

            # Print live context stats
            ctx_stats = trace.get("live_context_stats", {})
            if ctx_stats:
                print(f"\nLive Context Stats:")
                print(f"  Turn: {ctx_stats.get('turn_count', 'N/A')}")
                print(f"  Preferences: {ctx_stats.get('preferences', 'N/A')}")
                print(f"  Recent Actions: {ctx_stats.get('recent_actions', 'N/A')}")
                print(f"  Fact Categories: {ctx_stats.get('fact_categories', 'N/A')}")
                print(f"  Total Facts: {ctx_stats.get('total_facts', 'N/A')}")
                print(f"  Pending Tasks: {ctx_stats.get('pending_tasks', 'N/A')}")
        else:
            print(f"\nTrace not found: {verbose_path}")

    return data

def main():
    print("Living Session Context Test")
    print("="*80)
    print("Testing Syrian hamster conversation scenario")
    print("="*80)

    # Clear any existing context for this test user
    session_ctx_path = Path(f"/path/to/pandaagi/panda_system_docs/shared_state/session_contexts/{PROFILE_ID}.json")
    if session_ctx_path.exists():
        print(f"\nClearing existing context: {session_ctx_path}")
        session_ctx_path.unlink()

    # Turn 1: Express interest in Syrian hamsters
    print("\n\n" + "="*80)
    print("TURN 1: Express interest in Syrian hamsters")
    print("="*80)
    send_query("I'm interested in Syrian hamsters", PROFILE_ID)
    time.sleep(2)  # Small delay between requests

    # Turn 2: Ask about diet (should remember Syrian hamster context)
    print("\n\n" + "="*80)
    print("TURN 2: Ask about diet (should remember Syrian hamster context)")
    print("="*80)
    send_query("what do they eat?", PROFILE_ID)
    time.sleep(2)

    # Turn 3: Ask to find for sale (should have accumulated context)
    print("\n\n" + "="*80)
    print("TURN 3: Ask to find for sale (should have accumulated preferences)")
    print("="*80)
    send_query("can you find some for sale for me online?", PROFILE_ID)

    print("\n\n" + "="*80)
    print("TEST COMPLETE")
    print("="*80)
    print("\nCheck the results above:")
    print("- Turn 1 meta-reflection should understand the query")
    print("- Turn 2 should have context about Syrian hamsters from Turn 1")
    print("- Turn 3 should have highest confidence (accumulated context)")
    print("\nContext should grow: Turn 1 → Turn 2 → Turn 3")

if __name__ == "__main__":
    main()
