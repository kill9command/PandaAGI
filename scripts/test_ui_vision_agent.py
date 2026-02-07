#!/usr/bin/env python3
"""
Test harness for UI Vision Agent

Tests perception (DOM + OCR + shapes) and targeting modules.
Saves annotated screenshots showing detected candidates.

Usage:
    python3 scripts/test_ui_vision_agent.py
    python3 scripts/test_ui_vision_agent.py --url https://example.com --goal "click Next"
"""
import sys
sys.path.insert(0, '.')

import asyncio
import argparse
import logging
from playwright.async_api import async_playwright
from apps.services.tool_server.ui_vision_agent import UIVisionAgent, CandidateSource
from apps.services.tool_server.stealth_injector import Stealth

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


async def annotate_screenshot(
    screenshot_path: str,
    candidates: list,
    output_path: str
):
    """
    Draw bounding boxes on screenshot for visualization.

    Args:
        screenshot_path: Input screenshot
        candidates: List of UICandidate objects
        output_path: Output annotated screenshot
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        logger.warning("OpenCV not available, skipping annotation")
        return

    # Read image
    img = cv2.imread(screenshot_path)
    if img is None:
        logger.error(f"Failed to load screenshot: {screenshot_path}")
        return

    # Define colors for different sources
    colors = {
        CandidateSource.DOM: (0, 255, 0),  # Green
        CandidateSource.VISION_OCR: (255, 165, 0),  # Orange
        CandidateSource.VISION_SHAPE: (0, 0, 255),  # Red
    }

    # Draw bounding boxes for top 10 candidates
    for i, candidate in enumerate(candidates[:10]):
        bbox = candidate.bbox
        color = colors.get(candidate.source, (128, 128, 128))

        # Draw rectangle
        pt1 = (int(bbox.x), int(bbox.y))
        pt2 = (int(bbox.x + bbox.width), int(bbox.y + bbox.height))
        cv2.rectangle(img, pt1, pt2, color, 2)

        # Draw label
        label = f"{i+1}: {candidate.text[:20]} ({candidate.confidence:.2f})"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.5
        thickness = 1

        # Background for text
        (text_width, text_height), _ = cv2.getTextSize(label, font, font_scale, thickness)
        cv2.rectangle(
            img,
            (int(bbox.x), int(bbox.y) - text_height - 5),
            (int(bbox.x) + text_width, int(bbox.y)),
            color,
            -1
        )

        # Text
        cv2.putText(
            img,
            label,
            (int(bbox.x), int(bbox.y) - 5),
            font,
            font_scale,
            (255, 255, 255),
            thickness
        )

    # Save annotated image
    cv2.imwrite(output_path, img)
    logger.info(f"✅ Saved annotated screenshot: {output_path}")


async def test_perception_module(url: str):
    """Test Module 1 - Perception"""
    logger.info("="*80)
    logger.info("TEST 1: Perception Module (DOM + OCR + Shapes)")
    logger.info("="*80)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        # Apply stealth
        stealth = Stealth()
        await stealth.apply_stealth_async(context)

        page = await context.new_page()

        # Navigate to page
        logger.info(f"Navigating to: {url}")
        await page.goto(url, wait_until="networkidle")

        # Initialize agent
        agent = UIVisionAgent(page, enable_ocr=True, enable_shapes=True)

        # Extract candidates
        logger.info("Extracting candidates...")
        screenshot_path = "/tmp/ui_vision_test_raw.png"
        await page.screenshot(path=screenshot_path)

        candidates = await agent.perception.extract_candidates(page, screenshot_path)

        # Report results
        logger.info(f"\n{'='*80}")
        logger.info(f"PERCEPTION RESULTS: {len(candidates)} candidates found")
        logger.info(f"{'='*80}")

        # Count by source
        dom_count = sum(1 for c in candidates if c.source == CandidateSource.DOM)
        ocr_count = sum(1 for c in candidates if c.source == CandidateSource.VISION_OCR)
        shape_count = sum(1 for c in candidates if c.source == CandidateSource.VISION_SHAPE)

        logger.info(f"  DOM:   {dom_count}")
        logger.info(f"  OCR:   {ocr_count}")
        logger.info(f"  Shape: {shape_count}")

        # Show top 10 candidates
        logger.info(f"\nTop 10 candidates:")
        for i, candidate in enumerate(candidates[:10], 1):
            logger.info(
                f"  {i}. [{candidate.source.value:12}] "
                f"confidence={candidate.confidence:.2f} "
                f"text='{candidate.text[:40]}' "
                f"bbox=({candidate.bbox.x:.0f},{candidate.bbox.y:.0f},"
                f"{candidate.bbox.width:.0f}x{candidate.bbox.height:.0f})"
            )

        # Annotate screenshot
        output_path = "/tmp/ui_vision_test_annotated.png"
        await annotate_screenshot(screenshot_path, candidates, output_path)

        await browser.close()

    return candidates


async def test_targeting_module(url: str, goal: str):
    """Test Module 2 - Targeting Policy"""
    logger.info("\n" + "="*80)
    logger.info(f"TEST 2: Targeting Policy - Goal: '{goal}'")
    logger.info("="*80)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        # Apply stealth
        stealth = Stealth()
        await stealth.apply_stealth_async(context)

        page = await context.new_page()

        # Navigate to page
        logger.info(f"Navigating to: {url}")
        await page.goto(url, wait_until="networkidle")

        # Initialize agent
        agent = UIVisionAgent(page, enable_ocr=True, enable_shapes=True)

        # Extract and rank candidates
        logger.info("Extracting candidates...")
        screenshot_path = "/tmp/ui_vision_test_targeting.png"
        await page.screenshot(path=screenshot_path)

        candidates = await agent.perception.extract_candidates(page, screenshot_path)

        logger.info(f"Ranking {len(candidates)} candidates for goal: {goal}")
        viewport = await page.viewport_size()
        ranked = agent.targeting.rank_candidates(
            candidates,
            goal,
            viewport_width=viewport["width"],
            viewport_height=viewport["height"]
        )

        # Report results
        logger.info(f"\n{'='*80}")
        logger.info(f"TARGETING RESULTS: Top matches for '{goal}'")
        logger.info(f"{'='*80}")

        for i, candidate in enumerate(ranked[:5], 1):
            logger.info(
                f"  {i}. [{candidate.source.value:12}] "
                f"score={candidate.confidence:.3f} "
                f"text='{candidate.text[:40]}'"
            )

        # Annotate with ranked candidates
        output_path = "/tmp/ui_vision_test_targeting_annotated.png"
        await annotate_screenshot(screenshot_path, ranked, output_path)

        await browser.close()

    return ranked


async def test_full_flow(url: str, goal: str):
    """Test full agent click() method"""
    logger.info("\n" + "="*80)
    logger.info(f"TEST 3: Full Flow - agent.click('{goal}')")
    logger.info("="*80)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        # Apply stealth
        stealth = Stealth()
        await stealth.apply_stealth_async(context)

        page = await context.new_page()

        # Navigate to page
        logger.info(f"Navigating to: {url}")
        await page.goto(url, wait_until="networkidle")

        # Initialize agent
        agent = UIVisionAgent(page, enable_ocr=True, enable_shapes=True)

        # Call agent.click()
        logger.info(f"Calling agent.click('{goal}')")
        result = await agent.click(goal, max_attempts=3, timeout=30.0)

        # Report results
        logger.info(f"\n{'='*80}")
        logger.info(f"AGENT.CLICK() RESULT")
        logger.info(f"{'='*80}")
        logger.info(f"  Success: {result.success}")
        logger.info(f"  Verification: {result.verification_method}")
        if result.candidate:
            logger.info(f"  Top candidate: [{result.candidate.source.value}] '{result.candidate.text[:40]}'")
            logger.info(f"  Confidence: {result.candidate.confidence:.3f}")
        logger.info(f"  Metadata: {result.metadata}")

        await browser.close()

    return result


async def main():
    parser = argparse.ArgumentParser(description="Test UI Vision Agent")
    parser.add_argument(
        "--url",
        default="https://www.google.com",
        help="URL to test (default: Google)"
    )
    parser.add_argument(
        "--goal",
        default="Search",
        help="Goal for targeting test (default: 'Search')"
    )
    parser.add_argument(
        "--test",
        choices=["perception", "targeting", "full", "all"],
        default="all",
        help="Which test to run"
    )

    args = parser.parse_args()

    logger.info("="*80)
    logger.info("UI VISION AGENT TEST HARNESS")
    logger.info("="*80)
    logger.info(f"URL: {args.url}")
    logger.info(f"Goal: {args.goal}")
    logger.info(f"Test: {args.test}")
    logger.info("")

    try:
        if args.test in ["perception", "all"]:
            candidates = await test_perception_module(args.url)

        if args.test in ["targeting", "all"]:
            ranked = await test_targeting_module(args.url, args.goal)

        if args.test in ["full", "all"]:
            result = await test_full_flow(args.url, args.goal)

        logger.info("\n" + "="*80)
        logger.info("✅ ALL TESTS COMPLETED")
        logger.info("="*80)
        logger.info("Check /tmp/ for annotated screenshots:")
        logger.info("  /tmp/ui_vision_test_annotated.png (perception)")
        logger.info("  /tmp/ui_vision_test_targeting_annotated.png (targeting)")

    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
