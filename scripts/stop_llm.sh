#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PID_PATH="${PID_PATH:-$ROOT_DIR/vllm.pid}"
LOG_PATH="${LOG_PATH:-$ROOT_DIR/vllm.log}"

# Function to kill process tree
kill_process_tree() {
  local pid=$1
  local children
  children=$(pgrep -P "$pid" 2>/dev/null || true)

  # Recursively kill children first
  for child in $children; do
    kill_process_tree "$child"
  done

  # Kill the process itself
  if ps -p "$pid" >/dev/null 2>&1; then
    kill "$pid" 2>/dev/null || true
    sleep 0.5
    if ps -p "$pid" >/dev/null 2>&1; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  fi
}

if [[ ! -f "$PID_PATH" ]]; then
  echo "[stop_llm] pid file not found ($PID_PATH)"
  # Still try to clean up any orphaned vLLM processes
  echo "[stop_llm] checking for orphaned vLLM processes..."
else
  PID=$(cat "$PID_PATH")
  if ! ps -p "$PID" >/dev/null 2>&1; then
    echo "[stop_llm] process $PID not running; removing pid file."
    rm -f "$PID_PATH"
  else
    echo "[stop_llm] stopping vLLM process tree (root pid $PID)"
    kill_process_tree "$PID"
    rm -f "$PID_PATH"
  fi
fi

# Clean up any remaining vLLM/EngineCore processes (zombie cleanup)
echo "[stop_llm] checking for zombie vLLM processes..."
ZOMBIE_PIDS=$(pgrep -f "vllm|EngineCore" 2>/dev/null || true)
if [ -n "$ZOMBIE_PIDS" ]; then
  echo "[stop_llm] found zombie processes, cleaning up: $ZOMBIE_PIDS"
  for zpid in $ZOMBIE_PIDS; do
    kill -9 "$zpid" 2>/dev/null || true
  done
  sleep 1
fi

echo "[stop_llm] done. Logs at $LOG_PATH"
