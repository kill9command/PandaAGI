#!/usr/bin/env python3
"""
Playwright fetch diagnostic script.

Attempts to fetch a set of URLs using Playwright with different wait_until modes
and a higher timeout. Prints status, response status (when available), title,
HTML length, and any exception information.

Usage:
  set -a && source .env && PYTHONPATH=/home/henry/pythonprojects/pandaai python scripts/playwright_fetch_diag.py
"""
from __future__ import annotations
import time
from pathlib import Path

URLS = [
    "https://www.chewy.com/education/small-pet/hamster/how-much-are-hamsters-budgeting-tips-and-cost-guide",
    "https://www.petsupermarket.com/small-pet/live-small-pets-2/?srsltid=AfmBOorrtk1KYNvLjylZ3EBV7ckI5dlLI0x3X_1VyM7MHKJ-WaHjyEgo",
    "https://articles.hepper.com/where-to-buy-a-hamster/"
]

WAIT_MODES = ["networkidle", "load", "domcontentloaded"]
TIMEOUT_SECS = 60

def main():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print("Playwright not available or import failed:", e)
        print("Install playwright and run `playwright install` in the environment.")
        return

    print("Playwright diagnostic - testing URLs with wait modes:", WAIT_MODES)
    with sync_playwright() as p:
        for url in URLS:
            print("\n=== URL:", url)
            for wait in WAIT_MODES:
                try:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")
                    page = context.new_page()
                    page.set_default_navigation_timeout(int(TIMEOUT_SECS * 1000))
                    t0 = time.time()
                    resp = page.goto(url, wait_until=wait)
                    elapsed = time.time() - t0
                    status = None
                    try:
                        status = resp.status if resp is not None else None
                    except Exception:
                        status = None
                    title = ""
                    try:
                        title = page.title()
                    except Exception:
                        title = ""
                    html = page.content() or ""
                    print(f"wait={wait} elapsed={elapsed:.2f}s status={status} title={title!r} html_len={len(html)}")
                    page.close()
                    context.close()
                    browser.close()
                except Exception as exc:
                    print(f"wait={wait} ERROR: {type(exc).__name__}: {exc}")
    print("\nDiagnostic complete.")

if __name__ == "__main__":
    main()
