#!/usr/bin/env python3
"""
Test the cache fingerprint fix with backward compatibility.
"""
import asyncio
import sys
sys.path.insert(0, '/path/to/pandaagi')

from apps.services.tool_server.shared_state.response_cache import RESPONSE_CACHE

async def test_cache_lookup():
    """Test cache lookup with different domain values."""

    test_cases = [
        {
            "name": "Original domain (should find via legacy)",
            "query": "can you find some for sale for me online?",
            "context": {
                "session_id": "default",
                "preferences": {
                    "budget": "online search for sale items",
                    "location": "online",
                    "favorite_hamster_breed": "Syrian hamster"
                },
                "domain": "shopping for hamsters online"  # Original domain
            }
        },
        {
            "name": "Different domain (should still find via legacy)",
            "query": "can you find some for sale for me online?",
            "context": {
                "session_id": "default",
                "preferences": {
                    "budget": "online search for sale items",
                    "location": "online",
                    "favorite_hamster_breed": "Syrian hamster"
                },
                "domain": "shopping for Syrian hamsters"  # Different domain
            }
        },
        {
            "name": "No domain (should use new fingerprint)",
            "query": "can you find some for sale for me online?",
            "context": {
                "session_id": "default",
                "preferences": {
                    "budget": "online search for sale items",
                    "location": "online",
                    "favorite_hamster_breed": "Syrian hamster"
                },
                "domain": ""  # No domain
            }
        }
    ]

    for tc in test_cases:
        print(f"\nTest: {tc['name']}")
        print(f"  Query: {tc['query'][:50]}...")
        print(f"  Domain: '{tc['context']['domain']}'")

        candidates = await RESPONSE_CACHE.search(
            query=tc['query'],
            intent="transactional",
            domain=tc['context']['domain'],
            session_context=tc['context']
        )

        if candidates:
            best = candidates[0]
            print(f"  ✅ CACHE HIT!")
            print(f"     Hybrid score: {best.hybrid_score:.3f}")
            print(f"     Semantic: {best.semantic_score:.3f}")
            print(f"     Keyword: {best.keyword_score:.3f}")
            print(f"     Age: {best.age_hours:.1f} hours")
            print(f"     Response preview: {best.response[:100]}...")
        else:
            print(f"  ❌ CACHE MISS")

if __name__ == "__main__":
    asyncio.run(test_cache_lookup())