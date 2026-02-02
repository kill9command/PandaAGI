#!/usr/bin/env python3
import requests
import json

url = "http://127.0.0.1:9000/v1/chat/completions"
payload = {
    "messages": [
        {"role": "user", "content": "My favorite hamster is the Syrian hamster"},
        {"role": "assistant", "content": "That is a great choice! Syrian hamsters are popular pets."},
        {"role": "user", "content": "Can you find me some for sale online?"}
    ],
    "mode": "chat"
}

response = requests.post(url, json=payload)
print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    print(f"Response: {data.get('choices', [{}])[0].get('message', {}).get('content', 'No content')}")
else:
    print(f"Error: {response.text}")