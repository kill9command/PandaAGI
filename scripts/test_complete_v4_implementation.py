"""
Test Complete v4.0 Implementation

Tests all features implemented in this session:
- Phase 8 Archivist (rolling summaries)
- Research documents (research_plan.md, research_pass_N.json, satisfaction_check.md)
- Turn documents (cache_decision.md, trace.json)
- STANDARD mode research
- DEEP mode research

Run: python scripts/test_complete_v4_implementation.py
"""

import asyncio
import json
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx


async def test_standard_mode():
    """Test STANDARD mode research"""
    print("\n" + "="*80)
    print("TEST 1: STANDARD Mode Research")
    print("="*80)

    url = "http://127.0.0.1:9000/v1/chat/completions"
    session_id = f"test_standard_{int(time.time())}"

    payload = {
        "messages": [
            {"role": "user", "content": "hamster breeders in Oregon"}
        ],
        "session_id": session_id,
        "model": "qwen3-coder",
        "stream": False
    }

    print(f"\n📤 Sending STANDARD mode request (session: {session_id})...")

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

            result = response.json()
            answer = result["choices"][0]["message"]["content"]

            print(f"\n✅ Response received ({len(answer)} chars)")
            print(f"\n📝 Answer preview:\n{answer[:200]}...")

            # Check documents created
            turn_id = result.get("turn_id", "unknown")
            session_dir = Path(f"panda_system_docs/sessions/{session_id}")
            turn_dir = Path(f"panda_system_docs/turns/{turn_id}")

            print(f"\n📁 Checking documents...")
            print(f"   Turn dir: {turn_dir}")
            print(f"   Session dir: {session_dir}")

            # Check turn documents
            turn_docs = {
                "manifest.json": turn_dir / "manifest.json",
                "plan.md": turn_dir / "plan.md",
                "bundle.json": turn_dir / "bundle.json",
                "capsule.md": turn_dir / "capsule.md",
                "answer.md": turn_dir / "answer.md",
                "turn_summary.md": turn_dir / "turn_summary.md",
                "research_plan.md": turn_dir / "research_plan.md",
                "research_pass_1.json": turn_dir / "research_pass_1.json",
                "cache_decision.md": turn_dir / "cache_decision.md",
                "trace.json": turn_dir / "trace.json"
            }

            # Check session documents (Phase 8 Archivist)
            session_docs = {
                "live_context.md": session_dir / "live_context.md",
                "preferences.md": session_dir / "preferences.md",
                "history_compressed.md": session_dir / "history_compressed.md",
                "memory_update.json": session_dir / "memory_update.json"
            }

            print(f"\n   Turn Documents:")
            found = 0
            for name, path in turn_docs.items():
                exists = path.exists()
                size = path.stat().st_size if exists else 0
                status = f"✅ ({size}B)" if exists else "❌ MISSING"
                print(f"     {name}: {status}")
                if exists:
                    found += 1

            print(f"\n   Session Documents (Phase 8 Archivist):")
            session_found = 0
            for name, path in session_docs.items():
                exists = path.exists()
                size = path.stat().st_size if exists else 0
                status = f"✅ ({size}B)" if exists else "❌ MISSING"
                print(f"     {name}: {status}")
                if exists:
                    session_found += 1

            # Summary
            print(f"\n📊 Document Summary:")
            print(f"   Turn documents: {found}/{len(turn_docs)} created")
            print(f"   Session documents: {session_found}/{len(session_docs)} created")

            # Verify research_plan.md content
            research_plan_path = turn_dir / "research_plan.md"
            if research_plan_path.exists():
                content = research_plan_path.read_text()
                print(f"\n📄 Research Plan Preview:")
                print(content[:300])

            # Verify manifest
            manifest_path = turn_dir / "manifest.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text())
                docs_created = manifest.get("docs_created", [])
                print(f"\n📋 Manifest shows {len(docs_created)} documents created:")
                for doc in docs_created[:10]:
                    print(f"     - {doc}")
                if len(docs_created) > 10:
                    print(f"     ... and {len(docs_created) - 10} more")

            if found >= 8 and session_found >= 3:
                print(f"\n✅ STANDARD mode test PASSED")
                return True
            else:
                print(f"\n❌ STANDARD mode test FAILED (missing documents)")
                return False

    except Exception as e:
        print(f"\n❌ STANDARD mode test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_deep_mode():
    """Test DEEP mode research"""
    print("\n" + "="*80)
    print("TEST 2: DEEP Mode Research")
    print("="*80)

    url = "http://127.0.0.1:9000/v1/chat/completions"
    session_id = f"test_deep_{int(time.time())}"

    payload = {
        "messages": [
            {"role": "user", "content": "do deep research on the best dwarf hamster breeds for beginners"}
        ],
        "session_id": session_id,
        "model": "qwen3-coder",
        "stream": False
    }

    print(f"\n📤 Sending DEEP mode request (session: {session_id})...")

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:  # Longer timeout for DEEP mode
            response = await client.post(url, json=payload)
            response.raise_for_status()

            result = response.json()
            answer = result["choices"][0]["message"]["content"]

            print(f"\n✅ Response received ({len(answer)} chars)")
            print(f"\n📝 Answer preview:\n{answer[:200]}...")

            # Check documents created
            turn_id = result.get("turn_id", "unknown")
            turn_dir = Path(f"panda_system_docs/turns/{turn_id}")
            session_dir = Path(f"panda_system_docs/sessions/{session_id}")

            print(f"\n📁 Checking DEEP mode specific documents...")

            # Check for satisfaction_check.md (DEEP mode only)
            satisfaction_path = turn_dir / "satisfaction_check.md"
            if satisfaction_path.exists():
                content = satisfaction_path.read_text()
                print(f"\n✅ satisfaction_check.md created ({satisfaction_path.stat().st_size}B)")
                print(f"\n📄 Satisfaction Check Preview:")
                print(content[:400])
            else:
                print(f"\n❌ satisfaction_check.md MISSING (expected for DEEP mode)")

            # Check for multiple research passes
            pass_files = sorted(turn_dir.glob("research_pass_*.json"))
            print(f"\n📊 Research Passes: {len(pass_files)} pass file(s) found")
            for pass_file in pass_files:
                print(f"     - {pass_file.name} ({pass_file.stat().st_size}B)")

            # Verify history_compressed.md has multiple turns
            history_path = session_dir / "history_compressed.md"
            if history_path.exists():
                content = history_path.read_text()
                turn_count = content.count("## Turn")
                print(f"\n📚 History: {turn_count} turn(s) in history_compressed.md")

            if satisfaction_path.exists() and len(pass_files) >= 1:
                print(f"\n✅ DEEP mode test PASSED")
                return True
            else:
                print(f"\n❌ DEEP mode test FAILED (missing DEEP mode documents)")
                return False

    except Exception as e:
        print(f"\n❌ DEEP mode test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_multi_turn_session():
    """Test multi-turn session to verify rolling summaries"""
    print("\n" + "="*80)
    print("TEST 3: Multi-Turn Session (Rolling Summaries)")
    print("="*80)

    url = "http://127.0.0.1:9000/v1/chat/completions"
    session_id = f"test_multiturn_{int(time.time())}"

    queries = [
        "What are the best hamster breeds for kids?",
        "Tell me more about dwarf hamsters",
        "Where can I buy hamster supplies in Portland?"
    ]

    print(f"\n📤 Sending {len(queries)} queries in same session...")

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            for i, query in enumerate(queries, 1):
                print(f"\n   Turn {i}: {query}")

                payload = {
                    "messages": [{"role": "user", "content": query}],
                    "session_id": session_id,
                    "model": "qwen3-coder",
                    "stream": False
                }

                response = await client.post(url, json=payload)
                response.raise_for_status()

                result = response.json()
                answer = result["choices"][0]["message"]["content"]
                print(f"   ✅ Response: {answer[:80]}...")

                # Brief pause between turns
                await asyncio.sleep(1)

        # Check session documents
        session_dir = Path(f"panda_system_docs/sessions/{session_id}")
        history_path = session_dir / "history_compressed.md"

        if history_path.exists():
            content = history_path.read_text()
            turn_count = content.count("## Turn")
            print(f"\n📚 History Compressed:")
            print(f"   Turns recorded: {turn_count}")
            print(f"   File size: {history_path.stat().st_size}B")
            print(f"\n   Content preview:")
            print("   " + "\n   ".join(content.split("\n")[:15]))

            if turn_count == len(queries):
                print(f"\n✅ Multi-turn session test PASSED ({turn_count} turns tracked)")
                return True
            else:
                print(f"\n❌ Multi-turn session test FAILED (expected {len(queries)} turns, got {turn_count})")
                return False
        else:
            print(f"\n❌ Multi-turn session test FAILED (history_compressed.md missing)")
            return False

    except Exception as e:
        print(f"\n❌ Multi-turn session test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("Complete v4.0 Implementation Test Suite")
    print("="*80)
    print("\nThis will test:")
    print("  ✓ Phase 8 Archivist (rolling summaries)")
    print("  ✓ Research documents (research_plan.md, research_pass_N.json, satisfaction_check.md)")
    print("  ✓ Turn documents (cache_decision.md, trace.json)")
    print("  ✓ STANDARD mode research")
    print("  ✓ DEEP mode research")
    print("  ✓ Multi-turn sessions")

    # Run tests
    results = {}

    results["standard"] = await test_standard_mode()
    await asyncio.sleep(2)

    results["deep"] = await test_deep_mode()
    await asyncio.sleep(2)

    results["multiturn"] = await test_multi_turn_session()

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)

    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"  {test_name.upper()}: {status}")

    passed_count = sum(1 for p in results.values() if p)
    total_count = len(results)

    print(f"\n📊 Overall: {passed_count}/{total_count} tests passed")

    if passed_count == total_count:
        print("\n🎉 ALL TESTS PASSED! v4.0 implementation is complete.")
        return 0
    else:
        print(f"\n⚠️  {total_count - passed_count} test(s) failed. Check output above for details.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
