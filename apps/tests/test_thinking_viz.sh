#!/bin/bash

# Test script for thinking visualization fix
# Run this after starting the Panda stack

echo "Testing Thinking Visualization Fix"
echo "=================================="
echo ""

# 1. Check if services are running
echo "1. Checking services..."
if curl -s http://127.0.0.1:9000/healthz > /dev/null; then
    echo "   ✓ Gateway is running"
else
    echo "   ✗ Gateway not running! Start with: ./start.sh"
    exit 1
fi

# 2. Send a test request and check for trace_id
echo ""
echo "2. Testing API response..."
RESPONSE=$(curl -s -X POST http://127.0.0.1:9000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "panda-chat",
    "messages": [{"role": "user", "content": "What is 2+2?"}],
    "mode": "chat"
  }')

TRACE_ID=$(echo "$RESPONSE" | python3 -c "import json, sys; d=json.load(sys.stdin); print(d.get('trace_id', ''))" 2>/dev/null)

if [ -n "$TRACE_ID" ]; then
    echo "   ✓ Got trace_id: $TRACE_ID"
else
    echo "   ✗ No trace_id in response"
    echo "   Response: $RESPONSE"
    exit 1
fi

# 3. Check if SSE endpoint is accessible
echo ""
echo "3. Testing SSE endpoint..."
SSE_URL="http://127.0.0.1:9000/v1/thinking/$TRACE_ID"
if curl -s -N --max-time 2 "$SSE_URL" 2>/dev/null | head -1 | grep -q "event:"; then
    echo "   ✓ SSE endpoint is accessible"
else
    echo "   ⚠ SSE endpoint may not be streaming (this might be normal if request already completed)"
fi

# 4. Instructions for browser testing
echo ""
echo "4. Browser Testing Instructions:"
echo "   a. Open http://127.0.0.1:9000/ in your browser"
echo "   b. Open browser DevTools Console (F12)"
echo "   c. Look for these messages:"
echo "      - '[Panda] Thinking Visualization BUILD ... LOADED'"
echo "      - '[Thinking] ThinkingVisualizer initialized: ...'"
echo "      - Check that 'panel: true' appears in the initialization"
echo "   d. Send a test message like 'What is 2+2?'"
echo "   e. Watch for:"
echo "      - '[Thinking] Starting visualization for trace: ...'"
echo "      - The thinking panel should appear at the top"
echo ""
echo "5. Expected Console Output:"
echo "   - Should see: '[Thinking] ThinkingVisualizer initialized (DOM already ready)'"
echo "   - Should see: 'panel: true' in the initialization status"
echo "   - Should NOT see: 'CRITICAL: thinking-panel element not found!'"
echo ""
echo "Test complete! Check browser console for detailed diagnostics."