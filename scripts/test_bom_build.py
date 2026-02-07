
import requests
import json

# The URL of the Thingiverse page for the Garud-500 drone
url = "https://www.thingiverse.com/thing:2740739"

# The data to send to the /bom.build endpoint
data = {
    "url": url,
    "repo": "/path/to/pandaagi/apps/docs/",
    "filename": "garud-500-bom-reflexion-test",
    "format": "csv",
    "use_serpapi": True,  # Enable reflexion testing
    "serpapi_max_parts": 3,  # Limit to 3 parts to save API quota
}

# The URL of the /bom.build endpoint
endpoint_url = "http://127.0.0.1:8090/bom.build"

# Send the request to the /bom.build endpoint
response = requests.post(endpoint_url, data=json.dumps(data))

# Check the response
if response.status_code == 200:
    print("✓ Successfully called /bom.build endpoint\n")
    response_data = response.json()
    print(f"Status: {response_data['status']}")
    print(f"Message: {response_data['message']}")
    print(f"Spreadsheet path: {response_data['spreadsheet_path']}")
    print(f"Number of rows: {len(response_data['rows'])}")

    # Show reflexion activity
    print("\n" + "=" * 60)
    print("REFLEXION ACTIVITY:")
    print("=" * 60)
    messages = response_data.get('messages', [])
    reflexion_count = 0
    for msg in messages:
        if 'Refining search' in str(msg):
            print(f"✓ {msg}")
            reflexion_count += 1
        elif 'Found pricing' in str(msg):
            print(f"✓ {msg}")

    if reflexion_count > 0:
        print(f"\n✓ Reflexion loop activated {reflexion_count} time(s)")
    else:
        print("\nℹ No query refinements needed (all parts found on first attempt)")

    # Show all messages for debugging
    print("\n" + "=" * 60)
    print("ALL MESSAGES:")
    print("=" * 60)
    for msg in messages:
        print(f"  {msg}")

    print(f"\nSerpAPI calls: {response_data.get('serpapi_calls', 0)}")
else:
    print(f"✗ Error calling /bom.build endpoint: {response.status_code}")
    print(response.text)
