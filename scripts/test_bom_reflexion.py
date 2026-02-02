#!/usr/bin/env python3
"""
Test BOM builder with reflexion loop for product search.

Tests the new LLM-driven query refinement when products are hard to find.
"""

import requests
import json

# Test BOM with challenging parts that might need query refinement
test_bom_text = """
Part Name,Quantity,Notes
ESP32-WROOM,1,WiFi microcontroller module
LiPo Battery,1,3.7V 2000mAh
Servo Motor,4,9g micro servo
Carbon Fiber Tube,4,3mm diameter 200mm length
"""

# The data to send to the /bom.build endpoint
data = {
    "text": test_bom_text,
    "repo": "/tmp",
    "filename": "reflexion_test_bom",
    "format": "csv",
    "use_serpapi": True,  # Enable pricing search
    "serpapi_max_parts": 4  # Test all parts
}

# The URL of the /bom.build endpoint
endpoint_url = "http://127.0.0.1:8090/bom.build"

print("Testing BOM Builder with Reflexion Loop")
print("=" * 60)
print(f"Test parts: ESP32-WROOM, LiPo Battery, Servo Motor, Carbon Fiber Tube")
print(f"SerpAPI enabled: {data['use_serpapi']}")
print("=" * 60)

# Send the request to the /bom.build endpoint
print("\nSending request to /bom.build...")
response = requests.post(endpoint_url, json=data, timeout=120)

# Check the response
if response.status_code == 200:
    print("✓ Successfully called /bom.build endpoint\n")
    response_data = response.json()

    print(f"Status: {response_data['status']}")
    print(f"Message: {response_data.get('message', 'N/A')}")
    print(f"Spreadsheet path: {response_data.get('spreadsheet_path', 'N/A')}")
    print(f"Number of rows: {len(response_data.get('rows', []))}")

    # Show detailed results
    print("\n" + "=" * 60)
    print("RESULTS:")
    print("=" * 60)

    for row in response_data.get('rows', []):
        part = row.get('part', 'Unknown')
        price = row.get('price_text', row.get('price', 'N/A'))
        retailer = row.get('retailer', 'N/A')
        print(f"\n{part}:")
        print(f"  Price: {price}")
        print(f"  Retailer: {retailer}")
        print(f"  Pricing source: {row.get('pricing_source', 'N/A')}")

    # Check messages for reflexion activity
    messages = response_data.get('messages', [])
    print("\n" + "=" * 60)
    print("REFLEXION ACTIVITY:")
    print("=" * 60)

    refinement_count = 0
    for msg in messages:
        if 'Refining search' in str(msg):
            print(f"✓ {msg}")
            refinement_count += 1
        elif 'Found pricing' in str(msg):
            print(f"✓ {msg}")

    if refinement_count > 0:
        print(f"\n✓ Reflexion loop activated {refinement_count} time(s)")
    else:
        print("\nℹ No query refinements needed (all parts found on first attempt)")

    # Show SerpAPI usage
    serpapi_calls = response_data.get('serpapi_calls', 0)
    print(f"\nSerpAPI calls made: {serpapi_calls}")

else:
    print(f"✗ Error calling /bom.build endpoint: {response.status_code}")
    print(response.text)
