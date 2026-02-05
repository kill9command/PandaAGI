#!/usr/bin/env bash
#
# Run contract tests only (fast CI target)
#
# Usage:
#   ./scripts/run_contract_tests.sh           # Run all contract tests
#   ./scripts/run_contract_tests.sh --quick   # Run contract tests only (no bundles)
#   ./scripts/run_contract_tests.sh --full    # Run all tests including bundles
#
# Exit codes:
#   0 = all tests passed
#   1 = test failures
#
# This script is the CI gate: contract tests must pass before
# behavioral changes can be merged.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

MODE="${1:-}"

echo "============================================"
echo "  Pandora Contract Test Gate"
echo "============================================"
echo ""

if [ "$MODE" = "--quick" ]; then
    echo "Mode: Quick (contract tests only)"
    echo ""
    python -m pytest tests/contract/ -v --tb=short -q
    EXIT_CODE=$?

elif [ "$MODE" = "--full" ]; then
    echo "Mode: Full (contract + bundle tests)"
    echo ""
    python -m pytest tests/contract/ panda_system_docs/workflows/bundles/*/tests/ -v --tb=short -q
    EXIT_CODE=$?

else
    echo "Mode: Standard (contract + bundle tests)"
    echo ""
    python -m pytest tests/contract/ panda_system_docs/workflows/bundles/*/tests/ --tb=short -q
    EXIT_CODE=$?
fi

echo ""
echo "============================================"
if [ $EXIT_CODE -eq 0 ]; then
    echo "  GATE: PASSED"
else
    echo "  GATE: FAILED"
fi
echo "============================================"

exit $EXIT_CODE
