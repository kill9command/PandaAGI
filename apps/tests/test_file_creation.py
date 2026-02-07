#!/usr/bin/env python3
"""
Test script to verify file creation via Panda Gateway.
This tests that file creation requests are properly handled
and not misrouted to cached commerce results.
"""

import requests
import json
import sys

# Gateway endpoint
GATEWAY_URL = "http://127.0.0.1:9000/v1/chat/completions"

def test_file_creation():
    """Test that file creation request works correctly"""

    # Request to create a test file
    payload = {
        "model": "qwen3-coder",
        "mode": "continue",  # Code mode
        "repo": "/path/to/pandaagi",
        "messages": [
            {
                "role": "user",
                "content": "Create a simple test file called test_example.py with a hello world function in the repo /path/to/pandaagi"
            }
        ]
    }

    print("Testing file creation request...")
    print(f"Mode: {payload['mode']}")
    print(f"Repo: {payload['repo']}")
    print(f"Request: {payload['messages'][0]['content']}\n")

    try:
        response = requests.post(GATEWAY_URL, json=payload, timeout=60)
        response.raise_for_status()

        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

        print("Response received:")
        print("-" * 50)
        print(content[:500] if len(content) > 500 else content)
        print("-" * 50)

        # Check for misrouting indicators
        misrouting_keywords = ["hamster", "syrian", "price", "$", "eBay", "Barnes", "for sale"]
        found_misrouting = []
        for keyword in misrouting_keywords:
            if keyword.lower() in content.lower():
                found_misrouting.append(keyword)

        if found_misrouting:
            print(f"\n❌ FAILURE: Response contains commerce/pricing keywords: {found_misrouting}")
            print("This indicates the request was misrouted to cached commerce results!")
            return False

        # Check for expected code-related keywords
        expected_keywords = ["file", "created", "test", "python", "hello", "function"]
        found_expected = []
        for keyword in expected_keywords:
            if keyword.lower() in content.lower():
                found_expected.append(keyword)

        if len(found_expected) >= 3:
            print(f"\n✅ SUCCESS: Response contains expected code keywords: {found_expected}")
            print("File creation request was handled correctly!")
            return True
        else:
            print(f"\n⚠️  WARNING: Response may not be handling file creation properly")
            print(f"Found only {len(found_expected)} expected keywords: {found_expected}")
            return False

    except requests.exceptions.RequestException as e:
        print(f"\n❌ ERROR: Request failed: {e}")
        return False
    except Exception as e:
        print(f"\n❌ ERROR: Unexpected error: {e}")
        return False

if __name__ == "__main__":
    success = test_file_creation()
    sys.exit(0 if success else 1)