#!/usr/bin/env python3
"""
Systematic Anti-Bot Detection Test Matrix

Tests different combinations of settings to find what works:
- Headless modes (new, true, false)
- Session rotation (on/off)
- Pre-search delays (0s, 3s, 7s)
- Search engines (DuckDuckGo, Google)
- Human warmup patterns (none, light, full)

Results saved to test_results_TIMESTAMP.json for analysis.
"""
import asyncio
import httpx
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

# Add repo root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ORCH_URL = os.getenv("ORCH_URL", "http://127.0.0.1:8090")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:9000")

# Test queries (simple, non-controversial)
TEST_QUERIES = [
    "weather forecast",
    "python programming tutorial",
    "healthy recipes"
]


class TestConfiguration:
    """Single test configuration"""

    def __init__(
        self,
        headless_mode: str,
        session_rotation: bool,
        pre_search_delay: int,
        search_engine: str,
        warmup_pattern: str,
        query: str
    ):
        self.headless_mode = headless_mode
        self.session_rotation = session_rotation
        self.pre_search_delay = pre_search_delay
        self.search_engine = search_engine
        self.warmup_pattern = warmup_pattern
        self.query = query

    def to_dict(self) -> Dict:
        return {
            "headless_mode": self.headless_mode,
            "session_rotation": self.session_rotation,
            "pre_search_delay": self.pre_search_delay,
            "search_engine": self.search_engine,
            "warmup_pattern": self.warmup_pattern,
            "query": self.query
        }

    def __str__(self) -> str:
        return (
            f"headless={self.headless_mode}, "
            f"rotation={'ON' if self.session_rotation else 'OFF'}, "
            f"delay={self.pre_search_delay}s, "
            f"engine={self.search_engine}, "
            f"warmup={self.warmup_pattern}"
        )


class TestResult:
    """Result from a single test"""

    def __init__(
        self,
        config: TestConfiguration,
        success: bool,
        outcome: str,
        sources_visited: int,
        sources_extracted: int,
        findings_count: int,
        blocked_at_cycle: int = None,
        block_url: str = None,
        error_message: str = None,
        duration_seconds: float = 0.0
    ):
        self.config = config
        self.success = success
        self.outcome = outcome
        self.sources_visited = sources_visited
        self.sources_extracted = sources_extracted
        self.findings_count = findings_count
        self.blocked_at_cycle = blocked_at_cycle
        self.block_url = block_url
        self.error_message = error_message
        self.duration_seconds = duration_seconds

    def to_dict(self) -> Dict:
        return {
            "config": self.config.to_dict(),
            "success": self.success,
            "outcome": self.outcome,
            "sources_visited": self.sources_visited,
            "sources_extracted": self.sources_extracted,
            "findings_count": self.findings_count,
            "blocked_at_cycle": self.blocked_at_cycle,
            "block_url": self.block_url,
            "error_message": self.error_message,
            "duration_seconds": round(self.duration_seconds, 2)
        }


async def set_playwright_headless_mode(mode: str):
    """Update .env PLAYWRIGHT_HEADLESS setting"""
    env_path = Path("/home/henry/pythonprojects/pandaai/.env")
    content = env_path.read_text()

    # Replace PLAYWRIGHT_HEADLESS line
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if line.startswith('PLAYWRIGHT_HEADLESS='):
            lines[i] = f'PLAYWRIGHT_HEADLESS={mode}'
            break

    env_path.write_text('\n'.join(lines))
    print(f"[Config] Set PLAYWRIGHT_HEADLESS={mode}")


async def restart_orchestrator():
    """Restart orchestrator to apply new .env settings"""
    print("[System] Restarting orchestrator...")

    # Kill existing orchestrator
    os.system("ps aux | grep uvicorn | grep orchestrator | grep -v grep | awk '{print $2}' | xargs kill 2>/dev/null")
    await asyncio.sleep(2)

    # Start new orchestrator
    os.system("nohup uvicorn apps.orchestrator.app:app --host 127.0.0.1 --port 8090 >orchestrator.log 2>&1 &")
    await asyncio.sleep(5)

    print("[System] Orchestrator restarted")


async def perform_warmup(session_id: str, pattern: str):
    """Perform human warmup behavior based on pattern"""
    if pattern == "none":
        return

    print(f"[Warmup] Executing pattern: {pattern}")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if pattern in ("light", "full"):
                # Light: Just scroll
                await asyncio.sleep(2.0)
                await client.post(
                    f"{ORCH_URL}/web.scroll",
                    json={"session_id": session_id, "clicks": 3}
                )
                await asyncio.sleep(1.0)

            if pattern == "full":
                # Full: Scroll + multiple delays
                await asyncio.sleep(3.0)
                await client.post(
                    f"{ORCH_URL}/web.scroll",
                    json={"session_id": session_id, "clicks": -2}
                )
                await asyncio.sleep(1.5)

    except Exception as e:
        print(f"[Warmup] Warning: warmup failed (non-critical): {e}")


