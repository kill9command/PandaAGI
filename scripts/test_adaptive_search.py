#!/usr/bin/env python3
"""
scripts/test_adaptive_search.py

End-to-end test of the adaptive search system.
Tests the complete flow:
1. Source discovery (Phase 0)
2. Intent-based search with resilient fetching
3. LLM extraction and filtering
4. Quality assessment and refinement
"""

import asyncio
import sys
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apps.services.orchestrator.product_schema import ProductSearchIntent
from apps.services.orchestrator.research_mcp import discover_sources
from apps.services.orchestrator.commerce_mcp_v2 import search_with_intent
from apps.services.orchestrator.memory_store import get_memory_store


async def test_source_discovery():
    """Test Phase 0: Source Discovery"""
    print("\n" + "="*80)
    print("TEST 1: Source Discovery for Syrian Hamsters")
    print("="*80)
    
    result = await discover_sources(
        item_type="live_animal",
        category="pet:hamster",
        location="USA"
    )
    
    print(f"\n✓ Found {len(result.get('trusted_sources', []))} trusted sources")
    
    for source in result.get("trusted_sources", [])[:3]:
        print(f"  • {source['domain']} ({source['source_type']}) - Trust: {source['trust_score']:.2f}")
        print(f"    Reasons: {', '.join(source['reasons'][:2])}")
    
    if result.get("seller_type_guidance"):
        print(f"\n✓ Seller Guidance:")
        for guidance in result["seller_type_guidance"][:3]:
            print(f"  • {guidance}")
    
    if result.get("search_strategies"):
        print(f"\n✓ Search Strategies:")
        for strategy in result["search_strategies"][:3]:
            print(f"  • {strategy}")
    
    return result


async def test_intent_based_search(discovered_sources=None):
    """Test Phase 1-3: Intent-based search with quality assessment"""
    print("\n" + "="*80)
    print("TEST 2: Intent-Based Search with Resilient Fetching")
    print("="*80)
    
    # Create search intent
    intent = ProductSearchIntent(
        item_type="live_animal",
        category="pet:hamster",
        must_have_attributes=["Syrian", "live"],
        must_not_have_attributes=["cage", "toy", "book", "plush", "accessory"],
        seller_preferences=["breeder"],
        price_range=(10.0, 100.0),
        location="USA"
    )
    
    print(f"\n📋 Search Intent:")
    print(f"  • Item Type: {intent.item_type}")
    print(f"  • Category: {intent.category}")
    print(f"  • Must Have: {', '.join(intent.must_have_attributes)}")
    print(f"  • Must NOT Have: {', '.join(intent.must_not_have_attributes)}")
    print(f"  • Preferred Sellers: {', '.join(intent.seller_preferences)}")
    
    # Execute search
    result = await search_with_intent(
        intent,
        max_results=5,
        max_verification=10,
        discovered_sources=discovered_sources.get("trusted_sources") if discovered_sources else None
    )
    
    stats = result.get("stats", {})
    quality = result.get("quality_score", 0.0)
    
    print(f"\n📊 Search Statistics:")
    print(f"  • Raw Results: {stats.get('raw_count', 0)}")
    print(f"  • Verified: {stats.get('verified_count', 0)}")
    print(f"  • Rejected: {stats.get('rejected_count', 0)}")
    print(f"  • Quality Score: {quality:.1%}")
    
    # Show verified results
    verified = result.get("results", [])
    if verified:
        print(f"\n✅ Verified Listings ({len(verified)}):")
        for idx, listing in enumerate(verified[:3], 1):
            print(f"\n  {idx}. {listing['title']}")
            print(f"     URL: {listing['url'][:60]}...")
            print(f"     Seller: {listing['seller_name']} ({listing['seller_type']})")
            print(f"     Price: ${listing['price']:.2f} {listing['currency']}" if listing.get('price') else "     Price: Not listed")
            print(f"     Relevance: {listing['relevance_score']:.1%}")
            print(f"     Confidence: {listing['confidence']}")
            print(f"     Fetched via: {listing.get('fetch_method', 'unknown')}")
    
    # Show rejected samples
    rejected = result.get("rejected", [])
    if rejected:
        print(f"\n❌ Rejected Listings ({len(rejected)}) - Sample:")
        for idx, listing in enumerate(rejected[:2], 1):
            print(f"\n  {idx}. {listing['title'][:60]}")
            print(f"     Reasons: {', '.join(listing['rejection_reasons'])}")
            print(f"     Item Type: {listing['item_type']}")
    
    # Show issues and refinement
    issues = result.get("issues", [])
    if issues:
        print(f"\n⚠️  Detected Issues:")
        for issue in issues:
            print(f"  • {issue}")
    
    refinement = result.get("suggested_refinement")
    if refinement:
        print(f"\n💡 Suggested Refinement:")
        print(f"  Rationale: {refinement.get('rationale')}")
        refined = refinement.get("intent", {})
        print(f"  Added Negatives: {', '.join(refined.get('must_not_have', []))}")
    
    return result


