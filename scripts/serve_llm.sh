#!/usr/bin/env bash
set -euo pipefail

# vLLM launcher for Qwen3 Coder 30B
# Reads configuration from env vars; sensible defaults documented in models/vllm-qwen-setup.md

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
LOG_PATH="${LOG_PATH:-$ROOT_DIR/vllm.log}"
PID_PATH="${PID_PATH:-$ROOT_DIR/vllm.pid}"

MODEL_DIR="${MODEL_DIR:-$ROOT_DIR/models/qwen3-coder-30b-awq4}"
SERVED_NAME="${SERVED_NAME:-qwen3-coder}"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
API_KEY="${API_KEY:-qwen-local}"

MAX_LEN_DEFAULT=30000
MAX_LEN="${MAX_LEN:-$MAX_LEN_DEFAULT}"
DTYPE="${DTYPE:-float16}"
GPU_UTIL="${GPU_UTIL:-0.90}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-1}"
SWAP_SPACE="${SWAP_SPACE:-}"

ENABLE_AUTO_TOOL_CHOICE="${ENABLE_AUTO_TOOL_CHOICE:-1}"
TOOL_CALL_PARSER="${TOOL_CALL_PARSER:-hermes}"

DEFAULT_QUANTIZATION="compressed-tensors"
QUANTIZATION="${QUANTIZATION:-$DEFAULT_QUANTIZATION}"
QUANTIZATION_ARG=""
if [[ "$QUANTIZATION" != "none" && "$QUANTIZATION" != "off" ]]; then
  QUANTIZATION_ARG="--quantization $QUANTIZATION"
fi

READY_TIMEOUT="${READY_TIMEOUT:-420}"

command -v vllm >/dev/null 2>&1 || {
  echo "ERROR: vLLM not installed. Activate environment or install via pip." >&2
  exit 1
}

if [[ ! -d "$MODEL_DIR" ]]; then
  echo "ERROR: MODEL_DIR not found: $MODEL_DIR" >&2
  exit 1
fi

if [[ -f "$PID_PATH" ]] && ps -p "$(cat "$PID_PATH")" >/dev/null 2>&1; then
  echo "vLLM already running (pid $(cat "$PID_PATH")). Logs: $LOG_PATH"
  exit 0
fi

if ss -ltn 2>/dev/null | grep -q ":$PORT "; then
  echo "ERROR: Port $PORT already in use." >&2
  exit 1
fi

export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"

CMD=(vllm serve "$MODEL_DIR"
  --served-model-name "$SERVED_NAME"
  --host "$HOST"
  --port "$PORT"
  --max-model-len "$MAX_LEN"
  --dtype "$DTYPE"
  --gpu-memory-utilization "$GPU_UTIL"
  --tensor-parallel-size "$TENSOR_PARALLEL_SIZE"
  --trust-remote-code
)

if [[ -n "$API_KEY" ]]; then
  CMD+=(--api-key "$API_KEY")
fi

if [[ -n "$QUANTIZATION_ARG" ]]; then
  CMD+=($QUANTIZATION_ARG)
fi

if [[ -n "$SWAP_SPACE" ]]; then
  CMD+=(--swap-space "$SWAP_SPACE")
fi

if [[ "$ENABLE_AUTO_TOOL_CHOICE" =~ ^(1|true|yes)$ ]]; then
  CMD+=(--enable-auto-tool-choice)
  if [[ -n "$TOOL_CALL_PARSER" ]]; then
    CMD+=(--tool-call-parser "$TOOL_CALL_PARSER")
  fi
fi

echo "Starting vLLM: model=$MODEL_DIR name=$SERVED_NAME host=$HOST port=$PORT"
nohup "${CMD[@]}" >"$LOG_PATH" 2>&1 &
echo $! >"$PID_PATH"

CHECK_HOST="$HOST"
if [[ "$CHECK_HOST" == "0.0.0.0" ]]; then
  CHECK_HOST="127.0.0.1"
elif [[ "$CHECK_HOST" == "::" ]]; then
  CHECK_HOST="[::1]"
fi

declare -a CURL_ARGS=(-fsS)
if [[ -n "$API_KEY" ]]; then
  CURL_ARGS+=(-H "Authorization: Bearer $API_KEY")
fi

echo -n "Waiting for vLLM on http://$CHECK_HOST:$PORT/v1/models "
SECONDS=0
until curl "${CURL_ARGS[@]}" "http://$CHECK_HOST:$PORT/v1/models" >/dev/null 2>&1; do
  if ! ps -p "$(cat "$PID_PATH")" >/dev/null 2>&1; then
    echo
    echo "vLLM exited during startup. Last log lines:" >&2
    tail -n 120 "$LOG_PATH" >&2 || true
    rm -f "$PID_PATH"
    exit 1
  fi
  if (( SECONDS > READY_TIMEOUT )); then
    echo
    echo "Timed out waiting for vLLM. Last log lines:" >&2
    tail -n 120 "$LOG_PATH" >&2 || true
    exit 1
  fi
  echo -n "."
  sleep 2
done

echo
DISPLAY_HOST="${CHECK_HOST#[}"
DISPLAY_HOST="${DISPLAY_HOST%]}"
echo "vLLM ready at http://$DISPLAY_HOST:$PORT/v1 (pid $(cat "$PID_PATH")). Logs: $LOG_PATH"
