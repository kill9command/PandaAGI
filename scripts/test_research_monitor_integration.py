"""
Test script to verify research monitor event emission

Tests that all research events are properly emitted:
- search_started
- candidate_checking
- candidate_accepted/rejected
- progress
- phase_started/complete (deep mode)
- research_complete
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apps.services.orchestrator.research_event_emitter import ResearchEventEmitter
from apps.services.orchestrator.internet_research_mcp import adaptive_research


class MockGatewayCallback:
    """Mock gateway callback to capture emitted events"""

    def __init__(self):
        self.events = []

    async def __call__(self, event):
        """Capture event"""
        self.events.append(event)
        print(f"\n[EVENT] {event['type']}: {event['data']}")


async def test_standard_mode():
    """Test standard research mode event emission"""
    print("\n" + "="*80)
    print("TEST 1: Standard Research Mode")
    print("="*80)

    # Create mock callback
    callback = MockGatewayCallback()

    # Create event emitter with callback
    emitter = ResearchEventEmitter(
        session_id="test-standard",
        gateway_callback=callback
    )

    # Run standard research (canonical entry point)
    result = await adaptive_research(
        query="hamster care basics",
        research_goal="Find comprehensive hamster care information",
        mode="standard",
        session_id="test-standard",
        human_assist_allowed=False,
        event_emitter=emitter,
        query_type="informational"
    )

    # Wait for async event emissions to complete
    await asyncio.sleep(0.5)

    # Verify events
    event_types = [e['type'] for e in callback.events]
    print(f"\n[RESULTS] Total events emitted: {len(callback.events)}")
    print(f"[RESULTS] Event types: {event_types}")

    # Check required events
    required_events = ['search_started', 'candidate_checking', 'progress', 'research_complete']
    missing_events = [e for e in required_events if e not in event_types]

    if missing_events:
        print(f"\n❌ FAIL: Missing required events: {missing_events}")
        return False

    # Check that we have acceptance or rejection events
    has_acceptance = 'candidate_accepted' in event_types or 'candidate_rejected' in event_types
    if not has_acceptance:
        print(f"\n❌ FAIL: No candidate acceptance/rejection events")
        return False

    print(f"\n✅ PASS: Standard mode emits all required events")
    print(f"[MODE] {result.get('mode')}, [STRATEGY] {result.get('strategy_used')}")
    print(f"[RESULTS] {len(result.get('results', {}).get('sources', []))} sources found")
    return True


async def test_deep_mode():
    """Test deep research mode event emission (includes phase events)"""
    print("\n" + "="*80)
    print("TEST 2: Deep Research Mode")
    print("="*80)

    # Create mock callback
    callback = MockGatewayCallback()

    # Create event emitter with callback
    emitter = ResearchEventEmitter(
        session_id="test-deep",
        gateway_callback=callback
    )

    # Run deep research (canonical entry point)
    result = await adaptive_research(
        query="Syrian hamster breeding",
        research_goal="Find breeding information and best practices",
        mode="deep",
        session_id="test-deep",
        human_assist_allowed=False,
        event_emitter=emitter,
        query_type="informational"
    )

    # Wait for async event emissions to complete
    await asyncio.sleep(0.5)

    # Verify events
    event_types = [e['type'] for e in callback.events]
    print(f"\n[RESULTS] Total events emitted: {len(callback.events)}")
    print(f"[RESULTS] Event types: {event_types}")

    # Check required events for deep mode
    required_events = [
        'search_started',
        'phase_started',
        'phase_complete',
        'research_complete'
    ]
    missing_events = [e for e in required_events if e not in event_types]

    if missing_events:
        print(f"\n❌ FAIL: Missing required events: {missing_events}")
        return False

    # Check that we have both phase 1 and phase 2
    phase_events = [e for e in callback.events if e['type'] in ['phase_started', 'phase_complete']]
    phase1_started = any(e['data'].get('phase') == 'phase1' for e in phase_events if e['type'] == 'phase_started')
    phase2_started = any(e['data'].get('phase') == 'phase2' for e in phase_events if e['type'] == 'phase_started')

    if not (phase1_started and phase2_started):
        print(f"\n❌ FAIL: Missing phase 1 or phase 2 events")
        return False

    print(f"\n✅ PASS: Deep mode emits all required events including phases")
    print(f"[MODE] {result.get('mode')}, [STRATEGY] {result.get('strategy_used')}, [PASSES] {result.get('passes')}")
    print(f"[RESULTS] {len(result.get('results', {}).get('sources', []))} sources found")
    return True


async def test_event_no_callback():
    """Test that research works without event emitter (backward compatibility)"""
    print("\n" + "="*80)
    print("TEST 3: Backward Compatibility (No Event Emitter)")
    print("="*80)

    # Run without event emitter (canonical entry point)
    result = await adaptive_research(
        query="hamster diet",
        research_goal="Find dietary information",
        mode="standard",
        session_id="test-no-emitter",
        human_assist_allowed=False,
        event_emitter=None,  # No emitter
        query_type="informational"
    )

    if result and result.get('results'):
        print(f"\n✅ PASS: Research works without event emitter")
        print(f"[MODE] {result.get('mode')}, [STRATEGY] {result.get('strategy_used')}")
        sources = result.get('results', {}).get('sources', [])
        print(f"[RESULTS] {len(sources)} sources found")
        return True
    else:
        print(f"\n❌ FAIL: Research failed without event emitter")
        return False


async def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("RESEARCH MONITOR INTEGRATION TEST")
    print("="*80)

    results = []

    # Test 1: Standard mode
    try:
        results.append(await test_standard_mode())
    except Exception as e:
        print(f"\n❌ FAIL: Standard mode test crashed: {e}")
        import traceback
        traceback.print_exc()
        results.append(False)

    # Test 2: Deep mode
    try:
        results.append(await test_deep_mode())
    except Exception as e:
        print(f"\n❌ FAIL: Deep mode test crashed: {e}")
        import traceback
        traceback.print_exc()
        results.append(False)

    # Test 3: Backward compatibility
    try:
        results.append(await test_event_no_callback())
    except Exception as e:
        print(f"\n❌ FAIL: Backward compatibility test crashed: {e}")
        import traceback
        traceback.print_exc()
        results.append(False)

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    passed = sum(results)
    total = len(results)
    print(f"\nPassed: {passed}/{total}")

    if passed == total:
        print("\n✅ ALL TESTS PASSED - Research monitor integration is solid!")
        return 0
    else:
        print(f"\n❌ {total - passed} TEST(S) FAILED")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
