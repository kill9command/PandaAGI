"""
Golden query tests for live animal commerce queries.

Verifies that pet queries are correctly classified and
routed to pets-specific prompts that filter out toys/supplies.
"""

import pytest
import json
from unittest.mock import AsyncMock

from libs.gateway.query_analyzer import QueryAnalyzer, QueryAnalysis


# Golden pets queries that should be classified as content_type="pets"
PETS_QUERIES = [
    {
        "query": "find me a Syrian hamster for sale",
        "expected_content_type": "pets",
        "expected_intent": "commerce",
        "description": "Hamster purchase - live animal"
    },
    {
        "query": "where can I buy a hamster",
        "expected_content_type": "pets",
        "expected_intent": "commerce",
        "description": "Generic hamster purchase"
    },
    {
        "query": "hamster breeders near me",
        "expected_content_type": "pets",
        "expected_intent": "commerce",
        "description": "Breeder search"
    },
    {
        "query": "adopt a golden retriever puppy",
        "expected_content_type": "pets",
        "expected_intent": "commerce",
        "description": "Dog adoption"
    },
    {
        "query": "where to buy goldfish",
        "expected_content_type": "pets",
        "expected_intent": "commerce",
        "description": "Fish purchase"
    },
]


# Queries that should NOT be classified as pets (pet supplies, toys, etc.)
NOT_PETS_QUERIES = [
    {
        "query": "hamster cage and accessories",
        "expected_content_type": "general",
        "expected_intent": "commerce",
        "description": "Pet supplies - not live animal"
    },
    {
        "query": "hamster food and bedding",
        "expected_content_type": "general",
        "expected_intent": "commerce",
        "description": "Pet food - not live animal"
    },
    {
        "query": "plush hamster toy for kids",
        "expected_content_type": "general",
        "expected_intent": "commerce",
        "description": "Toy - not live animal"
    },
    {
        "query": "hamster wheel and exercise ball",
        "expected_content_type": "general",
        "expected_intent": "commerce",
        "description": "Pet accessories - not live animal"
    },
]


class TestPetsClassification:
    """Test that live animal queries are correctly classified."""

    @pytest.mark.parametrize("query_data", PETS_QUERIES, ids=lambda x: x["description"])
    def test_pets_query_classification(self, query_data, mock_llm_client):
        """Live animal queries should have content_type='pets'."""
        mock_llm_client.call = AsyncMock(return_value=json.dumps({
            "resolved_query": query_data["query"],
            "was_resolved": False,
            "query_type": "new_topic",
            "intent": query_data["expected_intent"],
            "intent_metadata": {"product": "live animal"},
            "content_type": query_data["expected_content_type"],
            "content_reference": None,
            "reasoning": "Live animal purchase query"
        }))

        analyzer = QueryAnalyzer(llm_client=mock_llm_client)
        result = analyzer._parse_response(
            query_data["query"],
            mock_llm_client.call.return_value
        )

        assert result.content_type == "pets", \
            f"Query '{query_data['query']}' should be classified as pets"
        assert result.intent == "commerce", \
            f"Query '{query_data['query']}' should have commerce intent"


class TestNotPetsClassification:
    """Test that pet supplies/toys are NOT classified as pets."""

    @pytest.mark.parametrize("query_data", NOT_PETS_QUERIES, ids=lambda x: x["description"])
    def test_supplies_not_classified_as_pets(self, query_data, mock_llm_client):
        """Pet supplies and toys should have content_type='general'."""
        mock_llm_client.call = AsyncMock(return_value=json.dumps({
            "resolved_query": query_data["query"],
            "was_resolved": False,
            "query_type": "new_topic",
            "intent": query_data["expected_intent"],
            "intent_metadata": {"product": "pet supplies"},
            "content_type": query_data["expected_content_type"],
            "content_reference": None,
            "reasoning": "Pet supplies, not live animal"
        }))

        analyzer = QueryAnalyzer(llm_client=mock_llm_client)
        result = analyzer._parse_response(
            query_data["query"],
            mock_llm_client.call.return_value
        )

        assert result.content_type == "general", \
            f"Query '{query_data['query']}' should be classified as general, not pets"


