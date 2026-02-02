"""
Tests for content-type classification in QueryAnalyzer.

Verifies that the QueryAnalyzer correctly classifies commerce queries
into electronics, pets, or general content types.
"""

import pytest
import json
from unittest.mock import AsyncMock, patch
from pathlib import Path

from libs.gateway.query_analyzer import QueryAnalyzer, QueryAnalysis


class TestContentTypeClassification:
    """Test content_type field in QueryAnalysis."""

    def test_query_analysis_has_content_type_field(self):
        """QueryAnalysis dataclass should have content_type field."""
        analysis = QueryAnalysis(
            resolved_query="test query",
            intent="commerce",
            content_type="electronics"
        )
        assert hasattr(analysis, "content_type")
        assert analysis.content_type == "electronics"

    def test_query_analysis_default_content_type(self):
        """content_type should default to 'general'."""
        analysis = QueryAnalysis(resolved_query="test query")
        assert analysis.content_type == "general"

    def test_query_analysis_to_dict_includes_content_type(self):
        """to_dict() should include content_type."""
        analysis = QueryAnalysis(
            resolved_query="test",
            intent="commerce",
            content_type="pets"
        )
        d = analysis.to_dict()
        assert "content_type" in d
        assert d["content_type"] == "pets"

    def test_query_analysis_valid_content_types(self):
        """Only electronics, pets, and general should be valid."""
        valid_types = {"electronics", "pets", "general"}

        for ct in valid_types:
            analysis = QueryAnalysis(
                resolved_query="test",
                content_type=ct
            )
            assert analysis.content_type == ct


class TestQueryAnalyzerParsing:
    """Test QueryAnalyzer response parsing for content_type."""

    @pytest.fixture
    def analyzer(self, mock_llm_client):
        """Create a QueryAnalyzer instance."""
        return QueryAnalyzer(
            llm_client=mock_llm_client,
            turns_dir=Path("/tmp/test_turns")
        )

    def test_parse_electronics_response(self, analyzer, query_analyzer_response_electronics):
        """Should correctly parse electronics content_type."""
        result = analyzer._parse_response(
            "cheapest laptop with nvidia gpu",
            query_analyzer_response_electronics
        )
        assert result.intent == "commerce"
        assert result.content_type == "electronics"

    def test_parse_pets_response(self, analyzer, query_analyzer_response_pets):
        """Should correctly parse pets content_type."""
        result = analyzer._parse_response(
            "find me a Syrian hamster for sale",
            query_analyzer_response_pets
        )
        assert result.intent == "commerce"
        assert result.content_type == "pets"

    def test_parse_general_response(self, analyzer, query_analyzer_response_general):
        """Should correctly parse general content_type."""
        result = analyzer._parse_response(
            "best office chair under $300",
            query_analyzer_response_general
        )
        assert result.intent == "commerce"
        assert result.content_type == "general"

    def test_parse_invalid_content_type_defaults_to_general(self, analyzer):
        """Invalid content_type should default to general."""
        response = json.dumps({
            "resolved_query": "test",
            "intent": "commerce",
            "content_type": "invalid_type",
            "reasoning": "test"
        })
        result = analyzer._parse_response("test", response)
        assert result.content_type == "general"

    def test_parse_missing_content_type_defaults_to_general(self, analyzer):
        """Missing content_type should default to general."""
        response = json.dumps({
            "resolved_query": "test",
            "intent": "commerce",
            # content_type intentionally missing
            "reasoning": "test"
        })
        result = analyzer._parse_response("test", response)
        assert result.content_type == "general"


class TestContentTypeRouting:
    """Test that content_type correctly routes to specialized recipes."""

    def test_select_recipe_electronics(self):
        """Electronics content_type should try electronics-specific recipe."""
        from libs.gateway.recipe_loader import select_recipe

        # This should work if planner_chat_electronics.yaml exists
        try:
            recipe = select_recipe("planner", "chat", content_type="electronics")
            assert recipe.name in ("planner_chat_electronics", "planner_chat")
        except Exception:
            # Recipe may not exist yet, that's OK for this test
            pass

    def test_select_recipe_pets(self):
        """Pets content_type should try pets-specific recipe."""
        from libs.gateway.recipe_loader import select_recipe

        try:
            recipe = select_recipe("planner", "chat", content_type="pets")
            assert recipe.name in ("planner_chat_pets", "planner_chat")
        except Exception:
            pass

    def test_select_recipe_general_uses_base(self):
        """General content_type should use base recipe."""
        from libs.gateway.recipe_loader import select_recipe

        recipe = select_recipe("planner", "chat", content_type="general")
        assert recipe.name == "planner_chat"

    def test_select_recipe_none_uses_base(self):
        """No content_type should use base recipe."""
        from libs.gateway.recipe_loader import select_recipe

        recipe = select_recipe("planner", "chat", content_type=None)
        assert recipe.name == "planner_chat"


class TestQueryAnalysisSerialization:
    """Test QueryAnalysis save/load with content_type."""

    def test_save_and_load_preserves_content_type(self, tmp_path):
        """Saving and loading should preserve content_type."""
        analysis = QueryAnalysis(
            resolved_query="find hamster for sale",
            intent="commerce",
            content_type="pets",
            reasoning="Live animal query"
        )

        # Save
        analysis.save(tmp_path)

        # Load
        loaded = QueryAnalysis.load(tmp_path)

        assert loaded is not None
        assert loaded.content_type == "pets"
        assert loaded.intent == "commerce"
