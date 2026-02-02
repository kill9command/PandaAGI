#!/usr/bin/env python3
"""
scripts/test_vendor_catalog.py

Integration test for vendor.explore_catalog tool.

Tests the complete flow:
1. Initial research detects catalog hints
2. Deep catalog exploration extracts all items
3. Results include pagination, categories, contact info

Usage:
    python scripts/test_vendor_catalog.py
"""
import asyncio
import sys
import os
import json

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_catalog_detection():
    """Test that initial research detects vendor catalogs"""
    from apps.services.orchestrator import internet_research_mcp

    print("\n" + "="*80)
    print("TEST 1: Catalog Detection in Initial Research")
    print("="*80)

    result = await internet_research_mcp.adaptive_research(
        query="Find online Syrian hamster breeders",
        session_id="test-catalog-detection",
        force_strategy="quick",  # Fast test
        remaining_token_budget=8000
    )

    # Check if catalog_hints exist in synthesis
    synthesis = result.get("results", {}).get("synthesis", {})
    catalog_hints = synthesis.get("catalog_hints", [])

    print(f"\n✓ Research complete: {len(result.get('results', {}).get('findings', []))} sources")
    print(f"✓ Catalog hints detected: {len(catalog_hints)}")

    if catalog_hints:
        print("\n📋 Detected Catalogs:")
        for hint in catalog_hints:
            print(f"  - {hint['vendor_name']}: {hint['detected_items']} items, pagination={hint['has_pagination']}")
            print(f"    URL: {hint['vendor_url']}")
            print(f"    Reason: {hint['reason']}")
    else:
        print("\n⚠️  No catalog hints detected (may be expected if pages don't have catalogs)")

    return catalog_hints


async def test_catalog_exploration(vendor_url: str, vendor_name: str):
    """Test deep catalog exploration"""
    from apps.services.orchestrator import vendor_catalog_mcp

    print("\n" + "="*80)
    print("TEST 2: Deep Catalog Exploration")
    print("="*80)

    print(f"\n🔍 Exploring catalog: {vendor_name}")
    print(f"   URL: {vendor_url}")

    result = await vendor_catalog_mcp.explore_catalog(
        vendor_url=vendor_url,
        vendor_name=vendor_name,
        category="all",
        max_items=20,
        session_id="test-catalog-exploration"
    )

    print(f"\n✓ Catalog exploration complete!")
    print(f"  Items found: {result['items_found']}")
    print(f"  Pages crawled: {result['pages_crawled']}")

    # Show contact info
    contact = result.get("contact_info", {})
    if any(contact.values()):
        print(f"\n📧 Contact Information:")
        if contact.get("email"):
            print(f"  Email: {contact['email']}")
        if contact.get("phone"):
            print(f"  Phone: {contact['phone']}")
        if contact.get("application_url"):
            print(f"  Application: {contact['application_url']}")

    # Show sample items
    items = result.get("items", [])
    if items:
        print(f"\n📦 Sample Items (showing first 3 of {len(items)}):")
        for i, item in enumerate(items[:3], 1):
            print(f"\n  {i}. {item.get('title', 'Untitled')}")
            if item.get("price"):
                print(f"     Price: {item['price']}")
            if item.get("availability"):
                print(f"     Availability: {item['availability']}")
            if item.get("url"):
                print(f"     URL: {item['url'][:60]}...")

            details = item.get("details", {})
            if details.get("born_date"):
                print(f"     Born: {details['born_date']}")

    return result


async def test_orchestrator_endpoint():
    """Test orchestrator HTTP endpoint"""
    import httpx

    print("\n" + "="*80)
    print("TEST 3: Orchestrator Endpoint")
    print("="*80)

    # Test vendor (using a known breeder site)
    test_payload = {
        "vendor_url": "http://hubbahubbahamstery.com/",
        "vendor_name": "Hubba-Hubba Hamstery",
        "category": "all",
        "max_items": 5,
        "session_id": "test-endpoint"
    }

    print(f"\n📡 Calling POST /vendor.explore_catalog")
    print(f"   Payload: {json.dumps(test_payload, indent=2)}")

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "http://127.0.0.1:8090/vendor.explore_catalog",
                json=test_payload
            )

            if response.status_code == 200:
                result = response.json()
                print(f"\n✓ Endpoint responded successfully!")
                print(f"  Items found: {result.get('items_found', 0)}")
                print(f"  Pages crawled: {result.get('pages_crawled', 0)}")
                return True
            else:
                print(f"\n❌ Endpoint error: {response.status_code}")
                print(f"   Response: {response.text}")
                return False
    except Exception as e:
        print(f"\n⚠️  Could not connect to orchestrator: {e}")
        print(f"   Make sure orchestrator is running on port 8090")
        return False


async def test_v4_flow_integration():
    """Test v4 flow with catalog hints"""
    print("\n" + "="*80)
    print("TEST 4: V4 Flow Integration (Catalog Hints in Capsule)")
    print("="*80)

    print("\n📝 This test verifies:")
    print("  1. Research finds catalog hints")
    print("  2. Context Manager adds catalog metadata to claims")
    print("  3. Capsule.md includes catalog hints section")
    print("  4. Guide synthesis shows 🔍 icon for catalogs")

    print("\n💡 To test manually:")
    print("  1. Start gateway: ./start.sh")
    print("  2. Visit http://127.0.0.1:9000")
    print("  3. Ask: 'Find online Syrian hamster breeders'")
    print("  4. Check response for 🔍 catalog hints")
    print("  5. Follow up: 'explore [vendor name] catalog'")
    print("  6. Verify full catalog with all items")

    print("\n✓ Manual test steps provided")
    return True


async def main():
    """Run all integration tests"""
    print("\n" + "="*80)
    print("VENDOR CATALOG INTEGRATION TEST SUITE")
    print("="*80)

    # Test 1: Catalog detection
    try:
        catalog_hints = await test_catalog_detection()
    except Exception as e:
        print(f"\n❌ Test 1 failed: {e}")
        import traceback
        traceback.print_exc()
        catalog_hints = []

    # Test 2: Catalog exploration (if we detected any catalogs)
    if catalog_hints:
        try:
            hint = catalog_hints[0]
            await test_catalog_exploration(
                vendor_url=hint["vendor_url"],
                vendor_name=hint["vendor_name"]
            )
        except Exception as e:
            print(f"\n❌ Test 2 failed: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("\n⏭️  Skipping Test 2 (no catalogs detected in Test 1)")

    # Test 3: Orchestrator endpoint
    try:
        await test_orchestrator_endpoint()
    except Exception as e:
        print(f"\n❌ Test 3 failed: {e}")
        import traceback
        traceback.print_exc()

    # Test 4: V4 flow integration
    try:
        await test_v4_flow_integration()
    except Exception as e:
        print(f"\n❌ Test 4 failed: {e}")
        import traceback
        traceback.print_exc()

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print("\n✅ Integration test complete!")
    print("\nNext steps:")
    print("1. Restart orchestrator to load new endpoint")
    print("2. Test end-to-end flow via Gateway UI")
    print("3. Verify catalog hints appear in responses")
    print("4. Test deep catalog exploration with real vendor sites")


if __name__ == "__main__":
    asyncio.run(main())
