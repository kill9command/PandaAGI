"""
orchestrator/web_fetcher.py

Lightweight web fetcher / extractor helpers used by the Orchestrator for
test/dry-run and simple fetch workflows.

Notes:
- This module intentionally avoids heavy third-party deps for the dry-run:
  - HTTP fetches use urllib.request
  - Local file reads use file:// URI handling
  - Playwright support is optional; if Playwright is installed the fetch_playwright
    helper will attempt to use it, otherwise it raises ImportError with a helpful message.
- Extraction is a best-effort HTML->plain-text conversion suitable for tests.
  For production use, replace extract_main_content with a Readability-based extractor.
"""

from __future__ import annotations
import os
import re
import uuid
import json
import urllib.request
from pathlib import Path
from typing import Dict, Any, Tuple

from apps.services.orchestrator.shared.browser_factory import get_sync_browser_type


def _http_get_text(url: str, timeout: int = 10) -> Tuple[str, int]:
    """Fetch text over HTTP(S). Returns (body, status_code)."""
    req = urllib.request.Request(url, headers={"User-Agent": "panda-orchestrator/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        body = resp.read().decode(charset, errors="replace")
        return body, resp.getcode()


def _read_file_uri(url: str) -> Tuple[str, int]:
    """Read a local file:// URI or plain file path."""
    if url.startswith("file://"):
        path = url[len("file://"):]
    else:
        path = url
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"fixture not found: {path}")
    # Return file text and pseudo-200 status
    body = p.read_text(encoding="utf-8", errors="replace")
    return body, 200


def fetch_url_basic(url: str, fetch_mode: str = "http") -> Dict[str, Any]:
    """
    Basic fetch routine that supports:
      - fetch_mode == "http"  -> HTTP(S) using urllib
      - fetch_mode == "file"  -> local files (file:// or path)
      - fetch_mode == "playwright" -> attempt to use Playwright if installed

    Returns:
      { "url": url, "status": int, "raw_html": str, "title": str, "error": str (optional), "error_code": str (optional) }
    """
    error = None
    status = 0
    body = ""
    # file/local handling
    if fetch_mode == "file" or url.startswith("file://") or Path(url).exists():
        try:
            body, status = _read_file_uri(url)
        except Exception as e:
            error = f"FILE_READ_ERROR: {e}"
            status = 0
    # http handling with retries and Playwright fallback
    elif fetch_mode == "http":
        import time
        max_retries = 2
        backoff = 1
        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                body, status = _http_get_text(url)
                last_exc = None
                break
            except Exception as e:
                last_exc = e
                if attempt < max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                # final attempt failed: try Playwright fallback
                try:
                    from apps.services.orchestrator import playwright_stealth_mcp as playwright_mcp
                    res = playwright_mcp.fetch_page(url, wait_until="networkidle", timeout=15, screenshot=False)
                    body = res.get("raw_html", "")
                    status = res.get("status", 200)
                    last_exc = None
                except Exception:
                    # try direct Playwright import
                    try:
                        from playwright.sync_api import sync_playwright
                    except Exception as e2:
                        error = f"HTTP_ERROR: {last_exc}; PLAYWRIGHT_UNAVAILABLE: {e2}"
                        status = 0
                    else:
                        try:
                            with sync_playwright() as p:
                                browser_type = get_sync_browser_type(p)
                                browser = browser_type.launch(headless=True)
                                page = browser.new_page()
                                page.goto(url, wait_until="networkidle")
                                body = page.content()
                                status = 200
                                browser.close()
                                last_exc = None
                        except Exception as e3:
                            error = f"HTTP_ERROR: {last_exc}; PLAYWRIGHT_FETCH_ERROR: {e3}"
                            status = 0
    elif fetch_mode == "playwright":
        # Prefer using the orchestrator.playwright_stealth_mcp wrapper if available; fall back to direct Playwright.
        try:
            from apps.services.orchestrator import playwright_stealth_mcp as playwright_mcp  # our MCP-style wrapper
        except Exception:
            # If the wrapper isn't present, try direct Playwright import for environments that have it installed.
            try:
                from playwright.sync_api import sync_playwright
            except Exception as e:
                raise ImportError(
                    "Playwright fetch requested but neither orchestrator.playwright_mcp nor Playwright are available. "
                    "Install playwright and run `playwright install` or add orchestrator.playwright_mcp."
                ) from e
            with sync_playwright() as p:
                browser_type = get_sync_browser_type(p)
                browser = browser_type.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until="networkidle")
                body = page.content()
                status = 200
                browser.close()
        else:
            # Use the wrapper's fetch_page API
            res = playwright_mcp.fetch_page(url, wait_until="networkidle", timeout=15, screenshot=False)
            body = res.get("raw_html", "")
            status = res.get("status", 200)
    else:
        raise ValueError(f"unknown fetch_mode: {fetch_mode}")

    # lightweight title extraction
    m = re.search(r"<title>(.*?)</title>", body, flags=re.IGNORECASE | re.DOTALL)
    title = m.group(1).strip() if m else (url.split("/")[-1] or url)

    result = {"url": url, "status": status, "raw_html": body, "title": title}
    if error:
        result["error"] = error
        result["error_code"] = "FETCH_FAILED"
    return result


