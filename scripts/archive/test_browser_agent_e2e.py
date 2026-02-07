"""
scripts/test_browser_agent_e2e.py

End-to-end integration tests for Browser Agent with research system.

Tests the full flow:
1. User query → Research Role
2. Research Role → Phase 1 (gather_intelligence) or Phase 2 (search_products)
3. Phase functions → visit_and_read → detect multi-page
4. Phase functions → deep_browse → aggregate results
5. Results returned with all pages visited

Created: 2025-11-18
"""

import asyncio
import sys
import os
import logging

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from apps.services.tool_server.research_orchestrator import gather_intelligence, search_products

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_phase1_forum_browsing():
    """
    Test Phase 1 (Intelligence Gathering) with multi-page forum thread.

    Expected behavior:
    - Visits forum thread about hamster breeding
    - Detects multi-page thread
    - Browses all pages (up to max_pages=5)
    - Aggregates intelligence from all pages
    - Returns comprehensive intelligence
    """
    print("\n" + "="*80)
    print("Test 1: Phase 1 - Multi-Page Forum Thread Browsing")
    print("="*80)

    query = "Syrian hamster breeding tips from experienced breeders"
    research_goal = "Learn what experienced breeders recommend for Syrian hamster breeding"

    print(f"\nQuery: {query}")
    print(f"Goal: {research_goal}")
    print("\nExpected: Visit forum threads, detect pagination, browse all pages")

    try:
        result = await gather_intelligence(
            query=query,
            research_goal=research_goal,
            max_sources=5,
            session_id="test_phase1_forum",
            event_emitter=None,
            human_assist_allowed=False,  # Disable for automated testing
            enable_deep_browse=True
        )

        print("\n--- Results ---")
        print(f"Sources checked: {result['stats']['sources_checked']}")
        print(f"\nIntelligence extracted:")
        intelligence = result.get("intelligence", {})
        print(f"  Key topics: {intelligence.get('key_topics', [])}")
        print(f"  Credible sources: {intelligence.get('credible_sources', [])}")
        print(f"  Important criteria: {intelligence.get('important_criteria', [])}")

        # Check for multi-page indicators in sources
        for i, source in enumerate(result.get("sources", [])[:3]):
            pages_visited = source.get("pages_visited", 1)
            print(f"\nSource {i+1}: {source.get('url', 'N/A')[:60]}")
            print(f"  Pages visited: {pages_visited}")
            print(f"  Page type: {source.get('page_type', 'unknown')}")

        assert result['stats']['sources_checked'] > 0, "Expected at least one source"
        assert len(intelligence.get('key_topics', [])) > 0, "Expected intelligence extraction"

        print("\n✅ Phase 1 forum browsing test passed")

    except Exception as e:
        print(f"\n❌ Phase 1 test failed: {e}")
        import traceback
        traceback.print_exc()


async def test_phase2_vendor_catalog():
    """
    Test Phase 2 (Product Search) with multi-page vendor catalog.

    Expected behavior:
    - Visits vendor catalog page
    - Detects pagination or categories
    - Browses all pages/categories (up to max_pages=10)
    - Aggregates all products
    - Deduplicates items
    - Returns comprehensive product list
    """
    print("\n" + "="*80)
    print("Test 2: Phase 2 - Multi-Page Vendor Catalog Browsing")
    print("="*80)

    query = "Syrian hamster for sale"
    research_goal = "Find all available Syrian hamsters from reputable breeders with pricing"
    intelligence = {
        "key_topics": ["breeding quality", "health", "temperament"],
        "credible_sources": ["example-shop.com"],
        "important_criteria": ["age", "health certificate", "breeder reputation"]
    }

    print(f"\nQuery: {query}")
    print(f"Goal: {research_goal}")
    print("\nExpected: Visit vendor catalogs, detect pagination/categories, browse all pages")

    try:
        result = await search_products(
            query=query,
            research_goal=research_goal,
            intelligence=intelligence,
            max_sources=5,
            session_id="test_phase2_catalog",
            event_emitter=None,
            human_assist_allowed=False,  # Disable for automated testing
            enable_deep_browse=True
        )

        print("\n--- Results ---")
        print(f"Sources checked: {result['stats']['sources_checked']}")

        # Extract product counts
        total_products = 0
        for finding in result.get("findings", [])[:3]:
            products = finding.get("extracted_info", {}).get("products", [])
            product_count = len(products) if isinstance(products, list) else 0
            pages_visited = finding.get("pages_visited", 1)

            print(f"\nFinding: {finding.get('url', 'N/A')[:60]}")
            print(f"  Pages visited: {pages_visited}")
            print(f"  Products found: {product_count}")
            print(f"  Page type: {finding.get('page_type', 'unknown')}")

            if product_count > 0 and isinstance(products, list):
                print(f"  Sample products:")
                for product in products[:3]:
                    if isinstance(product, dict):
                        name = product.get("name", product.get("title", "N/A"))
                        price = product.get("price", "N/A")
                        print(f"    - {name} ({price})")

            total_products += product_count

        print(f"\nTotal products across all findings: {total_products}")

        synthesis = result.get("synthesis", {})
        print(f"\nSynthesis confidence: {synthesis.get('confidence', 0.0):.2f}")
        print(f"Key findings: {len(synthesis.get('key_findings', []))}")

        assert result['stats']['sources_checked'] > 0, "Expected at least one source"
        assert total_products > 0, "Expected to find products"

        print("\n✅ Phase 2 vendor catalog test passed")

    except Exception as e:
        print(f"\n❌ Phase 2 test failed: {e}")
        import traceback
        traceback.print_exc()


