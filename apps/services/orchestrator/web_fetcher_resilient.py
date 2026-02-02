"""
orchestrator/web_fetcher_resilient.py

Resilient web fetching with multiple fallback methods.
Exhausts all available options to retrieve web content.
"""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, Optional, List
from urllib.parse import urlparse
import logging

from apps.services.orchestrator.shared.browser_factory import launch_browser, get_default_user_agent

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    """Result from web fetch attempt"""
    html: str
    url: str
    method: str  # Which method succeeded
    status_code: Optional[int]
    headers: Dict[str, str]
    success: bool
    error: Optional[str] = None


class ResilientWebFetcher:
    """
    Fetches web content using multiple fallback strategies.
    Tries methods in order until one succeeds.
    """
    
    def __init__(
        self,
        *,
        user_agent: str = "PandaAI/1.0 Personal Shopping Assistant",
        timeout: float = 10.0,  # Phase 1: Reduced from 30s for faster failure
        max_retries: int = 1     # Phase 1: Reduced from 2 to minimize retry overhead
    ):
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_retries = max_retries
        self.last_request_times: Dict[str, float] = {}
    
    async def fetch(self, url: str, **kwargs) -> FetchResult:
        """
        Fetch URL using all available methods until one succeeds.

        Order of attempts (Phase 1 optimized):
        1. httpx async (fastest, handles most sites - prioritized)
        2. requests (sync fallback, very reliable)
        3. Playwright (headless browser - for JS-heavy sites only)
        4. curl subprocess (ultimate fallback)
        """
        methods = [
            ("httpx", self._fetch_httpx),
            ("requests", self._fetch_requests),
            ("playwright", self._fetch_playwright),
            ("curl", self._fetch_curl),
            # wget removed - redundant with curl
        ]
        
        errors = []
        error_details = []  # NEW (2025-11-13): Structured error tracking

        for method_name, method_func in methods:
            try:
                logger.info(f"[WebFetch] Attempting {method_name} for: {url[:80]}")
                result = await method_func(url, **kwargs)
                if result.success:
                    logger.info(f"[WebFetch-SUCCESS] {method_name} succeeded: {url[:60]} (status={result.status_code})")
                    return result

                # NEW (2025-11-13): Enhanced error tracking
                error_detail = {
                    "method": method_name,
                    "error": result.error,
                    "status_code": result.status_code,
                    "url": url[:100]
                }
                error_details.append(error_detail)
                errors.append(f"{method_name}: {result.error}")

                logger.warning(
                    f"[WebFetch-FAIL] {method_name} failed: {result.error} "
                    f"(status={result.status_code}, url={url[:60]})"
                )
            except Exception as e:
                # NEW (2025-11-13): Enhanced exception logging with error type
                error_type = type(e).__name__
                error_detail = {
                    "method": method_name,
                    "error": str(e),
                    "error_type": error_type,
                    "status_code": None,
                    "url": url[:100]
                }
                error_details.append(error_detail)
                errors.append(f"{method_name}: {error_type}: {str(e)}")

                logger.warning(
                    f"[WebFetch-EXCEPTION] {method_name} raised {error_type}: {str(e)[:100]} "
                    f"(url={url[:60]})"
                )
                continue

        # NEW (2025-11-13): All methods failed - log detailed summary
        error_summary = '; '.join([f"{e['method']}={e.get('error_type', 'fail')}" for e in error_details])
        logger.error(
            f"[WebFetch-ALL-FAILED] URL: {url[:80]} | "
            f"Attempted: {len(methods)} methods | "
            f"Errors: {len(error_details)} | "
            f"Summary: {error_summary}"
        )

        return FetchResult(
            html="",
            url=url,
            method="none",
            status_code=None,
            headers={},
            success=False,
            error=f"All {len(methods)} fetch methods failed: {'; '.join(errors[:3])}"  # Limit to first 3 errors for brevity
        )
    
    async def _fetch_playwright(self, url: str, **kwargs) -> FetchResult:
        """Fetch using Playwright headless browser"""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return FetchResult(
                html="", url=url, method="playwright", status_code=None,
                headers={}, success=False, error="Playwright not installed"
            )
        
        try:
            async with async_playwright() as p:
                browser = await launch_browser(p, headless=True)
                context = await browser.new_context(
                    user_agent=self.user_agent or get_default_user_agent(),
                    ignore_https_errors=True,
                )
                page = await context.new_page()
                
                # Apply rate limiting
                domain = urlparse(url).netloc
                await self._apply_rate_limit(domain)
                
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(self.timeout * 1000)
                )
                
                html = await page.content()
                status = response.status if response else 200
                headers_dict = dict(response.headers) if response else {}
                
                await browser.close()
                
                return FetchResult(
                    html=html,
                    url=url,
                    method="playwright",
                    status_code=status,
                    headers=headers_dict,
                    success=bool(html and len(html) > 100)
                )
        except Exception as e:
            return FetchResult(
                html="", url=url, method="playwright", status_code=None,
                headers={}, success=False, error=str(e)
            )
    
    async def _fetch_httpx(self, url: str, **kwargs) -> FetchResult:
        """Fetch using httpx async client"""
        try:
            import httpx
        except ImportError:
            return FetchResult(
                html="", url=url, method="httpx", status_code=None,
                headers={}, success=False, error="httpx not installed"
            )
        
        try:
            headers = {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }
            
            domain = urlparse(url).netloc
            await self._apply_rate_limit(domain)
            
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                verify=False  # Ignore SSL errors
            ) as client:
                response = await client.get(url, headers=headers)
                
                return FetchResult(
                    html=response.text,
                    url=str(response.url),
                    method="httpx",
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    success=response.status_code == 200 and len(response.text) > 100
                )
        except Exception as e:
            return FetchResult(
                html="", url=url, method="httpx", status_code=None,
                headers={}, success=False, error=str(e)
            )
    
    async def _fetch_requests(self, url: str, **kwargs) -> FetchResult:
        """Fetch using requests library (sync, wrapped in async)"""
        try:
            import requests
        except ImportError:
            return FetchResult(
                html="", url=url, method="requests", status_code=None,
                headers={}, success=False, error="requests not installed"
            )
        
        try:
            headers = {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            
            domain = urlparse(url).netloc
            await self._apply_rate_limit(domain)
            
            # Run sync requests in executor to not block event loop
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.get(
                    url,
                    headers=headers,
                    timeout=self.timeout,
                    allow_redirects=True,
                    verify=False
                )
            )
            
            return FetchResult(
                html=response.text,
                url=response.url,
                method="requests",
                status_code=response.status_code,
                headers=dict(response.headers),
                success=response.status_code == 200 and len(response.text) > 100
            )
        except Exception as e:
            return FetchResult(
                html="", url=url, method="requests", status_code=None,
                headers={}, success=False, error=str(e)
            )
    
    async def _fetch_curl(self, url: str, **kwargs) -> FetchResult:
        """Fetch using curl subprocess"""
        try:
            domain = urlparse(url).netloc
            await self._apply_rate_limit(domain)
            
            cmd = [
                "curl",
                "-L",  # Follow redirects
                "-s",  # Silent
                "-A", self.user_agent,
                "--max-time", str(int(self.timeout)),
                "--insecure",  # Ignore SSL errors
                url
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout + 5
            )
            
            html = result.stdout
            success = result.returncode == 0 and len(html) > 100
            
            return FetchResult(
                html=html,
                url=url,
                method="curl",
                status_code=200 if success else result.returncode,
                headers={},
                success=success,
                error=result.stderr if not success else None
            )
        except Exception as e:
            return FetchResult(
                html="", url=url, method="curl", status_code=None,
                headers={}, success=False, error=str(e)
            )
    
    async def _fetch_wget(self, url: str, **kwargs) -> FetchResult:
        """Fetch using wget subprocess (last resort)"""
        try:
            domain = urlparse(url).netloc
            await self._apply_rate_limit(domain)
            
            cmd = [
                "wget",
                "-q",  # Quiet
                "-O", "-",  # Output to stdout
                "--user-agent", self.user_agent,
                "--timeout", str(int(self.timeout)),
                "--no-check-certificate",  # Ignore SSL
                url
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout + 5
            )
            
            html = result.stdout
            success = result.returncode == 0 and len(html) > 100
            
            return FetchResult(
                html=html,
                url=url,
                method="wget",
                status_code=200 if success else result.returncode,
                headers={},
                success=success,
                error=result.stderr if not success else None
            )
        except Exception as e:
            return FetchResult(
                html="", url=url, method="wget", status_code=None,
                headers={}, success=False, error=str(e)
            )
    
    async def _apply_rate_limit(self, domain: str):
        """Apply gentle rate limiting per domain (0.5s between requests)"""
        import time
        
        now = time.time()
        last_request = self.last_request_times.get(domain, 0)
        elapsed = now - last_request
        
        if elapsed < 0.5:  # 2 requests/second max
            await asyncio.sleep(0.5 - elapsed)
        
        self.last_request_times[domain] = time.time()


# Singleton instance
_fetcher = None

def get_fetcher() -> ResilientWebFetcher:
    """Get singleton fetcher instance"""
    global _fetcher
    if _fetcher is None:
        _fetcher = ResilientWebFetcher()
    return _fetcher


async def fetch_url(url: str, **kwargs) -> FetchResult:
    """Convenience function to fetch URL with resilient fetching"""
    fetcher = get_fetcher()
    return await fetcher.fetch(url, **kwargs)
