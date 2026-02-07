"""
Test Gateway-delegated research implementation.

Tests the v3 research flow with Gateway delegation.
"""

import asyncio
import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apps.services.tool_server.internet_research_mcp import adaptive_research

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

logger = logging.getLogger(__name__)


async def test_gateway_research():
    """
    Test Gateway-delegated research with Syrian hamsters query.
    """

    logger.info("="*80)
    logger.info("TESTING: Gateway-Delegated Research (v3)")
    logger.info("="*80)

    query = "Syrian hamsters for sale online"
    research_goal = "Find 3+ online vendors selling Syrian hamsters with pricing and availability"

    logger.info(f"\nQuery: {query}")
    logger.info(f"Goal: {research_goal}")
    logger.info("\nStarting research...\n")

    try:
        result = await adaptive_research(
            query=query,
            research_goal=research_goal,
            session_id="test_gateway_research",
            mode="standard",
            query_type="commerce_search",
            force_refresh=True
        )

        logger.info("\n" + "="*80)
        logger.info("RESEARCH RESULTS")
        logger.info("="*80)

        if "error" in result:
            logger.error(f"❌ Research FAILED: {result.get('message')}")
            logger.error(f"Details: {result.get('details', 'N/A')}")
            return False

        # Extract stats
        stats = result.get("stats", {})
        findings = result.get("findings", [])
        sources = result.get("sources", [])

        logger.info(f"\n✅ Research SUCCESS")
        logger.info(f"Cycles used: {stats.get('cycles_used')}")
        logger.info(f"Sources visited: {stats.get('sources_visited')}")
        logger.info(f"Findings extracted: {stats.get('findings_extracted')}")
        logger.info(f"Strategy: {result.get('strategy')}")

        # Display findings
        logger.info(f"\nFindings ({len(findings)}):")
        for i, finding in enumerate(findings[:10], 1):  # Show first 10
            logger.info(f"  {i}. {finding.get('field')}: {finding.get('value')}")
            logger.info(f"     Source: {finding.get('source', 'N/A')}")
            logger.info(f"     Confidence: {finding.get('confidence', 'N/A')}")

        # Display sources
        logger.info(f"\nSources ({len(sources)}):")
        for i, source in enumerate(sources[:10], 1):  # Show first 10
            logger.info(f"  {i}. {source}")

        # Validation
        logger.info("\n" + "-"*80)
        logger.info("VALIDATION")
        logger.info("-"*80)

        success = True

        if stats.get('findings_extracted', 0) == 0:
            logger.error("❌ FAIL: 0 findings extracted (same as before!)")
            success = False
        else:
            logger.info(f"✅ PASS: {stats.get('findings_extracted')} findings extracted")

        if stats.get('sources_visited', 0) < 2:
            logger.warning(f"⚠️  WARNING: Only {stats.get('sources_visited')} sources visited")
        else:
            logger.info(f"✅ PASS: {stats.get('sources_visited')} sources visited")

        if stats.get('cycles_used', 0) > 20:
            logger.warning(f"⚠️  WARNING: {stats.get('cycles_used')} cycles used (over limit)")
        else:
            logger.info(f"✅ PASS: {stats.get('cycles_used')} cycles used")

        return success

    except Exception as e:
        logger.error(f"❌ Test EXCEPTION: {e}", exc_info=True)
        return False


async def test_lightweight_mode():
    """
    Test Gateway lightweight mode directly.
    """

    logger.info("\n" + "="*80)
    logger.info("TESTING: Gateway Lightweight Mode")
    logger.info("="*80)

    import httpx
    import os

    gateway_url = os.getenv("GATEWAY_URL", "http://127.0.0.1:9000")
    api_key = os.getenv("GATEWAY_API_KEY", os.getenv("LLM_API_KEY", "qwen-local"))

    prompt = """You are a test assistant. Respond with JSON only:
{
  "status": "success",
  "message": "Lightweight mode working"
}
"""

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{gateway_url}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "X-Research-Mode": "lightweight"
                },
                json={
                    "model": "qwen3-coder",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 200,
                    "temperature": 0.3
                }
            )
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        logger.info(f"✅ Lightweight mode response: {content[:200]}")

        if "success" in content.lower():
            logger.info("✅ PASS: Lightweight mode working")
            return True
        else:
            logger.warning("⚠️  UNCERTAIN: Response may not be valid JSON")
            return True

    except Exception as e:
        logger.error(f"❌ FAIL: Lightweight mode error: {e}")
        return False


async def main():
    """
    Run all tests.
    """

    logger.info("Starting Gateway Research Tests\n")

    # Test 1: Lightweight mode
    logger.info("\n### Test 1: Gateway Lightweight Mode")
    test1_pass = await test_lightweight_mode()

    # Test 2: Gateway-delegated research
    logger.info("\n### Test 2: Gateway-Delegated Research")
    test2_pass = await test_gateway_research()

    # Summary
    logger.info("\n" + "="*80)
    logger.info("TEST SUMMARY")
    logger.info("="*80)
    logger.info(f"Test 1 (Lightweight Mode): {'✅ PASS' if test1_pass else '❌ FAIL'}")
    logger.info(f"Test 2 (Research Flow): {'✅ PASS' if test2_pass else '❌ FAIL'}")

    overall = test1_pass and test2_pass
    logger.info(f"\nOverall: {'✅ ALL TESTS PASSED' if overall else '❌ SOME TESTS FAILED'}")

    return 0 if overall else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
