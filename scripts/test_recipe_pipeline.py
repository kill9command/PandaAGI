#!/usr/bin/env python3
"""
Test Recipe Pipeline - Phase 0-1 Integration Test

Tests the complete v4.0 document-driven flow:
1. Create turn directory
2. Write user query
3. Load recipe
4. Build doc pack
5. Verify token budgets enforced
6. Generate prompt

Author: v4.0 Migration
Date: 2025-11-16
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from libs.gateway.persistence.turn_manager import setup_turn, TurnDirectory
from libs.gateway.llm.recipe_loader import load_recipe
from libs.gateway.context.doc_pack_builder import DocPackBuilder
from libs.gateway.context.doc_writers import write_unified_context_md, write_intent_json

# Mock unified context for testing
class MockUnifiedContext:
    def __init__(self):
        self.living_context = type('obj', (object,), {'content': 'User is shopping for hamster supplies. Current topic: Syrian hamster breeders.'})()
        self.long_term_memories = [
            type('obj', (object,), {'content': 'User prefers ethical breeders with health guarantees', 'confidence': 0.9})(),
            type('obj', (object,), {'content': 'User located in California', 'confidence': 0.85})()
        ]
        self.recent_claims = []
        self.discovered_facts = []
        self.total_items = 3
        self.total_estimated_tokens = 150
        self.gather_time_ms = 12.5


def test_phase0_turn_setup():
    """Test Phase 0: Turn initialization"""
    print("\n" + "="*80)
    print("PHASE 0: Turn Initialization")
    print("="*80)

    # Setup turn
    turn_dir, manifest = setup_turn(
        trace_id="test-trace-001",
        session_id="test-session-hamster",
        mode="chat",
        user_query="can you find some syrian hamster breeders online for me?"
    )

    print(f"\n✅ Turn directory created: {turn_dir.path}")
    print(f"   Turn ID: {turn_dir.turn_id}")
    print(f"   Session ID: {turn_dir.session_id}")
    print(f"   Mode: {turn_dir.mode}")

    print(f"\n✅ Manifest initialized:")
    print(f"   Docs created: {manifest['docs_created']}")
    print(f"   Status: {manifest['status']}")

    return turn_dir, manifest


def test_phase1_context_gathering(turn_dir):
    """Test Phase 1: Context gathering (simulated)"""
    print("\n" + "="*80)
    print("PHASE 1: Context Gathering (Simulated)")
    print("="*80)

    # Write unified context
    ctx = MockUnifiedContext()
    path = write_unified_context_md(turn_dir, ctx)
    print(f"\n✅ Wrote unified_context.md ({ctx.total_estimated_tokens} tokens)")
    print(f"   Path: {path}")

    # Write intent
    intent_path = write_intent_json(turn_dir, "transactional", "commerce", 0.92)
    print(f"\n✅ Wrote intent.json (intent=transactional, conf=0.92)")
    print(f"   Path: {intent_path}")

    return ctx


def test_phase2_recipe_loading():
    """Test Phase 2: Recipe loading"""
    print("\n" + "="*80)
    print("PHASE 2: Recipe Loading")
    print("="*80)

    # Load recipe
    recipe = load_recipe("guide_strategic_chat")

    print(f"\n✅ Loaded recipe: {recipe.name}")
    print(f"   Role: {recipe.role}")
    print(f"   Phase: {recipe.phase}")
    print(f"   Mode: {recipe.mode}")
    print(f"\n   Token Budget:")
    print(f"     Total: {recipe.token_budget.total}")
    print(f"     Prompt: {recipe.token_budget.prompt}")
    print(f"     Input docs: {recipe.token_budget.input_docs}")
    print(f"     Output: {recipe.token_budget.output}")
    print(f"     Buffer: {recipe.token_budget.buffer}")

    print(f"\n   Prompt Fragments ({len(recipe.prompt_fragments)}):")
    for frag in recipe.prompt_fragments:
        print(f"     - {frag}")

    print(f"\n   Input Docs ({len(recipe.input_docs)}):")
    for doc_spec in recipe.input_docs:
        optional = " (optional)" if doc_spec.optional else ""
        max_tok = f" (max {doc_spec.max_tokens} tokens)" if doc_spec.max_tokens else ""
        print(f"     - {doc_spec.path}{optional}{max_tok}")

    print(f"\n   Output Docs ({len(recipe.output_docs)}):")
    for doc in recipe.output_docs:
        print(f"     - {doc}")

    return recipe


def test_phase2_doc_pack_building(recipe, turn_dir):
    """Test Phase 2: Doc pack building"""
    print("\n" + "="*80)
    print("PHASE 2: Doc Pack Building")
    print("="*80)

    # Build doc pack
    builder = DocPackBuilder()
    pack = builder.build(recipe, turn_dir)

    print(f"\n✅ Built doc pack: {pack.recipe_name}")
    print(f"   Budget: {pack.budget} tokens")
    print(f"   Used: {pack.token_count} tokens ({pack.token_count/pack.budget*100:.1f}%)")
    print(f"   Remaining: {pack.remaining_budget} tokens")

    summary = pack.get_summary()
    print(f"\n   Breakdown:")
    print(f"     Prompt tokens: {summary['prompt_tokens']}")
    print(f"     Doc tokens: {summary['doc_tokens']}")
    print(f"     Output reserved: {summary['output_reserved']}")
    print(f"     Items: {summary['items']}")
    print(f"     Trimmed items: {summary['trimmed_items']}")

    if pack.trimming_log:
        print(f"\n   Trimming Log:")
        for log_entry in pack.trimming_log:
            print(f"     ⚠️  {log_entry}")

    # Verify budget not exceeded
    assert pack.token_count <= pack.budget, f"BUDGET EXCEEDED: {pack.token_count} > {pack.budget}"
    print(f"\n   ✅ Budget constraint satisfied: {pack.token_count} <= {pack.budget}")

    return pack


def test_phase2_prompt_generation(pack):
    """Test Phase 2: Final prompt generation"""
    print("\n" + "="*80)
    print("PHASE 2: Prompt Generation")
    print("="*80)

    # Generate final prompt
    prompt = pack.as_prompt()

    print(f"\n✅ Generated prompt:")
    print(f"   Total length: {len(prompt)} characters")
    print(f"   First 500 chars:")
    print("   " + "-"*76)
    print("   " + prompt[:500].replace("\n", "\n   "))
    print("   " + "-"*76)

    # Show last 300 chars to see input docs
    print(f"\n   Last 300 chars:")
    print("   " + "-"*76)
    print("   " + prompt[-300:].replace("\n", "\n   "))
    print("   " + "-"*76)

    return prompt


def main():
    """Run complete Phase 0-1 integration test"""
    print("\n" + "="*80)
    print("RECIPE PIPELINE INTEGRATION TEST")
    print("Testing: Turn Setup → Context Gathering → Recipe Loading → Doc Pack Building")
    print("="*80)

    try:
        # Phase 0: Turn setup
        turn_dir, manifest = test_phase0_turn_setup()

        # Phase 1: Context gathering (simulated)
        ctx = test_phase1_context_gathering(turn_dir)

        # Phase 2: Recipe loading
        recipe = test_phase2_recipe_loading()

        # Phase 2: Doc pack building
        pack = test_phase2_doc_pack_building(recipe, turn_dir)

        # Phase 2: Prompt generation
        prompt = test_phase2_prompt_generation(pack)

        # Final summary
        print("\n" + "="*80)
        print("✅ ALL TESTS PASSED")
        print("="*80)
        print(f"\nPhase 0-1 Integration Summary:")
        print(f"  Turn ID: {turn_dir.turn_id}")
        print(f"  Docs created: {len(turn_dir.list_docs())}")
        print(f"  Recipe: {recipe.name}")
        print(f"  Token budget: {pack.token_count}/{pack.budget} ({pack.token_count/pack.budget*100:.1f}%)")
        print(f"  Prompt length: {len(prompt)} chars")
        print(f"\n🎉 v4.0 Document-Driven Architecture - Phase 0-1 VALIDATED")

    except Exception as e:
        print("\n" + "="*80)
        print("❌ TEST FAILED")
        print("="*80)
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
