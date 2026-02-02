#!/usr/bin/env python3
"""
Test All Recipes - Phase 3 Recipe Validation

Tests that all 6 recipes load, validate, and build doc packs correctly:
1. guide_strategic_chat.yaml
2. guide_synthesis_chat.yaml
3. guide_synthesis_code.yaml
4. coordinator_chat.yaml
5. coordinator_code.yaml
6. context_manager.yaml

Author: v4.0 Migration - Phase 3
Date: 2025-11-16
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from libs.gateway.recipe_loader import load_recipe, list_recipes, validate_all_recipes
from libs.gateway.doc_pack_builder import DocPackBuilder
from libs.gateway.turn_manager import create_turn_directory
from libs.gateway.doc_writers import (
    write_markdown_doc,
    write_json_doc
)


def create_test_docs(turn_dir, recipe_name):
    """Create minimal test documents for a recipe"""
    # All recipes need user_query.md
    user_query_path = turn_dir.doc_path("user_query.md")
    write_markdown_doc(
        user_query_path,
        "User Query",
        {"Query": "Test query for recipe validation"},
        {"Turn ID": turn_dir.turn_id}
    )

    # Create unified_context.md (most recipes need this)
    unified_ctx_path = turn_dir.doc_path("unified_context.md")
    write_markdown_doc(
        unified_ctx_path,
        "Unified Context",
        {
            "Session State": "User is testing recipe system",
            "Preferences": "- test_mode: true"
        },
        {"Total Items": "2", "Est. Tokens": "50"}
    )

    # Create session_state.md
    session_state_path = turn_dir.doc_path("session_state.md")
    write_markdown_doc(
        session_state_path,
        "Live Session Context",
        {
            "Current State": "- **Turn Count:** 1",
            "User Preferences": "- **test_mode:** true"
        },
        {"Session ID": "test-session"}
    )

    # Recipe-specific documents
    if "strategic" in recipe_name:
        # Strategic guide doesn't need extra docs (creates ticket.md)
        pass

    elif "synthesis" in recipe_name:
        # Synthesis guide needs capsule.md
        capsule_path = turn_dir.doc_path("capsule.md")
        write_markdown_doc(
            capsule_path,
            "Evidence-Based Claims (Distilled Capsule)",
            {
                "Capsule ID": "test-capsule-001",
                "Claims": "### Claim 1: Test\n- **Statement:** This is a test claim\n- **Confidence:** 0.90"
            }
        )

        if "code" in recipe_name:
            # Code synthesis needs bundle.json
            bundle_path = turn_dir.doc_path("bundle.json")
            write_json_doc(bundle_path, {
                "tool_executions": [
                    {"tool": "file.read", "result": "test content"}
                ]
            })

    elif "coordinator" in recipe_name:
        # Coordinator needs ticket.md
        ticket_path = turn_dir.doc_path("ticket.md")
        write_markdown_doc(
            ticket_path,
            "Task Ticket",
            {
                "User Need": "Test coordinator recipe",
                "Recommended Tools": "- internet.research",
                "Success Criteria": "- Recipe validates"
            }
        )

    elif "context_manager" in recipe_name:
        # Context manager needs bundle.json and ticket.md
        bundle_path = turn_dir.doc_path("bundle.json")
        write_json_doc(bundle_path, {
            "tool_executions": [
                {"tool": "internet.research", "result": {"findings": ["test"]}}
            ]
        })

        ticket_path = turn_dir.doc_path("ticket.md")
        write_markdown_doc(
            ticket_path,
            "Task Ticket",
            {
                "User Need": "Test context manager",
                "Goal": "Validate recipe"
            }
        )


def test_recipe(recipe_name):
    """Test a single recipe"""
    print(f"\n{'='*80}")
    print(f"Testing Recipe: {recipe_name}")
    print(f"{'='*80}")

    try:
        # Step 1: Load recipe
        recipe = load_recipe(recipe_name)
        print(f"\n✅ Step 1: Recipe loaded")
        print(f"   Role: {recipe.role}")
        print(f"   Phase: {recipe.phase}")
        print(f"   Mode: {recipe.mode}")
        print(f"   Token Budget: {recipe.token_budget.total}")

        # Step 2: Validate recipe
        recipe.validate()
        print(f"\n✅ Step 2: Recipe validated")
        print(f"   Prompt fragments: {len(recipe.prompt_fragments)}")
        print(f"   Input docs: {len(recipe.input_docs)}")
        print(f"   Output docs: {len(recipe.output_docs)}")

        # Step 3: Create turn directory with test docs
        turn_dir = create_turn_directory(
            trace_id=f"test-{recipe_name}",
            session_id="test-session-recipes",
            mode=recipe.mode or "chat"
        )
        create_test_docs(turn_dir, recipe_name)
        print(f"\n✅ Step 3: Created test documents")
        print(f"   Turn directory: {turn_dir.path}")
        print(f"   Docs created: {len(turn_dir.list_docs())}")

        # Step 4: Build doc pack
        builder = DocPackBuilder()
        pack = builder.build(recipe, turn_dir)
        print(f"\n✅ Step 4: Built doc pack")
        print(f"   Budget: {pack.budget} tokens")
        print(f"   Used: {pack.token_count} tokens ({pack.token_count/pack.budget*100:.1f}%)")
        print(f"   Remaining: {pack.remaining_budget} tokens")

        summary = pack.get_summary()
        print(f"\n   Breakdown:")
        print(f"     Prompt tokens: {summary['prompt_tokens']}")
        print(f"     Doc tokens: {summary['doc_tokens']}")
        print(f"     Output reserved: {summary['output_reserved']}")
        print(f"     Trimmed items: {summary['trimmed_items']}")

        if pack.trimming_log:
            print(f"\n   Trimming Log:")
            for log_entry in pack.trimming_log:
                print(f"     ⚠️  {log_entry}")

        # Step 5: Verify budget constraint
        assert pack.token_count <= pack.budget, f"Budget exceeded: {pack.token_count} > {pack.budget}"
        print(f"\n   ✅ Budget constraint satisfied: {pack.token_count} <= {pack.budget}")

        # Step 6: Generate prompt (smoke test)
        prompt = pack.as_prompt()
        print(f"\n✅ Step 5: Generated prompt")
        print(f"   Length: {len(prompt)} chars")

        return True

    except Exception as e:
        print(f"\n❌ Recipe test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Test all recipes"""
    print("\n" + "="*80)
    print("RECIPE VALIDATION TEST - All 6 Recipes")
    print("="*80)

    # Get all recipes
    all_recipes = list_recipes()
    print(f"\nFound {len(all_recipes)} recipes:")
    for recipe_name in sorted(all_recipes):
        print(f"  - {recipe_name}")

    # Expected recipes
    expected_recipes = [
        "guide_strategic_chat",
        "guide_synthesis_chat",
        "guide_synthesis_code",
        "coordinator_chat",
        "coordinator_code",
        "context_manager"
    ]

    print(f"\nExpected {len(expected_recipes)} recipes for v4.0 flow")

    # Validate all recipes first
    print(f"\n{'='*80}")
    print("Step 1: Validating All Recipes")
    print(f"{'='*80}")
    validation_results = validate_all_recipes()
    for recipe_name, is_valid in sorted(validation_results.items()):
        status = "✅" if is_valid else "❌"
        print(f"{status} {recipe_name}")

    if not all(validation_results.values()):
        print(f"\n❌ Some recipes failed validation!")
        sys.exit(1)

    print(f"\n✅ All recipes passed initial validation")

    # Test each recipe with doc pack building
    print(f"\n{'='*80}")
    print("Step 2: Testing Doc Pack Building for Each Recipe")
    print(f"{'='*80}")

    results = {}
    for recipe_name in expected_recipes:
        if recipe_name in all_recipes:
            results[recipe_name] = test_recipe(recipe_name)
        else:
            print(f"\n⚠️  Recipe not found: {recipe_name}")
            results[recipe_name] = False

    # Summary
    print(f"\n{'='*80}")
    print("TEST SUMMARY")
    print(f"{'='*80}")

    passed_count = sum(1 for v in results.values() if v)
    total = len(results)

    print(f"\nResults: {passed_count}/{total} recipes passed")
    for recipe_name, recipe_passed in sorted(results.items()):
        status = "✅" if recipe_passed else "❌"
        print(f"{status} {recipe_name}")

    if passed_count == total:
        print(f"\n{'='*80}")
        print("🎉 ALL RECIPES VALIDATED - Phase 3 Complete!")
        print(f"{'='*80}")
        print(f"\nRecipe System Summary:")
        print(f"  - 6 recipes created (Guide x3, Coordinator x2, Context Manager x1)")
        print(f"  - All recipes load and validate correctly")
        print(f"  - All recipes build doc packs within token budgets")
        print(f"  - Token budgets measured and enforced")
        print(f"\n✅ Ready for Phase 4: Gateway Integration")
        return 0
    else:
        print(f"\n❌ {total - passed_count} recipe(s) failed validation")
        return 1


if __name__ == "__main__":
    sys.exit(main())
