#!/bin/bash
set -e

echo "=== Phase 3 LLM Evaluation Smoke Test ==="

# Check env vars
if ! grep -q "PHASE3_LLM_EVALUATION=true" .env 2>/dev/null; then
    echo "❌ PHASE3_LLM_EVALUATION not enabled in .env"
    echo "   Add: PHASE3_LLM_EVALUATION=true"
    exit 1
fi

echo "✅ PHASE3_LLM_EVALUATION enabled"

# Check if services are running
if ! pgrep -f "uvicorn project_build_instructions.gateway.app" > /dev/null; then
    echo "⚠️  Gateway not running, starting services..."
    ./start.sh
    sleep 5
else
    echo "✅ Services already running"
fi

# Health check
echo "Checking service health..."
./server_health.sh || exit 1

# Send test request
echo "Sending test request..."
RESPONSE=$(curl -s -X POST http://localhost:9000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-coder",
    "messages": [
      {"role": "user", "content": "Where can I buy Syrian hamsters in Oregon?"}
    ]
  }')

# Check for Phase 3 execution in logs
echo "Checking orchestrator logs for Phase 3 activity..."
PHASE3_COUNT=$(tail -200 tool_server.log | grep -c "\[Phase 3\]" || true)

if [ "$PHASE3_COUNT" -gt 0 ]; then
    echo "✅ Phase 3 executed successfully ($PHASE3_COUNT log entries)"
    echo ""
    echo "Recent Phase 3 log entries:"
    tail -200 tool_server.log | grep "\[Phase 3\]" | tail -5
else
    echo "⚠️  Phase 3 did not execute"
    echo "   This may be normal if no cached claims exist yet"
    echo "   Run the same query twice to trigger cache evaluation"
fi

# Check response quality
echo ""
echo "Validating response format..."
if echo "$RESPONSE" | jq -e '.choices[0].message.content' > /dev/null 2>&1; then
    echo "✅ Response received successfully"
    CONTENT=$(echo "$RESPONSE" | jq -r '.choices[0].message.content')
    echo ""
    echo "Response preview:"
    echo "$CONTENT" | head -c 200
    echo "..."
else
    echo "❌ Response malformed"
    echo "Raw response:"
    echo "$RESPONSE"
    exit 1
fi

# Check for Phase 3 timing
echo ""
echo "Checking Phase 3 performance..."
EVAL_TIME=$(tail -200 tool_server.log | grep "\[Phase 3\] Evaluating" | tail -1 || true)
if [ -n "$EVAL_TIME" ]; then
    echo "Latest evaluation: $EVAL_TIME"
fi

echo ""
echo "=== Smoke Test Passed ==="
echo ""
echo "Next steps:"
echo "1. Send the same query again to trigger cache evaluation"
echo "2. Check tool_server.log for Phase 3 decision making"
echo "3. Monitor latency with: tail -f tool_server.log | grep '\[Phase 3\]'"
