import os
import sys
import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def reload_orch(base_path: Path):
    os.environ["REPOS_BASE"] = str(base_path)
    # TODO: Test needs rewrite - original module structure changed
    mod_name = "apps.tool_server.app"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    module = importlib.import_module(mod_name)
    importlib.reload(module)
    return module.app


def test_commerce_search_offers(monkeypatch, tmp_path):
    base = tmp_path / "repos"
    base.mkdir()

    sample_offers = [
        {
            "title": "Sample Frame",
            "link": "https://store.example/frame",
            "source": "Example Store",
            "price": 89.99,
            "currency": "USD",
            "price_text": "$89.99",
            "availability": "In Stock",
            "position": 1,
        },
        {
            "title": "Sample Frame B",
            "link": "https://store.example/frame-b",
            "source": "Example Store B",
            "price": 95.50,
            "currency": "USD",
            "price_text": "$95.50",
            "availability": "In Stock",
            "position": 2,
        },
    ]

    import apps.services.tool_server.commerce_mcp as commerce_mcp

    monkeypatch.setattr(commerce_mcp, "search_offers", lambda *args, **kwargs: sample_offers)

    app = reload_orch(base)
    client = TestClient(app)
    resp = client.post(
        "/commerce.search_offers",
        json={"query": "cinewhoop frame", "extra_query": "3 inch", "max_results": 3},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["offers"][0]["title"] == "Sample Frame"
    assert data["best_offer"]["price"] == 89.99
    assert "Best offer" in data["summary"]


def test_docs_write_spreadsheet_csv(monkeypatch, tmp_path):
    base = tmp_path / "repos"
    repo = base / "panda"
    repo.mkdir(parents=True)

    app = reload_orch(base)
    client = TestClient(app)
    rows = [
        {"part": "Frame", "quantity": 1, "price": 89.99, "link": "https://store.example/frame"},
        {"part": "Flight Controller", "quantity": 1, "price": 129.0, "link": "https://store.example/fc"},
    ]
    resp = client.post(
        "/docs.write_spreadsheet",
        json={"repo": str(repo), "rows": rows, "filename": "cinewhoop_parts.csv"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    target = Path(data["path"])
    assert target.exists()
    content = target.read_text()
    assert "Frame" in content and "Flight Controller" in content
    assert data["format"] == "csv"
    assert data["rows"] == 2
