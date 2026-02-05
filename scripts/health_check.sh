#!/usr/bin/env bash

# Panda stack health check (vLLM, Gateway, Tool Server)
# Usage: bash ./server_health.sh

set -u

# ROOT_DIR is the project root (parent of scripts/)
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ -f "$ROOT_DIR/.env" ]; then
  # shellcheck disable=SC1090
  set -a; . "$ROOT_DIR/.env"; set +a
fi

GATEWAY_HOST="${GATEWAY_HOST:-127.0.0.1}"
GATEWAY_BASE="http://${GATEWAY_HOST}:9000"
TOOL_SERVER_URL="${TOOL_SERVER_URL:-http://127.0.0.1:8090}"

SOLVER_URL="${SOLVER_URL:-http://127.0.0.1:8000/v1/chat/completions}"
if [[ "$SOLVER_URL" == *"/v1/chat/completions"* ]]; then
  VLLM_BASE="${SOLVER_URL%/v1/chat/completions}"
else
  VLLM_BASE="http://127.0.0.1:8000"
fi
VLLM_MODELS="${VLLM_BASE}/v1/models"
VLLM_CHAT="${VLLM_BASE}/v1/chat/completions"

SOLVER_MODEL_ID="${SOLVER_MODEL_ID:-qwen3-coder}"
THINK_MODEL_ID="${THINK_MODEL_ID:-$SOLVER_MODEL_ID}"

SOLVER_API_KEY="${SOLVER_API_KEY:-qwen-local}"
THINK_API_KEY="${THINK_API_KEY:-$SOLVER_API_KEY}"

VLLM_SOLVER_HEADERS=(-H "Content-Type: application/json")
if [ -n "$SOLVER_API_KEY" ]; then
  VLLM_SOLVER_HEADERS+=(-H "Authorization: Bearer ${SOLVER_API_KEY}")
fi
VLLM_THINK_HEADERS=(-H "Content-Type: application/json")
if [ -n "$THINK_API_KEY" ]; then
  VLLM_THINK_HEADERS+=(-H "Authorization: Bearer ${THINK_API_KEY}")
fi

GATEWAY_HEADERS=(-H "Content-Type: application/json")
if [ -n "${GATEWAY_API_KEY:-}" ]; then
  GATEWAY_HEADERS+=(-H "Authorization: Bearer ${GATEWAY_API_KEY}")
fi

pass=0; fail=0; warn=0

hr() { printf "\n%s\n" "============================================"; }
ok() { echo "PASS: $1"; pass=$((pass+1)); }
bad() { echo "FAIL: $1"; fail=$((fail+1)); }
warnf() { echo "WARN: $1"; warn=$((warn+1)); }

check_gateway_health() {
  local url="${GATEWAY_BASE}/healthz"
  local out; out=$(curl -sS -m 5 "$url" || true)
  if echo "$out" | grep -q '"ok":\s*true'; then ok "Gateway /healthz"; else bad "Gateway /healthz ($out)"; fi
}

check_gateway_policy() {
  local url="${GATEWAY_BASE}/policy"
  local out; out=$(curl -sS -m 8 "$url" || true)
  if echo "$out" | grep -q 'chat_allow_file_create'; then ok "Gateway /policy"; else bad "Gateway /policy ($out)"; fi
}

check_gateway_chat() {
  local url="${GATEWAY_BASE}/v1/chat/completions"
  local payload='{"model":"panda-chat","messages":[{"role":"user","content":"ping"}]}'
  local out; out=$(curl -sS -m 30 "${GATEWAY_HEADERS[@]}" -d "$payload" "$url" || true)
  if echo "$out" | grep -q '"choices"'; then ok "Gateway chat completions"; GATEWAY_CHAT_OK=1; else bad "Gateway chat completions ($out)"; GATEWAY_CHAT_OK=0; fi
}

check_tool_server_docsearch() {
  local url="${TOOL_SERVER_URL}/doc.search"
  local payload='{"query":"README","k":1}'
  local out; out=$(curl -sS -m 20 -H 'Content-Type: application/json' -d "$payload" "$url" || true)
  if echo "$out" | grep -q '"summary"'; then ok "Tool Server /doc.search"; else bad "Tool Server /doc.search ($out)"; fi
}

check_vllm_models() {
  local out; out=$(curl -sS -m 10 "${VLLM_SOLVER_HEADERS[@]}" "$VLLM_MODELS" || true)
  if echo "$out" | grep -q "\"${SOLVER_MODEL_ID}\""; then
    ok "vLLM models (${SOLVER_MODEL_ID} present)"
  else
    bad "vLLM models missing '${SOLVER_MODEL_ID}' (response: $(echo "$out" | tr '\n' ' '))"
  fi
}

check_vllm_chat() {
  local payload='{"model":"'"${SOLVER_MODEL_ID}"'","messages":[{"role":"user","content":"ping"}],"max_tokens":32,"temperature":0.2}'
  local out; out=$(curl -sS -m 60 "${VLLM_SOLVER_HEADERS[@]}" -d "$payload" "$VLLM_CHAT" || true)
  if echo "$out" | grep -q '"choices"'; then ok "vLLM chat (${SOLVER_MODEL_ID})"; return; fi
  if [ "$THINK_MODEL_ID" != "$SOLVER_MODEL_ID" ]; then
    local payload2='{"model":"'"${THINK_MODEL_ID}"'","messages":[{"role":"user","content":"ping"}],"max_tokens":16,"temperature":0.2}'
    local out2; out2=$(curl -sS -m 60 "${VLLM_THINK_HEADERS[@]}" -d "$payload2" "$VLLM_CHAT" || true)
    if echo "$out2" | grep -q '"choices"'; then
      warnf "vLLM chat (${SOLVER_MODEL_ID}) failed but (${THINK_MODEL_ID}) succeeded"
      return
    fi
  fi
  bad "vLLM chat failed (${out:-timeout})"
}

echo "Panda Health Check"
echo "Gateway      : ${GATEWAY_BASE}"
echo "Orchestrator : ${TOOL_SERVER_URL}"
echo "vLLM         : ${VLLM_BASE}"
echo "Models       : solver='${SOLVER_MODEL_ID}', thinker='${THINK_MODEL_ID}'"

hr; check_gateway_health
check_gateway_policy
check_gateway_chat
hr; check_tool_server_docsearch
hr; check_vllm_models
check_vllm_chat

hr; echo "Summary: ${pass} passed, ${fail} failed, ${warn} warnings"
exit $([ $fail -eq 0 ] && echo 0 || echo 1)
