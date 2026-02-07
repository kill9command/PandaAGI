#!/usr/bin/env python3
import json
import sys
import traceback

# This script assumes the caller will source .env before running so that
# SERPAPI_API_KEY and other env vars are available. Example:
#   set -a && source .env && PYTHONPATH=/path/to/pandaagi python scripts/serpapi_live_test.py

def main():
    try:
        from apps.services.tool_server import context_builder, serpapi_quota
    except Exception as e:
        print("Failed to import orchestrator modules:", e)
        traceback.print_exc()
        sys.exit(1)

    try:
        remaining_before = serpapi_quota.get_remaining()
    except Exception as e:
        remaining_before = None
        print("Quota module unavailable (will proceed):", e)

    print("Quota before:", remaining_before)

    search_request = {
        "queries": [
            "prompts and context management panda",
            "panda search process",
            "NoteFrame summarization"
        ],
        "fetch_mode": "search_api",
        "k_per_query": 3,
        "follow_links": False,
        "follow_links_depth": 0,
        "max_links_per_page": 0
    }

    try:
        print("Running perform_search_request with search_api (will consume SerpAPI calls)...")
        results = context_builder.perform_search_request(search_request, staged_root="panda_system_docs/scrape_staging")
        print(json.dumps(results, indent=2))
    except Exception as e:
        print("Error during perform_search_request:")
        traceback.print_exc()
        sys.exit(1)

    try:
        remaining_after = serpapi_quota.get_remaining()
    except Exception as e:
        remaining_after = None
        print("Quota module unavailable (post-call):", e)

    print("\\nQuota remaining after call:", remaining_after)
    print("Done")

if __name__ == '__main__':
    main()
