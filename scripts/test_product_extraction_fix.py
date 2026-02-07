#!/usr/bin/env python3
"""
Test script to verify product extraction pipeline fixes.
"""
import asyncio
import sys
import os
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.services.tool_server.internet_research_mcp import adaptive_research

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_product_extraction():
    """Test that products are properly extracted from vendor pages."""

    # Test query for hamster products
    query = "hamster cages for sale"
    research_goal = "Find hamster cages with prices from different vendors"

    logger.info("=" * 80)
    logger.info(f"Testing product extraction with query: {query}")
    logger.info("=" * 80)

    try:
        # Run research with standard mode
        result = await adaptive_research(
            query=query,
            research_goal=research_goal,
            mode="standard",
            session_id="test_product_extraction",
            force_refresh=True  # Force fresh search to bypass cache
        )

        # Check results
        findings = result.get("results", {}).get("findings", [])
        raw_findings = result.get("results", {}).get("raw_findings", [])
        stats = result.get("stats", {})

        logger.info("\n" + "=" * 80)
        logger.info("RESULTS SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Sources visited: {stats.get('sources_visited', 0)}")
        logger.info(f"Sources extracted: {stats.get('sources_extracted', 0)}")
        logger.info(f"Products found: {len(findings)}")

        # Log raw findings to check extraction
        if raw_findings:
            logger.info("\n" + "=" * 80)
            logger.info("RAW FINDINGS ANALYSIS")
            logger.info("=" * 80)
            for i, finding in enumerate(raw_findings, 1):
                url = finding.get("url", "Unknown")
                extracted_info = finding.get("extracted_info", {})
                products = extracted_info.get("products", None)
                page_type = extracted_info.get("page_type", "unknown")

                logger.info(f"\n{i}. {url[:60]}...")
                logger.info(f"   Page type: {page_type}")
                logger.info(f"   Has extracted_info: {bool(extracted_info)}")
                logger.info(f"   Products field: {type(products).__name__ if products is not None else 'None'}")
                if isinstance(products, list):
                    logger.info(f"   Product count: {len(products)}")
                    if products:
                        # Show first product as sample
                        logger.info(f"   Sample product: {products[0]}")

        # Log extracted products
        if findings:
            logger.info("\n" + "=" * 80)
            logger.info(f"EXTRACTED PRODUCTS ({len(findings)} total)")
            logger.info("=" * 80)
            for i, product in enumerate(findings[:5], 1):  # Show first 5
                logger.info(f"\n{i}. {product.get('name', 'Unknown')}")
                logger.info(f"   Price: {product.get('price', 'N/A')}")
                logger.info(f"   Vendor: {product.get('vendor', 'Unknown')}")
                logger.info(f"   URL: {product.get('url', 'N/A')[:60]}...")
                if product.get('description'):
                    logger.info(f"   Description: {product['description'][:100]}...")
        else:
            logger.warning("\n⚠️  NO PRODUCTS EXTRACTED!")

        # Success/failure determination
        if findings:
            logger.info("\n✅ SUCCESS: Product extraction pipeline is working!")
            return True
        else:
            logger.error("\n❌ FAILURE: No products were extracted")
            logger.info("\nDEBUGGING TIPS:")
            logger.info("1. Check if LLM is returning products in _extract_information_llm")
            logger.info("2. Verify the prompt format matches what the LLM expects")
            logger.info("3. Check if the sanitized content contains product information")
            logger.info("4. Review the LLM logs for extraction attempts")
            return False

    except Exception as e:
        logger.error(f"\n❌ Test failed with error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


if __name__ == "__main__":
    success = asyncio.run(test_product_extraction())
    sys.exit(0 if success else 1)