async def run_test(config: TestConfiguration) -> TestResult:
    """Run a single test with the given configuration"""

    print("\n" + "="*80)
    print(f"TEST: {config}")
    print("="*80)

    start_time = time.time()

    try:
        # Generate session ID based on rotation setting
        if config.session_rotation:
            import hashlib
            session_id = f"test_{hashlib.md5(config.query.encode()).hexdigest()[:8]}"
        else:
            session_id = "default"

        print(f"[Test] Session ID: {session_id}")

        # Apply pre-search delay
        if config.pre_search_delay > 0:
            print(f"[Test] Waiting {config.pre_search_delay}s before search...")
            await asyncio.sleep(config.pre_search_delay)

        # Perform warmup if configured
        await perform_warmup(session_id, config.warmup_pattern)

        # Execute research
        print(f"[Test] Executing research: '{config.query}'")
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                f"{ORCH_URL}/internet.research",
                json={
                    "query": config.query,
                    "research_goal": f"Test search for: {config.query}",
                    "max_cycles": 3,
                    "session_id": session_id
                }
            )

            duration = time.time() - start_time

            if response.status_code == 200:
                result = response.json()

                sources_visited = result.get('sources_visited', 0)
                sources_extracted = result.get('sources_extracted', 0)
                findings_count = len(result.get('findings', []))

                # Determine outcome
                if sources_extracted > 0 and findings_count > 0:
                    outcome = "SUCCESS"
                    success = True
                elif sources_visited > 0 and sources_extracted == 0:
                    outcome = "BLOCKED"
                    success = False
                else:
                    outcome = "NO_RESULTS"
                    success = False

                print(f"[Test] Result: {outcome}")
                print(f"  - Sources visited: {sources_visited}")
                print(f"  - Sources extracted: {sources_extracted}")
                print(f"  - Findings: {findings_count}")

                return TestResult(
                    config=config,
                    success=success,
                    outcome=outcome,
                    sources_visited=sources_visited,
                    sources_extracted=sources_extracted,
                    findings_count=findings_count,
                    duration_seconds=duration
                )
            else:
                print(f"[Test] HTTP Error: {response.status_code}")
                return TestResult(
                    config=config,
                    success=False,
                    outcome="HTTP_ERROR",
                    sources_visited=0,
                    sources_extracted=0,
                    findings_count=0,
                    error_message=f"HTTP {response.status_code}",
                    duration_seconds=duration
                )

    except Exception as e:
        duration = time.time() - start_time
        print(f"[Test] Exception: {e}")
        return TestResult(
            config=config,
            success=False,
            outcome="EXCEPTION",
            sources_visited=0,
            sources_extracted=0,
            findings_count=0,
            error_message=str(e),
            duration_seconds=duration
        )


async def run_test_matrix():
    """Run comprehensive test matrix"""

    print("\n" + "="*80)
    print("ANTI-BOT DETECTION TEST MATRIX")
    print("="*80)
    print("\nThis will test different combinations to find what works.")
    print("Results will be saved to: test_results_TIMESTAMP.json\n")

    # Test matrix parameters
    headless_modes = ["new", "true"]  # Skip "false" for now (requires X server)
    session_rotations = [True, False]
    pre_search_delays = [0, 3, 7]
    search_engines = ["duckduckgo"]  # Add "google" later
    warmup_patterns = ["none", "light", "full"]

    # Use just one query for now to speed up testing
    test_query = TEST_QUERIES[0]

    # Generate all configurations
    configurations = []
    for headless in headless_modes:
        for rotation in session_rotations:
            for delay in pre_search_delays:
                for engine in search_engines:
                    for warmup in warmup_patterns:
                        configurations.append(
                            TestConfiguration(
                                headless_mode=headless,
                                session_rotation=rotation,
                                pre_search_delay=delay,
                                search_engine=engine,
                                warmup_pattern=warmup,
                                query=test_query
                            )
                        )

    print(f"Total configurations to test: {len(configurations)}\n")

    results: List[TestResult] = []
    current_headless_mode = None

    for i, config in enumerate(configurations, 1):
        print(f"\n[Progress] Test {i}/{len(configurations)}")

        # Only restart orchestrator when headless mode changes
        if config.headless_mode != current_headless_mode:
            await set_playwright_headless_mode(config.headless_mode)
            await restart_orchestrator()
            current_headless_mode = config.headless_mode

        # Run test
        result = await run_test(config)
        results.append(result)

        # Cooldown between tests
        cooldown = 5
        print(f"[Progress] Cooldown {cooldown}s before next test...")
        await asyncio.sleep(cooldown)

    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = f"test_results_{timestamp}.json"

    results_data = {
        "timestamp": timestamp,
        "total_tests": len(results),
        "results": [r.to_dict() for r in results]
    }

    with open(results_file, 'w') as f:
        json.dump(results_data, f, indent=2)

    print("\n" + "="*80)
    print("TEST MATRIX COMPLETE")
    print("="*80)

    # Summary
    successes = [r for r in results if r.success]
    blocks = [r for r in results if r.outcome == "BLOCKED"]

    print(f"\n📊 Summary:")
    print(f"  Total tests: {len(results)}")
    print(f"  Successes: {len(successes)} ({len(successes)/len(results)*100:.1f}%)")
    print(f"  Blocks: {len(blocks)} ({len(blocks)/len(results)*100:.1f}%)")
    print(f"\n💾 Results saved to: {results_file}")

    # Show winning configurations
    if successes:
        print(f"\n✅ WINNING CONFIGURATIONS:")
        for result in successes:
            print(f"  - {result.config}")
            print(f"    → {result.sources_extracted} sources extracted, {result.findings_count} findings")
    else:
        print(f"\n❌ No successful configurations found")
        print(f"   All tests were blocked or failed")

    print()
    return results


