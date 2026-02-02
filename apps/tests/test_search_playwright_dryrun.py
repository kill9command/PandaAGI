import pytest
from pathlib import Path
try:
    from apps.orchestrator.context_builder import perform_search_request, build_chunk_ranges_for_path
except Exception:
    from apps.services.orchestrator.context_builder import perform_search_request, build_chunk_ranges_for_path

"""
Playwright dry-run test

This test verifies the Orchestrator can:
- use the Playwright MCP wrapper to load a local file:// URL (or staged raw.html)
- stage fetched results under panda_system_docs/scrape_staging/<uuid>/
- produce staged files: raw.html, content.md, meta.json
- produce chunk metadata via build_chunk_ranges_for_path

The test will be skipped if Playwright is not installed in the environment (keeps CI safe).
It reuses existing staged raw.html fixtures under panda_system_docs/scrape_staging/ when present.
"""

def test_playwright_fetch_staged_file():
    # Skip if Playwright wrapper (or Playwright) isn't available
    try:
        from apps.orchestrator import playwright_mcp  # noqa: F401
    except Exception:
        try:
            from apps.services.orchestrator import playwright_mcp  # noqa: F401
        except Exception:
            pytest.skip("Playwright not available in environment; skipping Playwright dry-run test")

    staging_root = Path("panda_system_docs/scrape_staging")
    candidates = list(staging_root.glob("*/raw.html"))
    assert candidates, f"No staged raw.html fixtures found under {staging_root}; add fixtures or create staged pages first."

    # Use the first available staged raw.html as a local file URL for Playwright to load
    raw = candidates[0]
    url = f"file://{raw.resolve()}"

    search_request = {
        "queries": [url],
        "fetch_mode": "playwright",
        "follow_links": False,
        "follow_links_depth": 0,
        "max_links_per_page": 0,
    }

    results = perform_search_request(search_request, staged_root=str(staging_root))
    assert results, "perform_search_request returned no results"

    # Validate staged output and files
    item = results[0]
    assert "staged_path" in item, "result missing staged_path"
    staged_path = Path(item["staged_path"])
    assert (staged_path / "raw.html").exists(), "staged raw.html missing"
    assert (staged_path / "content.md").exists(), "staged content.md missing"
    assert (staged_path / "meta.json").exists(), "staged meta.json missing"

    # Validate chunk metadata generation on the staged content.md
    content_md_path = staged_path / "content.md"
    chunks = build_chunk_ranges_for_path(str(content_md_path))
    assert isinstance(chunks, list), "build_chunk_ranges_for_path did not return a list"
    assert chunks, "chunker returned no chunks for the staged content"
