#!/usr/bin/env python3
"""
Test harness for Computer Agent (Desktop Automation)

Tests the complete desktop automation stack:
- DesktopPerceptionEngine (screen capture + OCR + shapes)
- TargetingPolicy (candidate ranking)
- DesktopActuator (mouse/keyboard actions)
- ActionVerifier (screenshot diff)
- ComputerAgent (orchestration)

Usage:
    python3 scripts/test_computer_agent.py
    python3 scripts/test_computer_agent.py --test click --goal "Start menu"
    python3 scripts/test_computer_agent.py --test type --text "hello world"
    python3 scripts/test_computer_agent.py --test screenshot
"""
import sys
sys.path.insert(0, '.')

import asyncio
import argparse
import logging

from apps.services.orchestrator.computer_agent import ComputerAgent

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


async def test_screenshot():
    """Test Module: Screenshot Capture"""
    logger.info("="*80)
    logger.info("TEST: Screenshot Capture")
    logger.info("="*80)

    agent = ComputerAgent(enable_ocr=True, enable_shapes=True)

    # Get screen info
    width, height = await agent.actuator.get_screen_size()
    logger.info(f"Screen size: {width}x{height}")

    # Capture screenshot
    success, error, path = await agent.actuator.screenshot("/tmp/computer_agent_test.png")

    if success:
        logger.info(f"✅ Screenshot saved: {path}")
        return True
    else:
        logger.error(f"❌ Screenshot failed: {error}")
        return False


async def test_perception():
    """Test Module: Perception (OCR + Shapes)"""
    logger.info("\n" + "="*80)
    logger.info("TEST: Perception Module (Screen OCR + Shape Detection)")
    logger.info("="*80)

    agent = ComputerAgent(enable_ocr=True, enable_shapes=True)

    # Take screenshot
    screenshot_path = "/tmp/computer_agent_perception_test.png"
    width, height = await agent.actuator.get_screen_size()
    await agent.actuator.screenshot(screenshot_path)

    # Extract candidates
    logger.info(f"Extracting candidates from {screenshot_path}...")
    candidates = await agent.perception.extract_candidates(
        screenshot_path,
        width,
        height
    )

    # Report results
    logger.info(f"\n{'='*80}")
    logger.info(f"PERCEPTION RESULTS: {len(candidates)} candidates found")
    logger.info(f"{'='*80}")

    # Count by source
    from apps.services.orchestrator.desktop_perception import CandidateSource
    ocr_count = sum(1 for c in candidates if c.source == CandidateSource.SCREEN_OCR)
    shape_count = sum(1 for c in candidates if c.source == CandidateSource.SCREEN_SHAPE)
    window_count = sum(1 for c in candidates if c.source == CandidateSource.WINDOW_API)

    logger.info(f"  OCR:    {ocr_count}")
    logger.info(f"  Shapes: {shape_count}")
    logger.info(f"  Windows: {window_count}")

    # Show top 10 candidates
    logger.info(f"\nTop 10 candidates:")
    for i, candidate in enumerate(candidates[:10], 1):
        logger.info(
            f"  {i}. [{candidate.source.value:15}] "
            f"confidence={candidate.confidence:.2f} "
            f"text='{candidate.text[:40]}' "
            f"bbox=({candidate.bbox.x:.0f},{candidate.bbox.y:.0f},"
            f"{candidate.bbox.width:.0f}x{candidate.bbox.height:.0f})"
        )

    return len(candidates) > 0


async def test_targeting(goal: str):
    """Test Module: Targeting Policy"""
    logger.info("\n" + "="*80)
    logger.info(f"TEST: Targeting Policy - Goal: '{goal}'")
    logger.info("="*80)

    agent = ComputerAgent(enable_ocr=True, enable_shapes=True)

    # Take screenshot and extract candidates
    screenshot_path = "/tmp/computer_agent_targeting_test.png"
    width, height = await agent.actuator.get_screen_size()
    await agent.actuator.screenshot(screenshot_path)

    candidates = await agent.perception.extract_candidates(
        screenshot_path,
        width,
        height
    )

    logger.info(f"Ranking {len(candidates)} candidates for goal: {goal}")

    # Rank candidates
    ranked = agent.targeting.rank_candidates(
        candidates,
        goal,
        width,
        height
    )

    # Report results
    logger.info(f"\n{'='*80}")
    logger.info(f"TARGETING RESULTS: Top matches for '{goal}'")
    logger.info(f"{'='*80}")

    for i, candidate in enumerate(ranked[:5], 1):
        logger.info(
            f"  {i}. [{candidate.source.value:15}] "
            f"score={candidate.confidence:.3f} "
            f"text='{candidate.text[:40]}'"
        )

    return len(ranked) > 0 and ranked[0].confidence > 0


async def test_click(goal: str):
    """Test Full Flow: Click Action"""
    logger.info("\n" + "="*80)
    logger.info(f"TEST: Full Click Flow - agent.click('{goal}')")
    logger.info("="*80)

    agent = ComputerAgent(enable_ocr=True, enable_shapes=True)

    # Execute click
    logger.info(f"Calling agent.click('{goal}')...")
    result = await agent.click(goal, max_attempts=3, timeout=30.0)

    # Report results
    logger.info(f"\n{'='*80}")
    logger.info(f"CLICK RESULT")
    logger.info(f"{'='*80}")
    logger.info(f"  Success: {result.success}")
    logger.info(f"  Verification: {result.verification_method}")
    if result.candidate:
        logger.info(f"  Top candidate: [{result.candidate.source.value}] '{result.candidate.text[:40]}'")
        logger.info(f"  Confidence: {result.candidate.confidence:.3f}")
    logger.info(f"  Metadata: {result.metadata}")

    return result.success