async def main():
    results = await run_test_matrix()

    # Optional: analyze results
    print("\n" + "="*80)
    print("DETAILED ANALYSIS")
    print("="*80)

    # Group by outcome
    outcomes = {}
    for result in results:
        outcome = result.outcome
        if outcome not in outcomes:
            outcomes[outcome] = []
        outcomes[outcome].append(result)

    print(f"\n📈 Outcomes:")
    for outcome, results_list in sorted(outcomes.items()):
        print(f"  {outcome}: {len(results_list)} tests")

    # Analyze patterns
    print(f"\n🔍 Pattern Analysis:")

    # Does headless mode matter?
    headless_success = {}
    for result in results:
        mode = result.config.headless_mode
        if mode not in headless_success:
            headless_success[mode] = {"success": 0, "total": 0}
        headless_success[mode]["total"] += 1
        if result.success:
            headless_success[mode]["success"] += 1

    print(f"\n  Headless Mode Impact:")
    for mode, stats in headless_success.items():
        rate = stats["success"] / stats["total"] * 100 if stats["total"] > 0 else 0
        print(f"    {mode}: {stats['success']}/{stats['total']} ({rate:.1f}%)")

    # Does session rotation matter?
    rotation_success = {True: {"success": 0, "total": 0}, False: {"success": 0, "total": 0}}
    for result in results:
        rotation = result.config.session_rotation
        rotation_success[rotation]["total"] += 1
        if result.success:
            rotation_success[rotation]["success"] += 1

    print(f"\n  Session Rotation Impact:")
    for rotation, stats in rotation_success.items():
        rate = stats["success"] / stats["total"] * 100 if stats["total"] > 0 else 0
        label = "ON" if rotation else "OFF"
        print(f"    {label}: {stats['success']}/{stats['total']} ({rate:.1f}%)")

    # Does delay matter?
    delay_success = {}
    for result in results:
        delay = result.config.pre_search_delay
        if delay not in delay_success:
            delay_success[delay] = {"success": 0, "total": 0}
        delay_success[delay]["total"] += 1
        if result.success:
            delay_success[delay]["success"] += 1

    print(f"\n  Pre-Search Delay Impact:")
    for delay, stats in sorted(delay_success.items()):
        rate = stats["success"] / stats["total"] * 100 if stats["total"] > 0 else 0
        print(f"    {delay}s: {stats['success']}/{stats['total']} ({rate:.1f}%)")

    # Does warmup matter?
    warmup_success = {}
    for result in results:
        warmup = result.config.warmup_pattern
        if warmup not in warmup_success:
            warmup_success[warmup] = {"success": 0, "total": 0}
        warmup_success[warmup]["total"] += 1
        if result.success:
            warmup_success[warmup]["success"] += 1

    print(f"\n  Warmup Pattern Impact:")
    for warmup, stats in warmup_success.items():
        rate = stats["success"] / stats["total"] * 100 if stats["total"] > 0 else 0
        print(f"    {warmup}: {stats['success']}/{stats['total']} ({rate:.1f}%)")

    print()


if __name__ == "__main__":
    asyncio.run(main())
