#!/usr/bin/env python3
"""
Simplified test to verify file operations aren't misrouted.
"""

import requests
import json
import sys

GATEWAY_URL = "http://127.0.0.1:9000/v1/chat/completions"

def test_simple_file():
    """Test simple file operation"""

    # Very simple request
    payload = {
        "model": "qwen3-coder",
        "mode": "continue",
        "repo": "/path/to/pandaagi",
        "messages": [
            {
                "role": "user",
                "content": "Write 'hello world' to test.txt"
            }
        ]
    }

    print("Testing simple file write request...")
    print(f"Request: {payload['messages'][0]['content']}\n")

    try:
        response = requests.post(GATEWAY_URL, json=payload, timeout=60)
        response.raise_for_status()

        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

        print("Response received:")
        print("-" * 50)
        print(content[:500])
        print("-" * 50)

        # Check for misrouting
        if any(word in content.lower() for word in ["hamster", "syrian", "ebay", "barnes"]):
            print("\n❌ FAILURE: Response contains cached commerce results!")
            return False

        # Check for success indicators
        if any(word in content.lower() for word in ["created", "wrote", "written", "file", "test.txt"]):
            print("\n✅ SUCCESS: File operation completed correctly!")
            return True

        print("\n⚠️  WARNING: Unclear if operation succeeded")
        return False

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        return False

if __name__ == "__main__":
    success = test_simple_file()
    sys.exit(0 if success else 1)