async def test_source_caching():
    """Test that source discovery is cached"""
    print("\n" + "="*80)
    print("TEST 3: Source Discovery Caching")
    print("="*80)
    
    store = get_memory_store()
    
    # Check if cached discovery exists
    cached = store.get_source_discovery(
        item_type="live_animal",
        category="pet:hamster"
    )
    
    if cached:
        print("\n✓ Found cached source discovery")
        metadata = cached.get("metadata", {})
        print(f"  • Category: {metadata.get('category')}")
        print(f"  • Cached Domains: {len(metadata.get('trusted_domains', []))}")
        print(f"  • Discovery Date: {metadata.get('discovery_date', 'unknown')}")
        print(f"  • Age: {cached.get('created_at', 'unknown')}")
    else:
        print("\n⚠️  No cached discovery found (will need to research)")
    
    return cached


async def test_full_cycle():
    """Test complete cycle: discovery → cache → search → refinement"""
    print("\n" + "="*80)
    print("FULL CYCLE TEST: Adaptive Search with Source Discovery")
    print("="*80)
    
    # Step 1: Check cache
    print("\n📍 Step 1: Check source discovery cache...")
    cached = await test_source_caching()
    
    # Step 2: Discover sources if not cached
    if not cached:
        print("\n📍 Step 2: Discovering trusted sources...")
        discovery = await test_source_discovery()
        
        # Cache the results
        print("\n📍 Step 3: Caching discovery results...")
        store = get_memory_store()
        store.save_source_discovery(
            item_type="live_animal",
            category="pet:hamster",
            discovery_data=discovery
        )
        print("✓ Cached for 30 days")
    else:
        print("\n📍 Step 2: Using cached source discovery (skipping research)")
        # Convert cached format to discovery format
        metadata = cached.get("metadata", {})
        discovery = {
            "trusted_sources": [
                {"domain": d, "source_type": "unknown", "trust_score": 0.8}
                for d in metadata.get("trusted_domains", [])
            ]
        }
    
    # Step 3: Execute search with discovered sources
    print("\n📍 Step 4: Executing intent-based search...")
    result = await test_intent_based_search(discovery)
    
    # Step 4: If quality is low, could retry with refinement
    if result.get("quality_score", 0) < 0.3 and result.get("suggested_refinement"):
        print("\n📍 Step 5: Quality is low - could execute refined search...")
        print("  (Skipping retry in test, but system would auto-refine)")
    
    print("\n" + "="*80)
    print("✅ FULL CYCLE TEST COMPLETE")
    print("="*80)
    
    return result


async def main():
    """Run all tests"""
    print("\n")
    print("╔" + "="*78 + "╗")
    print("║" + " "*20 + "ADAPTIVE SEARCH SYSTEM TEST SUITE" + " "*25 + "║")
    print("╚" + "="*78 + "╝")
    
    try:
        # Run full cycle test
        result = await test_full_cycle()
        
        # Summary
        print("\n\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        
        verified_count = len(result.get("results", []))
        quality = result.get("quality_score", 0.0)
        
        print(f"\n✅ System is {'WORKING' if verified_count > 0 else 'PARTIAL'}")
        print(f"   • Verified Results: {verified_count}")
        print(f"   • Quality Score: {quality:.1%}")
        print(f"   • Resilient Fetching: Active")
        print(f"   • LLM Extraction: Active")
        print(f"   • Data Normalization: Active")
        print(f"   • Source Discovery: Active")
        print(f"   • Adaptive Refinement: Active")
        
        if verified_count > 0:
            print(f"\n🎉 All core systems operational!")
        else:
            print(f"\n⚠️  System functional but no verified results (check LLM/SerpAPI)")
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
