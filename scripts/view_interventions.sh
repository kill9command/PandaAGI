#!/bin/bash
# View intervention queue
# Usage: ./scripts/view_interventions.sh

QUEUE_FILE="panda_system_docs/shared_state/captcha_queue.json"

# Check if file exists
if [ ! -f "$QUEUE_FILE" ]; then
    echo "❌ Intervention queue file not found: $QUEUE_FILE"
    exit 1
fi

# Count interventions
COUNT=$(jq 'length' "$QUEUE_FILE" 2>/dev/null || echo "0")

echo "📋 Intervention Queue Status"
echo "════════════════════════════════════"
echo "   Total interventions: $COUNT"
echo ""

if [ "$COUNT" -eq 0 ]; then
    echo "   ✅ Queue is empty"
else
    echo "   Interventions:"
    jq -r '.[] | "   • [\(.type)] \(.domain) - Created: \(.created_at) - Resolved: \(.resolved)"' "$QUEUE_FILE"
fi

echo ""
echo "   File: $QUEUE_FILE"