def extract_main_content(html: str) -> str:
    """
    Very small HTML -> markdown/plain-text extractor for tests.
    - Strips <script>/<style> content
    - Removes tags and collapses whitespace
    - Leaves simple newlines for paragraphs
    This is intentionally simple for test/dry-run usage.
    """
    # remove script/style blocks
    html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    # replace <br> and <p> with newlines
    html = re.sub(r"(?i)</p>|<br\s*/?>", "\n", html)
    # remove all tags
    text = re.sub(r"<[^>]+>", " ", html)
    # collapse whitespace
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = text.strip()
    return text


def stage_scrape_result(staged_root: str, url: str, raw_html: str, content_md: str, meta: Dict[str, Any]) -> str:
    """
    Stage scraped result into panda_system_docs/scrape_staging/<uuid>/ and return the staged path.
    Creates directory if needed and writes raw.html, content.md, meta.json.
    """
    uid = uuid.uuid4().hex
    base = Path(staged_root) / uid
    base.mkdir(parents=True, exist_ok=True)
    raw_path = base / "raw.html"
    content_path = base / "content.md"
    meta_path = base / "meta.json"
    raw_path.write_text(raw_html, encoding="utf-8")
    content_path.write_text(content_md, encoding="utf-8")
    meta_data = {"url": url, **meta}
    meta_path.write_text(json.dumps(meta_data, indent=2), encoding="utf-8")
    return str(base)


# Convenience wrapper used by orchestrator in tests/dry-run
def fetch_and_stage(url: str, staged_root: str = "panda_system_docs/scrape_staging", fetch_mode: str = "http") -> Dict[str, Any]:
    """
    Fetch URL, extract main content, stage files, and return a SearchResultItem-like dict.

    Returned dict:
    {
      "url": url,
      "title": str,
      "snippet": first 300 chars,
      "content_md": content as plain text,
      "token_est": int (approx chars/4),
      "score": 0.0,
      "source": fetch_mode,
      "domain": <domain>,
      "fetched_at": "<ISO>",
      "staged_path": "<panda_system_docs/scrape_staging>/<uid>"
    }
    """
    res = fetch_url_basic(url, fetch_mode=fetch_mode)
    raw = res["raw_html"]
    content = extract_main_content(raw)
    snippet = content[:300]
    token_est = max(1, (len(content) + 3) // 4)
    domain = urllib.request.urlparse(url).netloc or "local"
    staged = stage_scrape_result(staged_root, url, raw, content, {"title": res["title"], "domain": domain})
    from datetime import datetime, timezone

    return {
        "url": url,
        "title": res["title"],
        "snippet": snippet,
        "content_md": content,
        "token_est": token_est,
        "score": 0.0,
        "source": fetch_mode,
        "domain": domain,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "staged_path": staged,
    }
