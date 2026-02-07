#!/bin/bash
# Start noVNC and x11vnc for CAPTCHA solving (runs as current user, no sudo needed)

DISPLAY_NUM=99
VNC_PORT=5999
NOVNC_PORT=6080
ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PID_DIR="$ROOT_DIR/.pids"
mkdir -p "$PID_DIR"

# Kill existing VNC/noVNC processes
pkill -f "websockify.*${NOVNC_PORT}" 2>/dev/null || true
pkill -f "x11vnc.*:${DISPLAY_NUM}" 2>/dev/null || true

# Check if Xvfb is running on DISPLAY :99
if ! pgrep -f "Xvfb :${DISPLAY_NUM}" >/dev/null; then
    echo "[novnc] ERROR: Xvfb not running on DISPLAY :${DISPLAY_NUM}"
    echo "[novnc] Start Xvfb first: Xvfb :${DISPLAY_NUM} -screen 0 1920x1080x24 &"
    exit 1
fi

# Start x11vnc on DISPLAY :99 (with -noshm to avoid shared memory errors)
# Note: Removed -localhost flag to allow remote connections for CAPTCHA solving
echo "[novnc] starting x11vnc on display :${DISPLAY_NUM}..."
x11vnc -display :${DISPLAY_NUM} \
       -rfbport ${VNC_PORT} \
       -nopw \
       -noshm \
       -forever \
       -shared \
       -bg \
       -o "$ROOT_DIR/x11vnc.log"

# Wait a moment for x11vnc to start
sleep 1

# Verify x11vnc started
if ! pgrep -f "x11vnc.*:${DISPLAY_NUM}" >/dev/null; then
    echo "[novnc] ERROR: x11vnc failed to start. Check $ROOT_DIR/x11vnc.log"
    exit 1
fi

# Check if noVNC is installed
if [ ! -d "/opt/noVNC" ]; then
    echo "[novnc] ERROR: noVNC not installed at /opt/noVNC"
    echo "[novnc] Install with: sudo bash scripts/setup_novnc.sh"
    exit 1
fi

# Start noVNC websockify proxy
# Note: Listen on 0.0.0.0 to allow remote connections for CAPTCHA solving
echo "[novnc] starting websockify on port ${NOVNC_PORT}..."
cd /opt/noVNC
./utils/novnc_proxy --vnc localhost:${VNC_PORT} --listen 0.0.0.0:${NOVNC_PORT} >"$ROOT_DIR/novnc.log" 2>&1 &
NOVNC_PID=$!
echo $NOVNC_PID > "$PID_DIR/novnc.pid"

# Wait a moment for websockify to start
sleep 1

# Verify websockify started
if ! kill -0 $NOVNC_PID 2>/dev/null; then
    echo "[novnc] ERROR: websockify failed to start. Check $ROOT_DIR/novnc.log"
    exit 1
fi

echo "[novnc] ✓ noVNC started successfully!"
echo "[novnc]   VNC server:  localhost:${VNC_PORT} (DISPLAY :${DISPLAY_NUM})"
echo "[novnc]   noVNC web:   http://localhost:${NOVNC_PORT}/vnc.html"
echo "[novnc]   PID file:    $PID_DIR/novnc.pid"
