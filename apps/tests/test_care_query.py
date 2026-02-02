#!/usr/bin/env python3
import requests
import json

url = "http://127.0.0.1:9000/v1/chat/completions"
payload = {
    "messages": [
        {"role": "user", "content": "What food and cage should I get for my Syrian hamster?"}
    ],
    "mode": "chat"
}

response = requests.post(url, json=payload)
print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    print(f"Response: {data.get('choices', [{}])[0].get('message', {}).get('content', 'No content')[:500]}")
else:
    print(f"Error: {response.text}")