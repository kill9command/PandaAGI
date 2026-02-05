from fastapi.testclient import TestClient

from apps.tool_server.app import app as orch_app


def test_purchasing_lookup_endpoint(monkeypatch):
    def fake_search_offers(query, max_results=5, extra_query="", country="us", language="en", pause=0.6):
        return [
            {
                "title": f"{query} offer",
                "link": "https://example.com/item",
                "source": "example-store",
                "price": 12.5,
                "currency": "USD",
                "price_text": "$12.50",
                "availability": "in stock",
                "position": 1,
            }
        ]

    monkeypatch.setattr("orchestrator.commerce_mcp.search_offers", fake_search_offers)

    client = TestClient(orch_app)
    resp = client.post(
        "/purchasing.lookup",
        json={"query": "syrian hamster", "extra_query": "for sale", "max_results": 3},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "syrian hamster"
    assert body["extra_query"] == "for sale"
    assert body["offers"]
    assert body["offers"][0]["title"] == "syrian hamster offer"
