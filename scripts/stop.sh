#!/bin/bash
#
# Pandora Stop Script
# Stops all services and clears caches
#

set -euo pipefail

# ROOT_DIR is the project root (parent of scripts/)
ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PID_DIR="$ROOT_DIR/.pids"
LOG_DIR="$ROOT_DIR/logs/panda"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Timeouts
GRACEFUL_TIMEOUT=10
FORCE_TIMEOUT=5

# Ports
VLLM_PORT="${VLLM_PORT:-8000}"
ORCHESTRATOR_PORT="${ORCHESTRATOR_PORT:-8090}"
GATEWAY_PORT="${GATEWAY_PORT:-9000}"

echo -e "${BLUE}=== Stopping Pandora Services ===${NC}"
echo ""

# Create directories if needed
mkdir -p "$PID_DIR" "$LOG_DIR"

# ========== Process Management Functions ==========

# Verify a PID belongs to an expected process type
verify_process() {
    local pid=$1
    local name=$2

    if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
        return 1
    fi

    local cmdline=$(ps -p "$pid" -o comm= 2>/dev/null)

    case "$name" in
        gateway|orchestrator)
            [[ "$cmdline" =~ ^(python|uvicorn|gunicorn) ]] && return 0
            ;;
        vllm)
            [[ "$cmdline" =~ ^(python|vllm) ]] && return 0
            ;;
        tunnel)
            [[ "$cmdline" =~ ^cloudflared ]] && return 0
            ;;
        xvfb)
            [[ "$cmdline" =~ ^Xvfb ]] && return 0
            ;;
        *)
            [[ "$cmdline" =~ ^python ]] && return 0
            ;;
    esac

    return 1
}

# Kill process and its children
kill_process_tree() {
    local pid=$1
    local signal=${2:-TERM}

    # Get all child PIDs
    local children=$(pgrep -P "$pid" 2>/dev/null || true)

    # Kill children first
    for child in $children; do
        kill_process_tree "$child" "$signal"
    done

    # Kill the process itself
    if kill -0 "$pid" 2>/dev/null; then
        kill -"$signal" "$pid" 2>/dev/null || true
    fi
}

# Wait for process to die
wait_for_process() {
    local pid=$1
    local timeout=$2

    for ((i=0; i<timeout; i++)); do
        if ! kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
        sleep 1
    done
    return 1
}

# Stop a service by name with graceful shutdown
stop_service() {
    local name=$1
    local port=$2
    local pidfile="$PID_DIR/${name}.pid"
    local stopped=false
    local pid_from_file=""

    echo -e "${YELLOW}Stopping $name...${NC}"

    # Try PID file first
    if [ -f "$pidfile" ]; then
        pid_from_file=$(cat "$pidfile" 2>/dev/null || true)

        if [[ "$pid_from_file" =~ ^[0-9]+$ ]]; then
            if kill -0 "$pid_from_file" 2>/dev/null; then
                if verify_process "$pid_from_file" "$name"; then
                    echo "  Stopping $name (PID: $pid_from_file)..."

                    kill_process_tree "$pid_from_file" "TERM"

                    if wait_for_process "$pid_from_file" "$GRACEFUL_TIMEOUT"; then
                        echo -e "  ${GREEN}$name stopped gracefully${NC}"
                        stopped=true
                    else
                        echo -e "  ${YELLOW}$name not responding, sending SIGKILL...${NC}"
                        kill_process_tree "$pid_from_file" "KILL"

                        if wait_for_process "$pid_from_file" "$FORCE_TIMEOUT"; then
                            echo -e "  ${GREEN}$name force stopped${NC}"
                            stopped=true
                        else
                            echo -e "  ${RED}Failed to stop $name${NC}"
                        fi
                    fi
                else
                    echo -e "  ${YELLOW}PID $pid_from_file is not $name (stale PID file)${NC}"
                fi
            else
                echo -e "  ${YELLOW}PID $pid_from_file not running (stale PID file)${NC}"
            fi
        fi

        rm -f "$pidfile"
    fi

    # Fallback: find by port
    if [ "$stopped" = false ] && [ -n "$port" ]; then
        local port_pids=$(lsof -ti:"$port" 2>/dev/null || true)

        if [ -n "$port_pids" ]; then
            for pid in $port_pids; do
                [ "$pid" = "$pid_from_file" ] && continue

                if verify_process "$pid" "$name"; then
                    echo "  Stopping $name on port $port (PID: $pid)..."
                    kill_process_tree "$pid" "TERM"

                    if wait_for_process "$pid" "$GRACEFUL_TIMEOUT"; then
                        echo -e "  ${GREEN}$name stopped${NC}"
                        stopped=true
                    else
                        kill_process_tree "$pid" "KILL"
                        sleep 1
                        stopped=true
                    fi
                fi
            done
        fi
    fi

    # Also try pkill as backup
    if [ "$stopped" = false ]; then
        case "$name" in
            gateway)
                pkill -f "uvicorn.*gateway.app" 2>/dev/null && echo -e "  ${GREEN}Killed stray gateway${NC}" && stopped=true || true
                ;;
            orchestrator)
                pkill -f "uvicorn.*orchestrator.app" 2>/dev/null && echo -e "  ${GREEN}Killed stray orchestrator${NC}" && stopped=true || true
                ;;
        esac
    fi

    if [ "$stopped" = false ]; then
        if [ -n "$port" ] && [ -z "$(lsof -ti:"$port" 2>/dev/null)" ]; then
            echo -e "  $name: not running"
        elif [ -z "$port" ]; then
            echo -e "  $name: not running"
        else
            echo -e "  ${RED}Warning: port $port still in use${NC}"
        fi
    fi
}

