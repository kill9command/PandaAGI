#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apps.services.orchestrator.content_sanitizer import sanitize_html

print("Testing Content Sanitizer...")

# Test 1: Noise removal
html = "<html><head><script>bad</script></head><body><p>Good</p></body></html>"
result = sanitize_html(html, "test.com")
assert "Good" in result["chunks"][0]["text"]
assert "bad" not in result["chunks"][0]["text"]
print("✅ Noise removal")

# Test 2: Price extraction  
html = "<html><body><p>Price: $25.99</p></body></html>"
result = sanitize_html(html, "test.com")
assert "$25.99" in result["structured_data"]["prices_found"]
print("✅ Price extraction")

# Test 3: Metadata
html = "<html><head><title>Test</title></head><body><p>Content</p></body></html>"
result = sanitize_html(html, "test.com")
assert "TITLE: Test" in result["chunks"][0]["text"]
print("✅ Metadata prioritization")

# Test 4: No filtering
html = "<html><body><p>Low quality</p><p>High quality</p></body></html>"
result = sanitize_html(html, "test.com")
content = result["chunks"][0]["text"]
assert "Low quality" in content and "High quality" in content
print("✅ No quality filtering")

# Test 5: Empty handling
result = sanitize_html("", "test.com")
assert result["total_chunks"] == 0
print("✅ Empty HTML handled")

print("\n✅ All tests passed!")
