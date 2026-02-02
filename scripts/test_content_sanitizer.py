#!/usr/bin/env python3
"""
Test script for content sanitizer
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apps.services.orchestrator.content_sanitizer import sanitize_html


def test_noise_removal():
    """Verify noise tags removed"""
    print("Testing noise removal...")

    html = """
    <html>
        <head><script>tracking();</script></head>
        <body>
            <nav>Site Nav</nav>
            <main><p>Real content here</p></main>
            <footer>Footer stuff</footer>
        </body>
    </html>
    """

    result = sanitize_html(html, "https://test.com", max_tokens=500)
    content = result["chunks"][0]["text"] if result["chunks"] else ""

    assert "Real content here" in content, "Real content missing"
    assert "tracking" not in content, "Script content not removed"
    assert "Site Nav" not in content, "Nav not removed"
    assert "Footer stuff" not in content, "Footer not removed"

    print(f"  ✅ Removed noise, kept content")
    print(f"  ✅ Reduction: {result['reduction_pct']}%")


def test_budget_enforcement():
    """Verify hard token limits respected"""
    print("Testing budget enforcement...")

    # Generate large HTML with multiple paragraphs
    paragraphs = []
    for i in range(20):
        para_text = f"Paragraph {i+1}. " + "This is test content. " * 50
        paragraphs.append(f"<p>{para_text}</p>")

    html = "<html><body>" + "".join(paragraphs) + "</body></html>"

    result = sanitize_html(html, "https://test.com", max_tokens=500)

    # Every chunk should be within budget (allow small margin)
    max_allowed = 550
    for chunk in result["chunks"]:
        token_count = chunk["token_estimate"]
        chunk_id = chunk["chunk_id"]
        assert token_count <= max_allowed, f"Chunk {chunk_id} exceeds budget: {token_count} tokens (max: {max_allowed})"

    print(f"  ✅ All {result['total_chunks']} chunks within budget")
    print(f"  ✅ Total tokens available: {result['total_tokens_available']}")


def test_metadata_prioritization():
    """Verify metadata always in chunk 0"""
    print("Testing metadata prioritization...")

    html = """
    <html>
        <head>
            <title>Test Product</title>
            <meta name="description" content="Best product ever">
        </head>
        <body><p>Content here</p></body>
    </html>
    """

    result = sanitize_html(html, "https://test.com")
    chunk_0 = result["chunks"][0]["text"] if result["chunks"] else ""

    assert "TITLE: Test Product" in chunk_0, "Title missing from chunk 0"
    assert "DESCRIPTION: Best product ever" in chunk_0, "Description missing from chunk 0"

    print("  ✅ Metadata in chunk 0")
    print("  ✅ Metadata:", result["metadata"])