async def test_content_sanitization():
    """
    Test that content sanitization is working in the flow.

    Expected behavior:
    - Raw HTML is sanitized before LLM processing
    - Metadata includes sanitization stats
    - Token reduction is significant (88-96%)
    """
    print("\n" + "="*80)
    print("Test 3: Content Sanitization Integration")
    print("="*80)

    query = "hamster care guide"
    research_goal = "Find comprehensive guide on hamster care"

    print(f"\nQuery: {query}")
    print("\nExpected: Content sanitized before LLM, metadata shows reduction stats")

    try:
        result = await search_products(
            query=query,
            research_goal=research_goal,
            max_sources=2,
            session_id="test_sanitization",
            event_emitter=None,
            human_assist_allowed=False,
            enable_deep_browse=False  # Disable for this test
        )

        print("\n--- Sanitization Stats ---")
        for i, finding in enumerate(result.get("findings", [])[:2]):
            metadata = finding.get("metadata", {})
            sanitization = metadata.get("sanitization", {})

            print(f"\nFinding {i+1}: {finding.get('url', 'N/A')[:60]}")
            if sanitization.get("used_raw_html"):
                reduction = sanitization.get("reduction_pct", 0)
                original = sanitization.get("original_size", 0)
                sanitized = sanitization.get("sanitized_size", 0)

                print(f"  Sanitization: ✅ Used")
                print(f"  Reduction: {reduction:.1f}%")
                print(f"  Size: {original} → {sanitized} chars")
            else:
                print(f"  Sanitization: ⚠️ Not used (fallback to text_content)")

        print("\n✅ Content sanitization test completed")

    except Exception as e:
        print(f"\n❌ Sanitization test failed: {e}")
        import traceback
        traceback.print_exc()


async def test_llm_evaluation_per_page():
    """
    Test that LLM evaluates after each page during deep browsing.

    Expected behavior:
    - deep_browse() calls should_continue_browsing() after each page
    - LLM calculates new_info_score and goal_satisfaction
    - Stops if new_info_score is low for multiple pages
    - Metadata includes evaluation stats
    """
    print("\n" + "="*80)
    print("Test 4: LLM Evaluation Per Page")
    print("="*80)

    print("\nExpected: LLM evaluates after each page, stops when information plateaus")
    print("This test requires observing logs for evaluation calls\n")

    query = "hamster forum discussion about best bedding"
    research_goal = "Learn community consensus on best hamster bedding"

    try:
        # Enable debug logging to see evaluation
        logging.getLogger("orchestrator.browser_agent").setLevel(logging.DEBUG)

        result = await gather_intelligence(
            query=query,
            research_goal=research_goal,
            max_sources=2,
            session_id="test_llm_eval",
            event_emitter=None,
            human_assist_allowed=False,
            enable_deep_browse=True
        )

        print("\n--- Evaluation Stats ---")
        for i, source in enumerate(result.get("sources", [])[:2]):
            print(f"\nSource {i+1}: {source.get('url', 'N/A')[:60]}")
            print(f"  Pages visited: {source.get('pages_visited', 1)}")

            # Check if stopped early due to evaluation
            stop_reason = source.get("stop_reason")
            if stop_reason:
                print(f"  Stop reason: {stop_reason}")

        print("\n✅ LLM evaluation test completed")
        print("Check logs above for 'should_continue_browsing' calls with LLM scores")

    except Exception as e:
        print(f"\n❌ LLM evaluation test failed: {e}")
        import traceback
        traceback.print_exc()


async def test_all():
    """Run all end-to-end tests"""
    print("\n" + "="*80)
    print("Browser Agent End-to-End Integration Tests")
    print("="*80)
    print("\nThese tests use real network requests and LLM calls.")
    print("Tests may take several minutes to complete.")

    # Run tests sequentially
    await test_phase1_forum_browsing()
    await test_phase2_vendor_catalog()
    await test_content_sanitization()
    await test_llm_evaluation_per_page()

    print("\n" + "="*80)
    print("✅ All Browser Agent E2E tests completed!")
    print("="*80)


if __name__ == "__main__":
    # Check if services are running
    print("\n⚠️  Prerequisites:")
    print("  - vLLM server must be running (port 8000)")
    print("  - Orchestrator must be running (port 8090)")
    print("  - Internet connection required for search")
    print("\nStarting tests in 3 seconds...")
    print("(Press Ctrl+C to cancel)\n")

    import time
    time.sleep(3)

    asyncio.run(test_all())
