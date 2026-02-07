#!/bin/bash
#
# Panda Start Script
# Starts vLLM, Tool Server, Gateway, and optional Cloudflare tunnel
#

set -e

# ROOT_DIR is the project root (parent of scripts/)
ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PID_DIR="$ROOT_DIR/.pids"
LOG_DIR="$ROOT_DIR/logs/panda"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Load .env FIRST (before defaults, so .env values take precedence)
if [ -f "$ROOT_DIR/.env" ]; then
    while IFS='=' read -r key val; do
        [[ -z "$key" || "$key" =~ ^\s*# ]] && continue || true
        # Remove surrounding quotes from val
        val="${val%\"}"
        val="${val#\"}"
        val="${val%\'}"
        val="${val#\'}"
        if [ -z "${!key+x}" ]; then
            export "$key"="$val"
        fi
    done < <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "$ROOT_DIR/.env")
fi

# Configuration (defaults applied AFTER .env is loaded)
CONDA_ENV="${CONDA_ENV:-panda}"
MODEL_PATH="${MODEL_PATH:-$ROOT_DIR/models/qwen3-coder-30b-awq4}"
VLLM_PORT="${VLLM_PORT:-8000}"
TOOL_SERVER_PORT="${TOOL_SERVER_PORT:-8090}"
GATEWAY_PORT="${GATEWAY_PORT:-9000}"
GATEWAY_HOST="${GATEWAY_HOST:-127.0.0.1}"

VLLM_START="${VLLM_START:-1}"
TUNNEL_ENABLE="${TUNNEL_ENABLE:-0}"
TUNNEL_NAME="${TUNNEL_NAME:-panda}"
TUNNEL_CONFIG="${TUNNEL_CONFIG:-$HOME/.cloudflared/config.yml}"
TUNNEL_BIN="${TUNNEL_BIN:-cloudflared}"

# Create directories
mkdir -p "$PID_DIR" "$LOG_DIR"

# Export defaults for services
export TOOL_SERVER_URL="${TOOL_SERVER_URL:-http://127.0.0.1:8090}"
export SOLVER_URL="${SOLVER_URL:-http://127.0.0.1:8000/v1/chat/completions}"
export THINK_URL="${THINK_URL:-http://127.0.0.1:8000/v1/chat/completions}"
export SOLVER_MODEL_ID="${SOLVER_MODEL_ID:-qwen3-coder}"
export THINK_MODEL_ID="${THINK_MODEL_ID:-qwen3-coder}"
export SOLVER_API_KEY="${SOLVER_API_KEY:-qwen-local}"
export THINK_API_KEY="${THINK_API_KEY:-$SOLVER_API_KEY}"

print_banner() {
    echo -e "${BLUE}"
    echo "=================================================="
    echo "  Panda - Context-Orchestrated LLM Stack"
    echo "  9-Phase Pipeline with Workflow Execution"
    echo "=================================================="
    echo -e "${NC}"
}

check_conda() {
    if ! command -v conda &> /dev/null; then
        echo -e "${RED}Error: conda not found${NC}"
        exit 1
    fi
}

check_model() {
    if [ ! -d "$MODEL_PATH" ] || [ -z "$(ls -A $MODEL_PATH 2>/dev/null)" ]; then
        echo -e "${YELLOW}Warning: Model not found at $MODEL_PATH${NC}"
        echo "Download the model first or set MODEL_PATH in .env"
        return 1
    fi
    return 0
}

wait_http_ok() {
    local url="$1"
    local timeout="${2:-30}"
    local auth_header="${3:-}"
    local start=$SECONDS
    local curl_cmd="curl -fsS"
    [ -n "$auth_header" ] && curl_cmd="$curl_cmd -H \"Authorization: Bearer $auth_header\""
    while true; do
        if eval $curl_cmd "\"$url\"" >/dev/null 2>&1; then
            return 0
        fi
        if (( SECONDS - start > timeout )); then
            return 1
        fi
        sleep 1
        echo -n "."
    done
}

check_port() {
    local port=$1
    if lsof -ti:"$port" >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

# ========== vLLM ==========
check_vllm_running() {
    curl -fsS -H "Authorization: Bearer $SOLVER_API_KEY" "http://127.0.0.1:$VLLM_PORT/v1/models" >/dev/null 2>&1
}

start_vllm() {
    if [ "$VLLM_START" != "1" ]; then
        echo -e "${YELLOW}vLLM autostart disabled (VLLM_START=$VLLM_START)${NC}"
        return 0
    fi

    echo -e "${YELLOW}Starting vLLM server...${NC}"

    if check_vllm_running; then
        echo -e "${GREEN}vLLM already running on port $VLLM_PORT${NC}"
        return 0
    fi

    if ! check_model; then
        echo -e "${YELLOW}Skipping vLLM start (no model)${NC}"
        return 1
    fi

    # Use serve_llm.sh if available
    if [ -x "$ROOT_DIR/scripts/serve_llm.sh" ]; then
        echo "[vllm] Launching via serve_llm.sh"
        SOLVER_API_KEY="$SOLVER_API_KEY" "$ROOT_DIR/scripts/serve_llm.sh"
    else
        # Fallback: start vLLM directly
        conda run -n "$CONDA_ENV" --no-capture-output \
            vllm serve "$MODEL_PATH" \
            --served-model-name qwen3-coder \
            --host 0.0.0.0 \
            --port "$VLLM_PORT" \
            --max-model-len 30000 \
            --dtype float16 \
            --gpu-memory-utilization 0.90 \
            --quantization compressed-tensors \
            --trust-remote-code \
            > "$LOG_DIR/vllm.log" 2>&1 &

        echo $! > "$PID_DIR/vllm.pid"
    fi

    echo -e "${YELLOW}Waiting for vLLM (may take 1-3 minutes for 30B model)...${NC}"
    if wait_http_ok "http://127.0.0.1:$VLLM_PORT/v1/models" 180 "$SOLVER_API_KEY"; then
        echo -e "\n${GREEN}vLLM started successfully${NC}"
        return 0
    else
        echo -e "\n${RED}vLLM startup timeout - check $LOG_DIR/vllm.log${NC}"
        return 1
    fi
}

# ========== Xvfb / VNC ==========
start_xvfb() {
    export DISPLAY=:99

    if pgrep -f "Xvfb :99" >/dev/null 2>&1; then
        echo -e "[xvfb] ${GREEN}Already running on display :99${NC}"
    else
        echo -e "${YELLOW}Starting Xvfb virtual display :99${NC}"
        Xvfb :99 -screen 0 1920x1080x24 &
        echo $! > "$PID_DIR/xvfb.pid"
        sleep 1
    fi
}

start_vnc() {
    if pgrep -f "x11vnc.*:99" >/dev/null 2>&1; then
        echo -e "[x11vnc] ${GREEN}Already running${NC}"
    else
        echo -e "${YELLOW}Starting x11vnc on port 5999${NC}"
        x11vnc -display :99 -rfbport 5999 -nopw -noshm -forever -shared -bg -o "$LOG_DIR/x11vnc.log"
        sleep 1
    fi
}

start_novnc() {
    if pgrep -f "novnc_proxy.*6080" >/dev/null 2>&1; then
        echo -e "[novnc] ${GREEN}Already running${NC}"
    else
        if [ -d "/opt/noVNC" ]; then
            echo -e "${YELLOW}Starting noVNC proxy on port 6080${NC}"
            cd /opt/noVNC
            ./utils/novnc_proxy --vnc localhost:5999 --listen 0.0.0.0:6080 > "$LOG_DIR/novnc.log" 2>&1 &
            echo $! > "$PID_DIR/novnc.pid"
            cd "$ROOT_DIR"
            sleep 1
        else
            echo -e "${YELLOW}noVNC not installed at /opt/noVNC, skipping${NC}"
        fi
    fi
}

# ========== Tool Server ==========
check_tool_server_running() {
    curl -fsS "http://127.0.0.1:$TOOL_SERVER_PORT/health" >/dev/null 2>&1
}

start_tool_server() {
    echo -e "${YELLOW}Starting Tool Server...${NC}"

    if [ -f "$PID_DIR/tool_server.pid" ] && kill -0 "$(cat "$PID_DIR/tool_server.pid")" 2>/dev/null; then
        echo -e "${GREEN}Tool Server already running (pid $(cat "$PID_DIR/tool_server.pid"))${NC}"
        return 0
    fi

    nohup env DISPLAY=:99 \
        SOLVER_URL="$SOLVER_URL" \
        SOLVER_MODEL_ID="$SOLVER_MODEL_ID" \
        SOLVER_API_KEY="$SOLVER_API_KEY" \
        uvicorn apps.tool_server.app:app \
        --host 127.0.0.1 --port $TOOL_SERVER_PORT \
        > "$LOG_DIR/tool_server.log" 2>&1 &

    echo $! > "$PID_DIR/tool_server.pid"
    echo -e "${GREEN}Tool Server started on port $TOOL_SERVER_PORT${NC}"
}

# ========== Gateway ==========
check_gateway_running() {
    curl -fsS "http://$GATEWAY_HOST:$GATEWAY_PORT/health" >/dev/null 2>&1 || \
    curl -fsS "http://$GATEWAY_HOST:$GATEWAY_PORT/healthz" >/dev/null 2>&1
}

start_gateway() {
    echo -e "${YELLOW}Starting Gateway...${NC}"

    if [ -f "$PID_DIR/gateway.pid" ] && kill -0 "$(cat "$PID_DIR/gateway.pid")" 2>/dev/null; then
        echo -e "${GREEN}Gateway already running (pid $(cat "$PID_DIR/gateway.pid"))${NC}"
        return 0
    fi

    nohup env \
        DISPLAY=:99 \
        TOOL_SERVER_URL="$TOOL_SERVER_URL" \
        SOLVER_URL="$SOLVER_URL" \
        THINK_URL="$THINK_URL" \
        SOLVER_MODEL_ID="$SOLVER_MODEL_ID" \
        THINK_MODEL_ID="$THINK_MODEL_ID" \
        SOLVER_API_KEY="$SOLVER_API_KEY" \
        THINK_API_KEY="$THINK_API_KEY" \
        uvicorn apps.services.gateway.app:app \
        --host "$GATEWAY_HOST" --port $GATEWAY_PORT \
        > "$LOG_DIR/gateway.log" 2>&1 &

    echo $! > "$PID_DIR/gateway.pid"
    echo -e "${GREEN}Gateway started on ${GATEWAY_HOST}:${GATEWAY_PORT}${NC}"
}

# ========== Tunnel ==========
start_tunnel() {
    if [ "$TUNNEL_ENABLE" != "1" ]; then
        echo -e "${YELLOW}Cloudflare tunnel disabled (TUNNEL_ENABLE != 1)${NC}"
        return 0
    fi

    echo -e "${YELLOW}Starting Cloudflare tunnel...${NC}"

    if [ -f "$PID_DIR/tunnel.pid" ] && kill -0 "$(cat "$PID_DIR/tunnel.pid")" 2>/dev/null; then
        echo -e "${GREEN}Tunnel already running${NC}"
        return 0
    fi

    if ! command -v "$TUNNEL_BIN" &> /dev/null; then
        echo -e "${RED}cloudflared not found, skipping tunnel${NC}"
        return 1
    fi

    if [ -f "$TUNNEL_CONFIG" ]; then
        nohup "$TUNNEL_BIN" --config "$TUNNEL_CONFIG" run "$TUNNEL_NAME" \
            > "$LOG_DIR/tunnel.log" 2>&1 &
    else
        nohup "$TUNNEL_BIN" tunnel run "$TUNNEL_NAME" \
            > "$LOG_DIR/tunnel.log" 2>&1 &
    fi

    echo $! > "$PID_DIR/tunnel.pid"
    sleep 2

    if kill -0 "$(cat "$PID_DIR/tunnel.pid")" 2>/dev/null; then
        echo -e "${GREEN}Tunnel started${NC}"
    else
        echo -e "${RED}Tunnel failed to start - check $LOG_DIR/tunnel.log${NC}"
    fi
}

# ========== UI Build ==========
build_ui() {
    local UI_DIR="$ROOT_DIR/apps/ui"
    local UI_BUILD_DIR="$UI_DIR/build"

    if [ -d "$UI_DIR" ] && [ -f "$UI_DIR/package.json" ]; then
        if [ ! -d "$UI_BUILD_DIR" ]; then
            if command -v npm >/dev/null 2>&1; then
                echo -e "${YELLOW}Building Svelte UI...${NC}"
                cd "$UI_DIR"
                npm install --silent 2>/dev/null || npm install
                npm run build
                cd "$ROOT_DIR"
                echo -e "${GREEN}UI build complete${NC}"
            else
                echo -e "${YELLOW}npm not found, skipping UI build${NC}"
            fi
        fi
    fi
}

# ========== Status ==========
show_status() {
    echo -e "${BLUE}=== Panda Status ===${NC}"
    echo ""

    # vLLM
    if check_vllm_running; then
        echo -e "vLLM:         ${GREEN}Running on port $VLLM_PORT${NC}"
    else
        echo -e "vLLM:         ${YELLOW}Not running${NC}"
    fi

    # Tool Server
    if check_port $TOOL_SERVER_PORT; then
        echo -e "Tool Server:  ${GREEN}Running on port $TOOL_SERVER_PORT${NC}"
    else
        echo -e "Tool Server:  ${YELLOW}Not running${NC}"
    fi

    # Gateway
    if check_port $GATEWAY_PORT; then
        echo -e "Gateway:      ${GREEN}Running on port $GATEWAY_PORT${NC}"
    else
        echo -e "Gateway:      ${YELLOW}Not running${NC}"
    fi

    # Xvfb
    if pgrep -f "Xvfb :99" >/dev/null 2>&1; then
        echo -e "Xvfb:         ${GREEN}Running on :99${NC}"
    else
        echo -e "Xvfb:         ${YELLOW}Not running${NC}"
    fi

    # Tunnel
    if [ -f "$PID_DIR/tunnel.pid" ] && kill -0 "$(cat "$PID_DIR/tunnel.pid")" 2>/dev/null; then
        echo -e "Tunnel:       ${GREEN}Running${NC}"
    else
        echo -e "Tunnel:       ${YELLOW}Not running${NC}"
    fi

    echo ""
}

show_help() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  start       Start all services (default)"
    echo "  stop        Stop all services"
    echo "  restart     Restart all services"
    echo "  status      Show service status"
    echo "  logs        Tail all logs"
    echo "  logs-vllm   Tail vLLM logs"
    echo "  logs-gw     Tail Gateway logs"
    echo "  logs-ts     Tail Tool Server logs"
    echo "  help        Show this help"
    echo ""
}

# Ensure we're in project root
cd "$ROOT_DIR"

# Main
print_banner
check_conda

case "${1:-start}" in
    start)
        start_vllm
        echo ""
        start_xvfb
        start_vnc
        start_novnc
        echo ""
        build_ui
        echo ""
        start_tool_server
        start_gateway
        echo ""
        start_tunnel
        echo ""
        echo -e "${GREEN}Panda is running!${NC}"
        echo "  vLLM:         http://127.0.0.1:$VLLM_PORT"
        echo "  Tool Server:  http://127.0.0.1:$TOOL_SERVER_PORT"
        echo "  Gateway:      http://$GATEWAY_HOST:$GATEWAY_PORT"
        echo "  noVNC:        http://localhost:6080/vnc_lite.html"
        echo ""
        echo "To stop: $0 stop"
        ;;
    stop)
        "$ROOT_DIR/scripts/stop.sh"
        ;;
    restart)
        "$ROOT_DIR/scripts/stop.sh"
        sleep 2
        exec "$0" start
        ;;
    status)
        show_status
        ;;
    logs)
        tail -f "$LOG_DIR"/*.log
        ;;
    logs-vllm)
        tail -f "$LOG_DIR/vllm.log"
        ;;
    logs-gw)
        tail -f "$LOG_DIR/gateway.log"
        ;;
    logs-ts)
        tail -f "$LOG_DIR/tool_server.log"
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo -e "${RED}Unknown command: $1${NC}"
        show_help
        exit 1
        ;;
esac
