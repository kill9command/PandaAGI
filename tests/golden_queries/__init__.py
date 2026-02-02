"""
Golden Query Tests for Content-Type Classification and Routing.

This test suite verifies that:
1. Commerce queries are correctly classified by content_type (electronics, pets, general)
2. Content-type-specific recipes are selected when available
3. Pets queries return live animals, NOT toys or supplies (hamster regression)
4. Electronics queries include specs and price comparisons

Run with: pytest tests/golden_queries/ -v
"""
