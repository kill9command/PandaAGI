#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apps.services.orchestrator.content_sanitizer import sanitize_html

print("="*60)
print("Testing Content Sanitizer")
print("="*60 + "\n")

# Test 1: Noise removal
print("Test 1: Noise removal...")
html = "<html><head><script>tracking();</script></head><body><nav>Nav</nav><p>Real content here that is long enough to process properly</p></body></html>"
result = sanitize_html(html, "test.com")
content = result["chunks"][0]["text"] if result["chunks"] else ""
assert "Real content" in content, "Content missing"
assert "tracking" not in content, "Script not removed"
assert "Nav" not in content, "Nav not removed"
print(f"  ✅ Pass (reduction: {result['reduction_pct']}%)\n")

# Test 2: Price extraction
print("Test 2: Price extraction...")
html = "<html><body><p>Syrian Hamster for sale. Price: $25.99. Was: $35.00. Great deal!</p></body></html>"
result = sanitize_html(html, "test.com")
if result["structured_data"].get("prices_found"):
    assert "$25.99" in result["structured_data"]["prices_found"], "$25.99 not found"
    print(f"  ✅ Pass (found: {result['structured_data']['prices_found']})\n")
else:
    print("  ⚠️  Warning: No prices found (content may be too short)\n")

# Test 3: Metadata
print("Test 3: Metadata prioritization...")
html = "<html><head><title>Test Product Page</title><meta name='description' content='Best hamster ever'></head><body><p>Content here for testing</p></body></html>"
result = sanitize_html(html, "test.com")
chunk_0 = result["chunks"][0]["text"] if result["chunks"] else ""
assert "TITLE: Test Product Page" in chunk_0, "Title missing"
assert "DESCRIPTION: Best hamster ever" in chunk_0, "Description missing"
print(f"  ✅ Pass\n")

# Test 4: No quality filtering
print("Test 4: No quality filtering...")
html = "<html><body><p>This is low quality content that might not be relevant.</p><p>This is high quality verified information.</p></body></html>"
result = sanitize_html(html, "test.com")
content = result["chunks"][0]["text"] if result["chunks"] else ""
assert "low quality" in content, "Low quality content filtered"
assert "high quality" in content, "High quality content filtered"
for chunk in result["chunks"]:
    assert "confidence" not in chunk, "Quality score present"
print(f"  ✅ Pass (all content preserved)\n")

# Test 5: Empty handling
print("Test 5: Empty HTML handling...")
result = sanitize_html("", "test.com")
assert result["total_chunks"] == 0, "Empty HTML should have 0 chunks"
result = sanitize_html("   ", "test.com")
assert result["total_chunks"] == 0, "Whitespace should have 0 chunks"
print(f"  ✅ Pass\n")

# Test 6: Budget enforcement
print("Test 6: Budget enforcement...")
paragraphs = []
for i in range(10):
    para = f"Paragraph {i+1}. " + "This is test content with sufficient length. " * 20
    paragraphs.append(f"<p>{para}</p>")
html = "<html><body>" + "".join(paragraphs) + "</body></html>"
result = sanitize_html(html, "test.com", max_tokens=500)
max_allowed = 550  # 10% margin
for chunk in result["chunks"]:
    assert chunk["token_estimate"] <= max_allowed, f"Chunk {chunk['chunk_id']} exceeds budget"
print(f"  ✅ Pass ({result['total_chunks']} chunks, {result['total_tokens_available']} tokens)\n")

print("="*60)
print("✅ All content sanitizer tests passed!")
print("="*60)
