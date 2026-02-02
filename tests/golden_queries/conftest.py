"""
Pytest fixtures for golden query tests.

These tests verify content-type classification and routing
for commerce queries (electronics, pets, general).
"""

import pytest
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Test data directory
GOLDEN_DATA_DIR = Path(__file__).parent / "golden_data"


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client for testing."""
    client = AsyncMock()
    return client


@pytest.fixture
def electronics_queries():
    """Load electronics golden queries."""
    path = GOLDEN_DATA_DIR / "electronics_queries.json"
    if path.exists():
        return json.loads(path.read_text())
    return []


@pytest.fixture
def pets_queries():
    """Load pets golden queries."""
    path = GOLDEN_DATA_DIR / "pets_queries.json"
    if path.exists():
        return json.loads(path.read_text())
    return []


@pytest.fixture
def query_analyzer_response_electronics():
    """Mock LLM response for electronics query classification."""
    return json.dumps({
        "resolved_query": "cheapest laptop with nvidia gpu",
        "was_resolved": False,
        "query_type": "new_topic",
        "intent": "commerce",
        "intent_metadata": {"product": "laptop with nvidia gpu"},
        "content_type": "electronics",
        "content_reference": None,
        "reasoning": "User wants to buy a laptop (electronics)"
    })


@pytest.fixture
def query_analyzer_response_pets():
    """Mock LLM response for pets query classification."""
    return json.dumps({
        "resolved_query": "find me a Syrian hamster for sale",
        "was_resolved": False,
        "query_type": "new_topic",
        "intent": "commerce",
        "intent_metadata": {"product": "Syrian hamster"},
        "content_type": "pets",
        "content_reference": None,
        "reasoning": "User wants to buy a live animal (hamster)"
    })


@pytest.fixture
def query_analyzer_response_general():
    """Mock LLM response for general commerce query classification."""
    return json.dumps({
        "resolved_query": "best office chair under $300",
        "was_resolved": False,
        "query_type": "new_topic",
        "intent": "commerce",
        "intent_metadata": {"product": "office chair under $300"},
        "content_type": "general",
        "content_reference": None,
        "reasoning": "User wants to buy furniture (general)"
    })
