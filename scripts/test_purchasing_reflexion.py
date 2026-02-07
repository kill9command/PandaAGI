#!/usr/bin/env python3
"""
Direct test of purchasing lookup with reflexion loop.
"""

import requests
import json

# Test with a product that might need refinement
test_product = "Arduino Nano microcontroller"

data = {
    "item": test_product,
    "max_results": 5
}

endpoint_url = "http://127.0.0.1:8090/purchasing.lookup"

print(f"Testing purchasing lookup with reflexion")
print("=" * 60)
print(f"Product: {test_product}")
print("=" * 60)

response = requests.post(endpoint_url, json=data, timeout=60)

if response.status_code == 200:
    print("✓ Successfully called /purchasing.lookup\n")
    response_data = response.json()

    print(f"Status: {response_data.get('status', 'N/A')}")
    print(f"Offers found: {len(response_data.get('offers', []))}")

    if response_data.get('offers'):
        print("\nTop offer:")
        top = response_data['offers'][0]
        print(f"  Title: {top.get('title', 'N/A')}")
        print(f"  Price: {top.get('price_text', 'N/A')}")
        print(f"  Source: {top.get('source', 'N/A')}")
else:
    print(f"✗ Error: {response.status_code}")
    print(response.text)
