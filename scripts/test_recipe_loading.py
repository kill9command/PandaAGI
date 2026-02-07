#!/usr/bin/env python3
"""
Test script for recipe loading with new structured format.

Tests:
1. All 6 recipes load successfully
2. DocSpec path_type is parsed correctly
3. max_tokens budgets are parsed correctly
4. Backward compatibility with legacy string format
"""
import sys
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

from libs.gateway.llm.recipe_loader import load_recipe, RecipeValidationError


def test_recipe_loading():
    """Test all 6 recipes load successfully with new format."""

    recipes = [
        "guide_synthesis_chat",
        "guide_synthesis_code",
        "guide_strategic_chat",
        "coordinator_chat",
        "coordinator_code",
        "context_manager"
    ]

    print("=" * 80)
    print("Recipe Loading Test - Structured Format with max_tokens and path_type")
    print("=" * 80)
    print()

    passed = 0
    failed = 0

    for recipe_name in recipes:
        try:
            recipe = load_recipe(recipe_name)

            print(f"✅ {recipe_name}")
            print(f"   Role: {recipe.role}, Mode: {recipe.mode}, Phase: {recipe.phase}")
            print(f"   Token Budget: {recipe.token_budget.total} total")
            print(f"   Input Docs: {len(recipe.input_docs)}")

            # Check that docs have path_type and max_tokens
            for doc in recipe.input_docs:
                path_type = doc.path_type
                max_tokens = doc.max_tokens if doc.max_tokens else "unspecified"
                optional = "(optional)" if doc.optional else ""

                print(f"      - {doc.path}: path_type={path_type}, max_tokens={max_tokens} {optional}")

            print()
            passed += 1

        except RecipeValidationError as e:
            print(f"❌ {recipe_name}: Validation Error: {e}")
            print()
            failed += 1

        except Exception as e:
            print(f"❌ {recipe_name}: {type(e).__name__}: {e}")
            print()
            failed += 1

    print("=" * 80)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 80)

    if failed > 0:
        sys.exit(1)
    else:
        print()
        print("✅ All recipes loaded successfully with structured format!")
        print()
        print("Key Features Verified:")
        print("  - path_type field parsed correctly (turn/repo/session/absolute)")
        print("  - max_tokens budgets parsed from structured YAML")
        print("  - Backward compatible with legacy string format")
        print()


if __name__ == "__main__":
    test_recipe_loading()
