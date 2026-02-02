#!/bin/bash
# Test research monitor end-to-end

SESSION_ID="test_monitor_$(date +%s)"

echo "=== Testing Research Monitor ==="
echo "Session ID: $SESSION_ID"
echo ""

echo "1. Monitor URL: http://127.0.0.1:9000/research_monitor.html?session=$SESSION_ID"
echo "2. Triggering research..."

curl -X POST http://127.0.0.1:8090/internet.research \
  -H "Content-Type: application/json" \
  -d "{
    \"query\": \"Syrian hamster care\",
    \"intent\": \"informational\",
    \"max_results\": 2,
    \"max_candidates\": 5,
    \"session_id\": \"$SESSION_ID\",
    \"human_assist_allowed\": true
  }" | jq .

echo ""
echo "3. Check Gateway logs for events:"
tail -20 gateway.log | grep -i "research\|event"

echo ""
echo "4. Check Orchestrator logs for events:"
tail -20 orchestrator.log | grep -i "emit\|event"
