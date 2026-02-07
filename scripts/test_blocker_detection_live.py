#!/usr/bin/env python3
"""
Test script to verify why blocker detection is not triggering.
Adds diagnostic logging to human_search_engine.
"""
import asyncio
import logging
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_search():
    """Test search with diagnostic logging."""
    from apps.services.tool_server import human_search_engine

    logger.info("=" * 80)
    logger.info("TESTING BLOCKER DETECTION")
    logger.info("=" * 80)

    query = "Find Syrian hamsters for sale online"

    try:
        results = await human_search_engine.search(
            query=query,
            k=3,
            session_id="test_blocker_detection",
            human_assist_allowed=True
        )

        logger.info(f"\nRESULTS: {len(results)} items")
        for i, r in enumerate(results):
            logger.info(f"  {i+1}. {r.get('title', 'N/A')}")

    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(test_search())
