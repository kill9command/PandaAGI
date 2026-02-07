#!/bin/bash
# Clear intervention queue
# Usage: ./scripts/clear_interventions.sh

QUEUE_FILE="panda_system_docs/shared_state/captcha_queue.json"

# Check if file exists
if [ ! -f "$QUEUE_FILE" ]; then
    echo "❌ Intervention queue file not found: $QUEUE_FILE"
    exit 1
fi

# Count current interventions
COUNT=$(jq 'length' "$QUEUE_FILE" 2>/dev/null || echo "0")

# Clear the queue
echo '[]' > "$QUEUE_FILE"

echo "✅ Cleared intervention queue"
echo "   Removed: $COUNT intervention(s)"
echo "   File: $QUEUE_FILE"
