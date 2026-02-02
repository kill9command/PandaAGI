#!/usr/bin/env python3
"""
Test WebSocket Event Bridge Integration

This script tests the complete event flow:
1. UI WebSocket client connects to Gateway
2. Gateway creates event callback
3. Gateway calls Orchestrator research function directly
4. Orchestrator emits events during execution
5. Gateway broadcasts events via WebSocket
6. UI client receives and displays events

Expected Flow:
User → Gateway → orchestrator_research() → event_callback → WebSocket → UI
"""

import asyncio
import json
import websockets
from datetime import datetime

async def test_websocket_events():
    """Test WebSocket event streaming."""
    session_id = "test-websocket-bridge"
    ws_url = f"ws://127.0.0.1:9000/ws/research/{session_id}"

    print(f"=== WebSocket Event Bridge Test ===")
    print(f"Time: {datetime.now().isoformat()}")
    print(f"Session: {session_id}")
    print(f"WebSocket: {ws_url}")
    print()

    events_received = []

    try:
        # Connect to WebSocket
        print("[1] Connecting to WebSocket...")
        async with websockets.connect(ws_url) as websocket:
            print("✓ WebSocket connected")
            print()

            # Trigger research via API
            print("[2] Triggering research query...")
            import httpx
            async with httpx.AsyncClient(timeout=120.0) as client:
                # Start research in background
                research_task = asyncio.create_task(
                    client.post(
                        "http://127.0.0.1:9000/v1/chat/completions",
                        json={
                            "model": "qwen3-coder",
                            "messages": [
                                {"role": "user", "content": "find Syrian hamster for sale"}
                            ],
                            "profile_id": session_id,
                            "session_id": session_id
                        }
                    )
                )

                print("✓ Research started")
                print()

                # Listen for WebSocket events
                print("[3] Listening for events...")
                print()

                # Set timeout for event listening (60 seconds)
                event_timeout = 60
                start_time = asyncio.get_event_loop().time()

                try:
                    while asyncio.get_event_loop().time() - start_time < event_timeout:
                        try:
                            # Wait for message with short timeout
                            message = await asyncio.wait_for(
                                websocket.recv(),
                                timeout=2.0
                            )

                            # Parse event
                            event = json.loads(message)
                            events_received.append(event)

                            # Display event
                            event_type = event.get("type", "unknown")
                            timestamp = event.get("timestamp", "")

                            print(f"[Event {len(events_received)}] {event_type}")

                            # Show relevant data for each event type
                            if event_type == "search_started":
                                data = event.get("data", {})
                                print(f"  Query: {data.get('query')}")
                                print(f"  Max candidates: {data.get('max_candidates')}")

                            elif event_type == "candidate_checking":
                                data = event.get("data", {})
                                print(f"  [{data.get('index')}/{data.get('total')}] {data.get('url')}")
                                print(f"  Title: {data.get('title', 'N/A')[:60]}...")

                            elif event_type == "intervention_needed":
                                data = event.get("data", {})
                                print(f"  🔒 {data.get('blocker_type')}")
                                print(f"  URL: {data.get('url')}")

                            elif event_type == "intervention_resolved":
                                data = event.get("data", {})
                                print(f"  ✓ Resolved: {data.get('success')}")

                            elif event_type == "candidate_accepted":
                                data = event.get("data", {})
                                print(f"  ✓ {data.get('url')}")
                                print(f"  Quality: {data.get('quality_score', 0) * 100:.1f}%")

                            elif event_type == "candidate_rejected":
                                data = event.get("data", {})
                                print(f"  ✗ {data.get('url')}")
                                print(f"  Reason: {data.get('reason')}")

                            elif event_type == "progress":
                                data = event.get("data", {})
                                print(f"  Progress: {data.get('checked')}/{data.get('total')} checked")
                                print(f"  Accepted: {data.get('accepted')}, Rejected: {data.get('rejected')}")
                                print(f"  {data.get('progress_pct', 0):.1f}% complete")

                            elif event_type == "search_complete":
                                data = event.get("data", {})
                                print(f"  ✓ Total accepted: {data.get('total_accepted')}")
                                print(f"  Duration: {data.get('duration_ms', 0) / 1000:.1f}s")

                            elif event_type == "research_complete":
                                data = event.get("data", {})
                                synthesis = data.get("synthesis", {})
                                print(f"  ✓ Research complete!")
                                print(f"  Sources: {len(synthesis.get('sources', []))}")

                            print()

                            # Stop on research_complete
                            if event_type == "research_complete":
                                print("✓ Received research_complete event - stopping")
                                break

                        except asyncio.TimeoutError:
                            # No message in last 2 seconds, check if research finished
                            if research_task.done():
                                print("Research task completed, no more events expected")
                                break
                            continue

                    # Wait for research to complete
                    if not research_task.done():
                        print()
                        print("[4] Waiting for research to complete...")
                        response = await research_task
                        print(f"✓ Research HTTP response: {response.status_code}")

                except Exception as e:
                    print(f"Error during event listening: {e}")
                    if not research_task.done():
                        research_task.cancel()

    except websockets.exceptions.WebSocketException as e:
        print(f"✗ WebSocket error: {e}")
        return False

    except Exception as e:
        print(f"✗ Test error: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Summary
    print()
    print("=== Test Summary ===")
    print(f"Total events received: {len(events_received)}")
    print()

    if events_received:
        print("Event types received:")
        event_types = {}
        for event in events_received:
            event_type = event.get("type", "unknown")
            event_types[event_type] = event_types.get(event_type, 0) + 1

        for event_type, count in event_types.items():
            print(f"  - {event_type}: {count}")
        print()

    # Validation
    expected_events = ["search_started"]
    has_expected = all(
        any(e.get("type") == evt for e in events_received)
        for evt in expected_events
    )

    if has_expected and len(events_received) >= 3:
        print("✓ TEST PASSED: WebSocket event bridge is working!")
        print()
        print("The event flow is complete:")
        print("  Gateway → create_research_event_callback()")
        print("         → orchestrator_research(event_emitter=callback)")
        print("         → Orchestrator emits events")
        print("         → callback() broadcasts to WebSocket")
        print("         → UI client receives events ✓")
        return True
    else:
        print("✗ TEST FAILED: Not enough events received")
        print(f"Expected at least: {expected_events}")
        print(f"Received {len(events_received)} events total")
        return False


if __name__ == "__main__":
    print()
    success = asyncio.run(test_websocket_events())
    print()
    exit(0 if success else 1)
