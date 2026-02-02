import sys
import types

from apps.services.orchestrator import commerce_mcp


def test_search_offers_filters_irrelevant_titles(monkeypatch):
    def fake_search(*args, **kwargs):
        return [
            {
                "title": "Abiquiu Scented Sachet Package of Six",
                "link": "https://example.com/sachet",
                "price": "$6",
            },
            {
                "title": "Live Syrian hamster from local breeder",
                "link": "https://example.com/hamster",
                "price": "$45",
                "extracted_price": 45,
            },
        ]

    fetch_calls: list[str] = []

    def fake_fetch(link: str):
        fetch_calls.append(link)
        return {"raw_html": "<html>Live Syrian hamster available now.</html>"}

    monkeypatch.setattr(commerce_mcp.serpapi_mcp, "search_shopping", fake_search)
    monkeypatch.setattr(commerce_mcp.playwright_mcp, "fetch_page", fake_fetch)
    monkeypatch.setattr(commerce_mcp, "_is_relevant_product", lambda html, query, title="": True)

    offers = commerce_mcp.search_offers("Syrian hamster for sale", max_results=5)

    assert len(offers) == 1
    assert offers[0]["title"].lower().startswith("live syrian")
    assert fetch_calls == ["https://example.com/hamster"], "irrelevant listing should be skipped before fetch"


def test_is_relevant_product_falls_back_to_heuristics(monkeypatch):
    dummy_httpx = types.SimpleNamespace()

    def boom(*args, **kwargs):
        raise RuntimeError("llm offline")

    dummy_httpx.post = boom
    monkeypatch.setitem(sys.modules, "httpx", dummy_httpx)

    assert commerce_mcp._is_relevant_product(
        "<html>Live Syrian hamster available.</html>",
        "syrian hamster for sale",
        title="Live Syrian hamster",
    )

    assert not commerce_mcp._is_relevant_product(
        "<html>Herbal sachets and aromatherapy.</html>",
        "syrian hamster for sale",
        title="Abiquiu Scented Sachet Package of Six",
    )
