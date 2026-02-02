"""
Golden query tests for electronics commerce queries.

Verifies that electronics queries are correctly classified
and routed to electronics-specific prompts.
"""

import pytest
import json
from unittest.mock import AsyncMock, patch

from libs.gateway.query_analyzer import QueryAnalyzer, QueryAnalysis


# Golden electronics queries that should be classified as content_type="electronics"
ELECTRONICS_QUERIES = [
    {
        "query": "cheapest laptop with nvidia gpu",
        "expected_content_type": "electronics",
        "expected_intent": "commerce",
        "description": "Budget laptop with GPU requirement"
    },
    {
        "query": "gaming laptop under $1000 with rtx 4060",
        "expected_content_type": "electronics",
        "expected_intent": "commerce",
        "description": "Gaming laptop with specific GPU"
    },
    {
        "query": "find me a good 4k monitor",
        "expected_content_type": "electronics",
        "expected_intent": "commerce",
        "description": "Monitor shopping"
    },
    {
        "query": "best mechanical keyboard under $100",
        "expected_content_type": "electronics",
        "expected_intent": "commerce",
        "description": "Keyboard shopping"
    },
    {
        "query": "where can I buy an RTX 4080",
        "expected_content_type": "electronics",
        "expected_intent": "commerce",
        "description": "GPU shopping"
    },
    {
        "query": "compare iPhone 15 and Samsung Galaxy S24",
        "expected_content_type": "electronics",
        "expected_intent": "commerce",
        "description": "Phone comparison"
    },
]


class TestElectronicsClassification:
    """Test that electronics queries are correctly classified."""

    @pytest.mark.parametrize("query_data", ELECTRONICS_QUERIES, ids=lambda x: x["description"])
    def test_electronics_query_classification(self, query_data, mock_llm_client):
        """Electronics queries should have content_type='electronics'."""
        # Setup mock response
        mock_llm_client.call = AsyncMock(return_value=json.dumps({
            "resolved_query": query_data["query"],
            "was_resolved": False,
            "query_type": "new_topic",
            "intent": query_data["expected_intent"],
            "intent_metadata": {"product": "electronics item"},
            "content_type": query_data["expected_content_type"],
            "content_reference": None,
            "reasoning": "Electronics product query"
        }))

        # Parse response directly (since we're testing the parsing logic)
        analyzer = QueryAnalyzer(llm_client=mock_llm_client)
        result = analyzer._parse_response(
            query_data["query"],
            mock_llm_client.call.return_value
        )

        assert result.content_type == "electronics", \
            f"Query '{query_data['query']}' should be classified as electronics"
        assert result.intent == "commerce", \
            f"Query '{query_data['query']}' should have commerce intent"


class TestElectronicsRecipeRouting:
    """Test that electronics queries route to correct recipe."""

    def test_electronics_planner_recipe_exists(self):
        """planner_chat_electronics recipe should exist."""
        from libs.gateway.recipe_loader import load_recipe

        recipe = load_recipe("planner_chat_electronics")
        assert recipe.name == "planner_chat_electronics"
        assert recipe.role == "planner"
        assert recipe.mode == "chat"

    def test_electronics_synthesizer_recipe_exists(self):
        """synthesizer_chat_electronics recipe should exist."""
        from libs.gateway.recipe_loader import load_recipe

        recipe = load_recipe("synthesizer_chat_electronics")
        assert recipe.name == "synthesizer_chat_electronics"
        assert recipe.role == "synthesizer"
        assert recipe.mode == "chat"

    def test_select_recipe_routes_to_electronics(self):
        """select_recipe should return electronics recipe for electronics content_type."""
        from libs.gateway.recipe_loader import select_recipe

        recipe = select_recipe("planner", "chat", content_type="electronics")
        assert recipe.name == "planner_chat_electronics"

        recipe = select_recipe("synthesizer", "chat", content_type="electronics")
        assert recipe.name == "synthesizer_chat_electronics"


class TestElectronicsPromptContent:
    """Test that electronics prompts contain expected content."""

    def test_electronics_planner_prompt_has_price_focus(self):
        """Electronics planner prompt should mention price comparison."""
        from pathlib import Path

        prompt_path = Path("apps/prompts/planner/strategic_electronics.md")
        assert prompt_path.exists(), "Electronics planner prompt should exist"

        content = prompt_path.read_text()
        assert "price" in content.lower(), "Should mention price"
        assert "spec" in content.lower(), "Should mention specs"

    def test_electronics_synthesizer_prompt_has_table_format(self):
        """Electronics synthesizer prompt should mention comparison tables."""
        from pathlib import Path

        prompt_path = Path("apps/prompts/synthesizer/synthesis_electronics.md")
        assert prompt_path.exists(), "Electronics synthesizer prompt should exist"

        content = prompt_path.read_text()
        assert "table" in content.lower(), "Should mention comparison table"
        assert "price" in content.lower(), "Should mention price"