# ========== Stop Services ==========

# Stop Tunnel first (external facing)
echo -e "${YELLOW}Stopping Cloudflare tunnel...${NC}"
if [ -f "$PID_DIR/tunnel.pid" ]; then
    pid=$(cat "$PID_DIR/tunnel.pid" 2>/dev/null || true)
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        sleep 1
        echo -e "  ${GREEN}Tunnel stopped${NC}"
    fi
    rm -f "$PID_DIR/tunnel.pid"
fi
pkill -f "cloudflared.*tunnel.*run" 2>/dev/null && echo -e "  ${GREEN}Killed stray tunnel${NC}" || echo -e "  Tunnel: not running"

# Stop Gateway
stop_service "gateway" "$GATEWAY_PORT"

# Stop Orchestrator
stop_service "orchestrator" "$ORCHESTRATOR_PORT"

# Stop vLLM
echo -e "${YELLOW}Stopping vLLM...${NC}"
if [ -x "$ROOT_DIR/scripts/stop_llm.sh" ]; then
    "$ROOT_DIR/scripts/stop_llm.sh" || true
else
    stop_service "vllm" "$VLLM_PORT"
fi

# Stop noVNC and x11vnc
echo -e "${YELLOW}Stopping VNC services...${NC}"
pkill -f "novnc_proxy.*6080" 2>/dev/null && echo -e "  ${GREEN}Killed noVNC proxy${NC}" || echo -e "  noVNC: not running"
pkill -f "websockify.*6080" 2>/dev/null && echo -e "  ${GREEN}Killed websockify${NC}" || true
pkill -f "x11vnc.*:99" 2>/dev/null && echo -e "  ${GREEN}Killed x11vnc${NC}" || echo -e "  x11vnc: not running"
rm -f "$PID_DIR/novnc.pid"

# Check for root-owned VNC processes
if ps aux | grep -E "root.*websockify.*6080|root.*x11vnc.*:99" | grep -v grep >/dev/null 2>&1; then
    echo -e "${YELLOW}Warning: Root-owned VNC processes still running. Kill manually:${NC}"
    ps aux | grep -E "root.*websockify.*6080|root.*x11vnc.*:99" | grep -v grep | awk '{print "  sudo kill " $2}'
fi

# Stop Xvfb
echo -e "${YELLOW}Stopping Xvfb...${NC}"
pkill -f "Xvfb :99" 2>/dev/null && echo -e "  ${GREEN}Killed Xvfb${NC}" || echo -e "  Xvfb: not running"
rm -f "$PID_DIR/xvfb.pid"

# ========== Clear Caches ==========
echo ""
echo -e "${YELLOW}Clearing Python cache...${NC}"
find "$ROOT_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$ROOT_DIR" -name "*.pyc" -delete 2>/dev/null || true
find "$ROOT_DIR" -name "*.pyo" -delete 2>/dev/null || true
echo -e "${GREEN}Python cache cleared${NC}"

# Clear response cache (optional - uncomment if desired)
# echo -e "${YELLOW}Clearing response cache...${NC}"
# rm -rf "$ROOT_DIR/panda_system_docs/shared_state/response_cache"/* 2>/dev/null || true
# echo -e "${GREEN}Response cache cleared${NC}"

# ========== Final Status ==========
echo ""
echo -e "${BLUE}=== Status ===${NC}"

# Check tunnel
if pgrep -f "cloudflared.*tunnel.*run" > /dev/null 2>&1; then
    echo -e "Tunnel:       ${RED}still running${NC}"
else
    echo -e "Tunnel:       ${GREEN}stopped${NC}"
fi

# Check gateway
if [ -z "$(lsof -ti:"$GATEWAY_PORT" 2>/dev/null)" ]; then
    echo -e "Gateway:      ${GREEN}stopped${NC}"
else
    echo -e "Gateway:      ${RED}still running on port $GATEWAY_PORT${NC}"
fi

# Check orchestrator
if [ -z "$(lsof -ti:"$ORCHESTRATOR_PORT" 2>/dev/null)" ]; then
    echo -e "Orchestrator: ${GREEN}stopped${NC}"
else
    echo -e "Orchestrator: ${RED}still running on port $ORCHESTRATOR_PORT${NC}"
fi

# Check vLLM
if [ -z "$(lsof -ti:"$VLLM_PORT" 2>/dev/null)" ]; then
    echo -e "vLLM:         ${GREEN}stopped${NC}"
else
    echo -e "vLLM:         ${RED}still running on port $VLLM_PORT${NC}"
fi

# Check Xvfb
if pgrep -f "Xvfb :99" > /dev/null 2>&1; then
    echo -e "Xvfb:         ${RED}still running${NC}"
else
    echo -e "Xvfb:         ${GREEN}stopped${NC}"
fi

echo ""
echo -e "${GREEN}Done${NC}"