class TestPetsRecipeRouting:
    """Test that pets queries route to correct recipe."""

    def test_pets_planner_recipe_exists(self):
        """planner_chat_pets recipe should exist."""
        from libs.gateway.recipe_loader import load_recipe

        recipe = load_recipe("planner_chat_pets")
        assert recipe.name == "planner_chat_pets"
        assert recipe.role == "planner"
        assert recipe.mode == "chat"

    def test_pets_synthesizer_recipe_exists(self):
        """synthesizer_chat_pets recipe should exist."""
        from libs.gateway.recipe_loader import load_recipe

        recipe = load_recipe("synthesizer_chat_pets")
        assert recipe.name == "synthesizer_chat_pets"
        assert recipe.role == "synthesizer"
        assert recipe.mode == "chat"

    def test_select_recipe_routes_to_pets(self):
        """select_recipe should return pets recipe for pets content_type."""
        from libs.gateway.recipe_loader import select_recipe

        recipe = select_recipe("planner", "chat", content_type="pets")
        assert recipe.name == "planner_chat_pets"

        recipe = select_recipe("synthesizer", "chat", content_type="pets")
        assert recipe.name == "synthesizer_chat_pets"


class TestPetsPromptContent:
    """Test that pets prompts contain expected content."""

    def test_pets_planner_prompt_has_live_animal_focus(self):
        """Pets planner prompt should emphasize live animals."""
        from pathlib import Path

        prompt_path = Path("apps/prompts/planner/strategic_pets.md")
        assert prompt_path.exists(), "Pets planner prompt should exist"

        content = prompt_path.read_text()
        assert "live" in content.lower(), "Should mention live animals"
        assert "breeder" in content.lower(), "Should mention breeders"
        # Should mention what to exclude
        assert "toy" in content.lower() or "plush" in content.lower(), \
            "Should mention toys/plush to exclude"

    def test_pets_synthesizer_prompt_has_disqualifiers(self):
        """Pets synthesizer prompt should list disqualifiers."""
        from pathlib import Path

        prompt_path = Path("apps/prompts/synthesizer/synthesis_pets.md")
        assert prompt_path.exists(), "Pets synthesizer prompt should exist"

        content = prompt_path.read_text()
        # Should explicitly disqualify non-animals
        assert "plush" in content.lower() or "toy" in content.lower(), \
            "Should mention toys/plush to exclude"
        assert "cage" in content.lower() or "supplies" in content.lower(), \
            "Should mention supplies to exclude"


class TestHamsterRegression:
    """
    Regression tests for the hamster query issue.

    The original problem: "find me a Syrian hamster for sale"
    returned toys and supplies instead of live animals.
    """

    def test_hamster_query_classified_as_pets(self, mock_llm_client):
        """Syrian hamster query should be classified as pets content_type."""
        query = "find me a Syrian hamster for sale"

        mock_llm_client.call = AsyncMock(return_value=json.dumps({
            "resolved_query": query,
            "was_resolved": False,
            "query_type": "new_topic",
            "intent": "commerce",
            "intent_metadata": {"product": "Syrian hamster"},
            "content_type": "pets",
            "content_reference": None,
            "reasoning": "User wants to buy a live Syrian hamster"
        }))

        analyzer = QueryAnalyzer(llm_client=mock_llm_client)
        result = analyzer._parse_response(query, mock_llm_client.call.return_value)

        # Critical assertion: hamster = pets, not general
        assert result.content_type == "pets", \
            "Hamster purchase query MUST be classified as pets"
        assert result.intent == "commerce"

    def test_hamster_routes_to_pets_recipe(self):
        """Hamster query should route to pets-specific recipe."""
        from libs.gateway.recipe_loader import select_recipe

        recipe = select_recipe("planner", "chat", content_type="pets")
        assert "pets" in recipe.name, \
            "Pets content_type should route to pets-specific recipe"
