#!/bin/bash

# Test Meta-Reflection System
# Tests different query types to verify meta-reflection works correctly

GATEWAY_URL="http://127.0.0.1:9000/v1/chat/completions"

echo "========================================"
echo "Meta-Reflection Test Suite"
echo "========================================"
echo ""

# Test 1: Clear query (should PROCEED)
echo "Test 1: Clear query - 'find Syrian hamster breeders online'"
echo "Expected: PROCEED (confidence >= 0.8)"
echo "----------------------------------------"
curl -s -X POST "$GATEWAY_URL" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-coder",
    "messages": [
      {"role": "user", "content": "find Syrian hamster breeders online"}
    ]
  }' | jq -r '.choices[0].message.content' | head -20
echo ""
echo "Checking meta-reflection stats..."
curl -s http://127.0.0.1:9000/debug/meta-reflection | jq .
echo ""
echo ""

# Test 2: Ambiguous query (might need ANALYSIS or CLARIFICATION)
echo "Test 2: Ambiguous query - 'find those things'"
echo "Expected: NEEDS_CLARIFICATION (confidence < 0.4)"
echo "----------------------------------------"
curl -s -X POST "$GATEWAY_URL" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-coder",
    "messages": [
      {"role": "user", "content": "find those things"}
    ]
  }' | jq -r '.choices[0].message.content' | head -20
echo ""
echo "Checking meta-reflection stats..."
curl -s http://127.0.0.1:9000/debug/meta-reflection | jq .
echo ""
echo ""

# Test 3: Simple greeting (might PROCEED or CLARIFICATION depending on implementation)
echo "Test 3: Greeting - 'hello'"
echo "Expected: Varies (could be PROCEED or NEEDS_CLARIFICATION)"
echo "----------------------------------------"
curl -s -X POST "$GATEWAY_URL" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-coder",
    "messages": [
      {"role": "user", "content": "hello"}
    ]
  }' | jq -r '.choices[0].message.content' | head -20
echo ""
echo "Checking meta-reflection stats..."
curl -s http://127.0.0.1:9000/debug/meta-reflection | jq .
echo ""
echo ""

echo "========================================"
echo "Test Complete!"
echo "========================================"
echo "Review gateway.log for detailed meta-reflection decisions"
echo "Use: tail -100 gateway.log | grep MetaReflect"
