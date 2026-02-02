"""
Playwright dry-run test (offline-first).

This test exercises:
- orchestrator.context_builder.perform_search_request
- orchestrator.web_fetcher.fetch_and_stage

It creates local HTML fixtures under the test tmp_path and uses fetch_mode 'file' to avoid network access.
"""
from pathlib import Path
import json
try:
    from apps.orchestrator.context_builder import perform_search_request
except Exception:
    from apps.services.orchestrator.context_builder import perform_search_request


def make_fixture(dirpath: Path, name: str, title: str, body_html: str) -> Path:
    p = dirpath / name
    html = f"""<!doctype html>
<html>
  <head><title>{title}</title></head>
  <body>
    <h1>{title}</h1>
    <p>{body_html}</p>
  </body>
</html>"""
    p.write_text(html, encoding="utf-8")
    return p


def test_perform_search_request_dryrun(tmp_path: Path):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()

    p1 = make_fixture(fixtures, "page1.html", "Page One", "This is the first fixture page for testing.")
    p2 = make_fixture(fixtures, "page2.html", "Page Two", "Second page content with slightly more text to exercise chunking.")
    p3 = make_fixture(fixtures, "page3.html", "Page Three", "Third page content. Short.")

    staged_root = tmp_path / "staged"
    staged_root.mkdir()

    queries = [str(p1), str(p2), str(p3)]
    req = {"queries": queries, "fetch_mode": "file"}

    results = perform_search_request(req, staged_root=str(staged_root))

    # Basic assertions
    assert isinstance(results, list)
    assert len(results) == 3

    for res in results:
        assert "url" in res
        # If fetch succeeded, staged_path should exist
        assert "staged_path" in res, f"missing staged_path for result: {res}"
        staged_path = Path(res["staged_path"])
        assert staged_path.exists() and staged_path.is_dir()
        content_md = staged_path / "content.md"
        meta_json = staged_path / "meta.json"
        raw_html = staged_path / "raw.html"
        assert content_md.exists()
        assert meta_json.exists()
        assert raw_html.exists()

        # content should contain at least some of the original fixture text
        cm = content_md.read_text(encoding="utf-8")
        assert len(cm) > 10

        meta = json.loads(meta_json.read_text(encoding="utf-8"))
        assert meta.get("url") == res["url"]
