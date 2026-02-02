"""Webpage cache management for PandaAI v2.

Architecture Reference:
    architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md#6-webpage_cache-specification

Purpose:
    When the system visits a web page, it creates a webpage_cache capturing
    everything about that visit. This enables answering follow-up questions
    from cached data without re-navigating.

Retrieval Hierarchy:
    | Priority | Source                      | Speed   |
    |----------|-----------------------------| --------|
    | 1        | manifest.json content_summary| Instant |
    | 2        | extracted_data.json         | Instant |
    | 3        | page_content.md             | Instant |
    | 4        | Navigate to source_url      | Slow    |

Directory Structure:
    turn_000001/
    └── webpage_cache/
        └── {url_slug}/
            ├── manifest.json
            ├── page_content.md
            ├── extracted_data.json
            └── screenshot.png (optional)
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import json
import re


class WebpageCacheManager:
    """Manages cached webpage data.

    Implements cache-first retrieval pattern:
    1. Check manifest.json content_summary
    2. Check extracted_data.json
    3. Check page_content.md
    4. Navigate to source_url (last resort)
    """

    def __init__(self, turn_dir: Path):
        """
        Initialize cache manager.

        Args:
            turn_dir: Turn directory
        """
        self.turn_dir = turn_dir
        self.cache_dir = turn_dir / "webpage_cache"

    def create_cache(self, url: str, title: str) -> Path:
        """
        Create cache directory for a URL.

        Args:
            url: Page URL
            title: Page title

        Returns:
            Path to cache directory
        """
        slug = self._url_to_slug(url)
        cache_path = self.cache_dir / slug
        cache_path.mkdir(parents=True, exist_ok=True)

        # Create initial manifest
        manifest = {
            "url": url,
            "url_slug": slug,
            "title": title,
            "visited_at": datetime.now().isoformat(),
            "turn_number": self._get_turn_number(),
            "captured": {
                "page_content": False,
                "screenshot": False,
                "extracted_data": False,
            },
            "content_summary": {},
            "answerable_questions": [],
        }
        self._save_manifest(cache_path, manifest)

        return cache_path

    def get_cache(self, url: str) -> Optional[Path]:
        """
        Get cache directory for a URL if it exists.

        Args:
            url: Page URL

        Returns:
            Cache path or None
        """
        slug = self._url_to_slug(url)
        cache_path = self.cache_dir / slug
        return cache_path if cache_path.exists() else None

    def get_cache_by_slug(self, slug: str) -> Optional[Path]:
        """
        Get cache directory by URL slug.

        Args:
            slug: URL slug

        Returns:
            Cache path or None
        """
        cache_path = self.cache_dir / slug
        return cache_path if cache_path.exists() else None

    def list_caches(self) -> list[Path]:
        """
        List all cached pages for this turn.

        Returns:
            List of cache directory paths
        """
        if not self.cache_dir.exists():
            return []
        return [p for p in self.cache_dir.iterdir() if p.is_dir()]

    def get_manifest(self, cache_path: Path) -> dict:
        """Get manifest for a cache."""
        manifest_path = cache_path / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path) as f:
                return json.load(f)
        return {}

    def save_page_content(self, cache_path: Path, content: str) -> None:
        """
        Save page content markdown.

        Args:
            cache_path: Cache directory
            content: Markdown content of the page
        """
        content_path = cache_path / "page_content.md"
        content_path.write_text(content)

        # Update manifest
        manifest = self.get_manifest(cache_path)
        manifest["captured"]["page_content"] = True
        self._save_manifest(cache_path, manifest)

    def get_page_content(self, cache_path: Path) -> Optional[str]:
        """
        Get cached page content.

        Args:
            cache_path: Cache directory

        Returns:
            Page content or None
        """
        content_path = cache_path / "page_content.md"
        if content_path.exists():
            return content_path.read_text()
        return None

    def save_extracted_data(self, cache_path: Path, data: dict) -> None:
        """
        Save extracted structured data.

        Args:
            cache_path: Cache directory
            data: Structured data extracted from the page
        """
        data_path = cache_path / "extracted_data.json"
        with open(data_path, "w") as f:
            json.dump(data, f, indent=2)

        # Update manifest
        manifest = self.get_manifest(cache_path)
        manifest["captured"]["extracted_data"] = True
        self._save_manifest(cache_path, manifest)

    def get_extracted_data(self, cache_path: Path) -> Optional[dict]:
        """
        Get extracted data from cache.

        Args:
            cache_path: Cache directory

        Returns:
            Extracted data or None
        """
        data_path = cache_path / "extracted_data.json"
        if data_path.exists():
            with open(data_path) as f:
                return json.load(f)
        return None

    def save_screenshot(self, cache_path: Path, screenshot_path: Path) -> None:
        """
        Record screenshot path in manifest.

        Args:
            cache_path: Cache directory
            screenshot_path: Path to screenshot file
        """
        manifest = self.get_manifest(cache_path)
        manifest["captured"]["screenshot"] = True
        manifest["screenshot_path"] = str(screenshot_path)
        self._save_manifest(cache_path, manifest)

    def update_content_summary(self, cache_path: Path, summary: dict) -> None:
        """
        Update content summary in manifest.

        The content summary enables quick answers without reading full content.

        Args:
            cache_path: Cache directory
            summary: Summary dict with key information
        """
        manifest = self.get_manifest(cache_path)
        manifest["content_summary"] = summary
        self._save_manifest(cache_path, manifest)

    def set_answerable_questions(self, cache_path: Path, questions: list[str]) -> None:
        """
        Set questions answerable from cache.

        These are question templates that can be answered from cached data.
        Used for cache-first retrieval pattern.

        Args:
            cache_path: Cache directory
            questions: List of question templates
        """
        manifest = self.get_manifest(cache_path)
        manifest["answerable_questions"] = questions
        self._save_manifest(cache_path, manifest)

    def can_answer_from_cache(self, url: str, question: str) -> bool:
        """
        Check if a question can be answered from cache.

        Uses simple keyword matching against answerable_questions templates.

        Args:
            url: Page URL
            question: User question

        Returns:
            True if likely answerable from cache
        """
        cache_path = self.get_cache(url)
        if not cache_path:
            return False

        manifest = self.get_manifest(cache_path)
        answerable = manifest.get("answerable_questions", [])

        # Simple keyword matching
        question_lower = question.lower()
        for template in answerable:
            if template.lower() in question_lower:
                return True

        return False

    def get_cached_answer(self, url: str, question: str) -> Optional[str]:
        """
        Try to answer question from cache.

        Implements cache-first retrieval:
        1. Check content_summary for quick answers
        2. Check extracted_data for structured answers
        3. Return None if no match (caller should use page_content or navigate)

        Args:
            url: Page URL
            question: User question

        Returns:
            Answer if found, None otherwise
        """
        cache_path = self.get_cache(url)
        if not cache_path:
            return None

        manifest = self.get_manifest(cache_path)
        summary = manifest.get("content_summary", {})

        question_lower = question.lower()

        # Check for common patterns in content_summary
        if "how many pages" in question_lower:
            page_info = summary.get("page_info", "")
            if page_info:
                return f"The page has {page_info}"

        if "how many comments" in question_lower:
            count = summary.get("comment_count")
            if count is not None:
                return f"There are {count} comments"

        if "price" in question_lower:
            price = summary.get("price")
            if price:
                return f"The price is {price}"

        if "title" in question_lower or "name" in question_lower:
            title = manifest.get("title") or summary.get("title")
            if title:
                return f"The title is: {title}"

        # Check extracted_data for structured answers
        extracted = self.get_extracted_data(cache_path)
        if extracted:
            # Look for matching keys
            for key, value in extracted.items():
                if key.lower() in question_lower:
                    return f"{key}: {value}"

        return None

    def get_all_cached_urls(self) -> list[dict]:
        """
        Get all cached URLs with their manifests.

        Returns:
            List of dicts with url and manifest info
        """
        results = []
        for cache_path in self.list_caches():
            manifest = self.get_manifest(cache_path)
            if manifest:
                results.append({
                    "url": manifest.get("url"),
                    "title": manifest.get("title"),
                    "visited_at": manifest.get("visited_at"),
                    "captured": manifest.get("captured", {}),
                    "cache_path": str(cache_path),
                })
        return results

    def _url_to_slug(self, url: str) -> str:
        """
        Convert URL to filesystem-safe slug.

        Args:
            url: URL to convert

        Returns:
            Filesystem-safe slug (truncated to 100 characters)
        """
        # Remove protocol
        slug = re.sub(r'^https?://', '', url)
        # Replace special chars with underscores
        slug = re.sub(r'[^\w\-]', '_', slug)
        # Remove consecutive underscores
        slug = re.sub(r'_+', '_', slug)
        # Strip leading/trailing underscores
        slug = slug.strip('_')
        # Truncate to 100 characters
        return slug[:100]

    def _get_turn_number(self) -> int:
        """Extract turn number from directory name."""
        try:
            return int(self.turn_dir.name.split("_")[1])
        except (IndexError, ValueError):
            return 0

    def _save_manifest(self, cache_path: Path, manifest: dict) -> None:
        """Save manifest JSON."""
        manifest_path = cache_path / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