async def test_type(text: str, into: str = None):
    """Test Full Flow: Type Action"""
    logger.info("\n" + "="*80)
    logger.info(f"TEST: Full Type Flow - agent.type_text('{text}', into='{into}')")
    logger.info("="*80)

    agent = ComputerAgent(enable_ocr=True, enable_shapes=True)

    # Execute type
    logger.info(f"Calling agent.type_text('{text}', into='{into}')...")
    result = await agent.type_text(text, into=into, interval=0.05)

    # Report results
    logger.info(f"\n{'='*80}")
    logger.info(f"TYPE RESULT")
    logger.info(f"{'='*80}")
    logger.info(f"  Success: {result.success}")
    logger.info(f"  Verification: {result.verification_method}")
    logger.info(f"  Metadata: {result.metadata}")

    return result.success


async def test_press_key(key: str):
    """Test Full Flow: Press Key Action"""
    logger.info("\n" + "="*80)
    logger.info(f"TEST: Full Press Key Flow - agent.press_key('{key}')")
    logger.info("="*80)

    agent = ComputerAgent(enable_ocr=True, enable_shapes=True)

    # Execute press
    logger.info(f"Calling agent.press_key('{key}')...")
    result = await agent.press_key(key, presses=1)

    # Report results
    logger.info(f"\n{'='*80}")
    logger.info(f"PRESS KEY RESULT")
    logger.info(f"{'='*80}")
    logger.info(f"  Success: {result.success}")
    logger.info(f"  Verification: {result.verification_method}")
    logger.info(f"  Metadata: {result.metadata}")

    return result.success


async def test_scroll(clicks: int):
    """Test Full Flow: Scroll Action"""
    logger.info("\n" + "="*80)
    logger.info(f"TEST: Full Scroll Flow - agent.scroll({clicks})")
    logger.info("="*80)

    agent = ComputerAgent(enable_ocr=True, enable_shapes=True)

    # Execute scroll
    logger.info(f"Calling agent.scroll({clicks})...")
    result = await agent.scroll(clicks)

    # Report results
    logger.info(f"\n{'='*80}")
    logger.info(f"SCROLL RESULT")
    logger.info(f"{'='*80}")
    logger.info(f"  Success: {result.success}")
    logger.info(f"  Verification: {result.verification_method}")
    logger.info(f"  Metadata: {result.metadata}")

    return result.success


async def test_all():
    """Run all tests"""
    logger.info("="*80)
    logger.info("COMPUTER AGENT - FULL TEST SUITE")
    logger.info("="*80)

    results = {}

    # Test 1: Screenshot
    results['screenshot'] = await test_screenshot()

    # Test 2: Perception
    results['perception'] = await test_perception()

    # Test 3: Targeting (requires manual goal)
    results['targeting'] = await test_targeting("File")

    # Summary
    logger.info("\n" + "="*80)
    logger.info("TEST SUMMARY")
    logger.info("="*80)
    for test_name, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"  {test_name:15} {status}")

    all_passed = all(results.values())
    if all_passed:
        logger.info("\n🎉 ALL TESTS PASSED")
    else:
        logger.info("\n⚠️  SOME TESTS FAILED")

    return all_passed


async def main():
    parser = argparse.ArgumentParser(description="Test Computer Agent")
    parser.add_argument(
        "--test",
        choices=["screenshot", "perception", "targeting", "click", "type", "press", "scroll", "all"],
        default="all",
        help="Which test to run"
    )
    parser.add_argument(
        "--goal",
        default="File",
        help="Goal for targeting/click test (default: 'File')"
    )
    parser.add_argument(
        "--text",
        default="test",
        help="Text for type test (default: 'test')"
    )
    parser.add_argument(
        "--into",
        default=None,
        help="Target field for type test (optional)"
    )
    parser.add_argument(
        "--key",
        default="tab",
        help="Key for press test (default: 'tab')"
    )
    parser.add_argument(
        "--scroll-clicks",
        type=int,
        default=3,
        help="Scroll clicks for scroll test (default: 3)"
    )

    args = parser.parse_args()

    logger.info("="*80)
    logger.info("COMPUTER AGENT TEST HARNESS")
    logger.info("="*80)
    logger.info(f"Test: {args.test}")
    logger.info("")

    try:
        if args.test == "screenshot":
            success = await test_screenshot()
        elif args.test == "perception":
            success = await test_perception()
        elif args.test == "targeting":
            success = await test_targeting(args.goal)
        elif args.test == "click":
            success = await test_click(args.goal)
        elif args.test == "type":
            success = await test_type(args.text, args.into)
        elif args.test == "press":
            success = await test_press_key(args.key)
        elif args.test == "scroll":
            success = await test_scroll(args.scroll_clicks)
        elif args.test == "all":
            success = await test_all()
        else:
            logger.error(f"Unknown test: {args.test}")
            return 1

        logger.info("\n" + "="*80)
        if success:
            logger.info("✅ TEST COMPLETED SUCCESSFULLY")
        else:
            logger.info("❌ TEST FAILED")
        logger.info("="*80)

        return 0 if success else 1

    except Exception as e:
        logger.error(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
