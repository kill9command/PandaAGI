"""
URL Health Checker - Programmatic validation for detecting corrupted/malformed URLs.

This module provides a backup validation layer for URLs that the LLM-based
validator might miss. It detects:
- Repeated character patterns (e.g., 0000000000)
- Placeholder patterns (e.g., /p/NB7Z0{15,})
- Excessive length (>2000 chars)
- Malformed structure

Used by:
- Phase 6 Validation (unified_flow.py) - Pre-check before LLM validation
- Can be used by other components that need URL validation

Author: Fix for corrupted URL issue (turn 112)
Date: 2026-01-26
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple
from urllib.parse import urlparse


class URLHealthStatus(Enum):
    """Status of URL health check."""
    HEALTHY = "healthy"
    MALFORMED = "malformed"      # Structurally invalid
    SUSPICIOUS = "suspicious"    # Looks like placeholder/garbage
    TRUNCATED = "truncated"      # Appears cut off


@dataclass
class URLHealthReport:
    """Report from URL health check."""
    url: str
    status: URLHealthStatus
    issues: List[str]
    confidence: float  # How confident we are in the diagnosis (0.0-1.0)

    @property
    def is_healthy(self) -> bool:
        """Check if URL passed all health checks."""
        return self.status == URLHealthStatus.HEALTHY

    @property
    def is_usable(self) -> bool:
        """Check if URL is usable (healthy or only minor issues)."""
        return self.status in (URLHealthStatus.HEALTHY, URLHealthStatus.TRUNCATED)


def check_url_health(url: str) -> URLHealthReport:
    """
    Comprehensive URL health check.

    This is the SINGLE SOURCE OF TRUTH for programmatic URL validation.
    It complements the LLM-based validation in the validator prompt.

    Args:
        url: The URL to check

    Returns:
        URLHealthReport with status, issues, and confidence

    Examples:
        >>> report = check_url_health("https://newegg.com/p/N82E16834156123")
        >>> report.is_healthy
        True

        >>> report = check_url_health("https://newegg.com/p/NB7Z0000000000000000")
        >>> report.is_healthy
        False
        >>> report.issues
        ["Repeated character pattern: '0' x 16"]
    """
    issues = []

    # Check 1: Empty or whitespace-only
    if not url or not url.strip():
        return URLHealthReport(
            url=url or "",
            status=URLHealthStatus.MALFORMED,
            issues=["Empty URL"],
            confidence=1.0
        )

    url = url.strip()

    # Check 2: Excessive length (URLs over 2000 chars are almost always garbage)
    if len(url) > 2000:
        issues.append(f"Excessive length: {len(url)} chars (max 2000)")

    # Check 3: Repeated characters (the zeros pattern from turn 112)
    repeated = _detect_repeated_chars(url)
    if repeated:
        issues.append(f"Repeated character pattern: {repeated}")

    # Check 4: Placeholder patterns
    placeholder = _detect_placeholder_pattern(url)
    if placeholder:
        issues.append(f"Placeholder pattern: {placeholder}")

    # Check 5: Valid URL structure
    try:
        parsed = urlparse(url)
        if not parsed.scheme:
            issues.append("Missing URL scheme (http/https)")
        if not parsed.netloc:
            issues.append("Missing domain")
    except Exception as e:
        issues.append(f"URL parse error: {e}")

    # Determine status based on issues
    if not issues:
        return URLHealthReport(
            url=url,
            status=URLHealthStatus.HEALTHY,
            issues=[],
            confidence=1.0
        )

    # Categorize the issues
    has_repeated = any("Repeated" in i for i in issues)
    has_placeholder = any("Placeholder" in i for i in issues)
    has_length = any("length" in i.lower() for i in issues)
    has_structure = any("scheme" in i.lower() or "domain" in i.lower() or "parse" in i.lower() for i in issues)

    if has_repeated or has_placeholder:
        status = URLHealthStatus.SUSPICIOUS
        confidence = 0.95
    elif has_length:
        status = URLHealthStatus.TRUNCATED
        confidence = 0.8
    elif has_structure:
        status = URLHealthStatus.MALFORMED
        confidence = 0.9
    else:
        status = URLHealthStatus.SUSPICIOUS
        confidence = 0.7

    return URLHealthReport(
        url=url,
        status=status,
        issues=issues,
        confidence=confidence
    )


def _detect_repeated_chars(url: str) -> Optional[str]:
    """
    Detect suspicious repeated character patterns.

    The turn 112 bug had URLs like:
    https://newegg.com/p/NB7Z0000000000000000000000...

    We detect 10+ of the same character in a row as suspicious.
    """
    # Look for 10+ of the same character in a row
    match = re.search(r'(.)\1{9,}', url)
    if match:
        char = match.group(1)
        count = len(match.group(0))
        return f"'{char}' x {count}"
    return None


def _detect_placeholder_pattern(url: str) -> Optional[str]:
    """
    Detect common placeholder URL patterns.

    These patterns indicate the URL is fake/generated, not a real product link.
    """
    patterns = [
        # Newegg-style with lots of zeros
        (r'/p/[A-Z0-9]{2,6}0{8,}', "Newegg-style zeros placeholder"),
        # Amazon-style with lots of zeros
        (r'/dp/B0{8,}', "Amazon-style zeros placeholder"),
        # Generic numeric placeholder
        (r'/product-\d{6,}$', "Generic numeric placeholder"),
        # Template variables
        (r'\{[^}]+\}', "Template variable in URL"),
        # Bracket placeholders
        (r'\[[^\]]+\]', "Bracket placeholder in URL"),
        # Sequential numbers
        (r'/id/\d{10,}', "Sequential ID placeholder"),
        # Just domain with trailing slash only
        (r'^https?://[^/]+/?$', "Domain only - no product path"),
    ]

    for pattern, name in patterns:
        if re.search(pattern, url):
            return name

    return None


def check_urls_in_text(text: str) -> List[URLHealthReport]:
    """
    Extract and check all URLs in a text.

    Args:
        text: Text that may contain URLs (e.g., a response markdown)

    Returns:
        List of URLHealthReport for each URL found
    """
    # Extract URLs using a simple regex
    # This catches most markdown links and plain URLs
    url_pattern = r'https?://[^\s\)\]>"\']+'
    urls = re.findall(url_pattern, text)

    # Also extract from markdown link syntax [text](url)
    markdown_links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', text)
    for _, url in markdown_links:
        if url.startswith('http') and url not in urls:
            urls.append(url)

    # Check each URL
    reports = []
    for url in urls:
        # Clean up trailing punctuation that might have been captured
        url = url.rstrip('.,;:!?')
        report = check_url_health(url)
        reports.append(report)

    return reports


def get_unhealthy_urls(text: str) -> Tuple[List[str], List[str]]:
    """
    Convenience function to get lists of unhealthy URLs from text.

    Args:
        text: Text that may contain URLs

    Returns:
        Tuple of (unhealthy_urls, issues_list)
        - unhealthy_urls: List of URLs that failed health check
        - issues_list: List of issue descriptions
    """
    reports = check_urls_in_text(text)

    unhealthy_urls = []
    issues_list = []

    for report in reports:
        if not report.is_healthy:
            unhealthy_urls.append(report.url)
            for issue in report.issues:
                issues_list.append(f"{report.url[:50]}... - {issue}")

    return unhealthy_urls, issues_list
