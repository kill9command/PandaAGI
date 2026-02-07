#!/bin/bash
# Setup noVNC for browser-based CAPTCHA solving
# This allows users to view and control the server's browser from any device

set -e

echo "=== Installing x11vnc and dependencies ==="
sudo apt-get update
sudo apt-get install -y x11vnc

echo ""
echo "=== Cloning noVNC ==="
cd /opt
sudo git clone https://github.com/novnc/noVNC.git
cd noVNC
sudo git clone https://github.com/novnc/websockify utils/websockify

echo ""
echo "=== Creating noVNC startup script ==="
cat > /tmp/start_novnc.sh << 'EOF'
#!/bin/bash
# Start noVNC proxy to serve VNC via WebSocket on port 6080

DISPLAY_NUM=99
VNC_PORT=5999
NOVNC_PORT=6080

# Kill existing noVNC/websockify processes
pkill -f "websockify.*${NOVNC_PORT}" 2>/dev/null || true

# Start x11vnc on DISPLAY :99
echo "Starting x11vnc on display :${DISPLAY_NUM}..."
x11vnc -display :${DISPLAY_NUM} \
       -rfbport ${VNC_PORT} \
       -localhost \
       -nopw \
       -forever \
       -shared \
       -bg \
       -o /tmp/x11vnc.log

# Start noVNC websockify proxy
echo "Starting noVNC websockify on port ${NOVNC_PORT}..."
cd /opt/noVNC
./utils/novnc_proxy --vnc localhost:${VNC_PORT} --listen ${NOVNC_PORT} &

echo ""
echo "✓ noVNC started!"
echo "  VNC server: localhost:${VNC_PORT} (DISPLAY :${DISPLAY_NUM})"
echo "  noVNC web:  http://localhost:${NOVNC_PORT}/vnc.html"
echo ""
EOF

sudo mv /tmp/start_novnc.sh /opt/noVNC/start_novnc.sh
sudo chmod +x /opt/noVNC/start_novnc.sh

echo ""
echo "=== Setup complete! ==="
echo ""
echo "To start noVNC, run:"
echo "  sudo /opt/noVNC/start_novnc.sh"
echo ""
echo "Then access from browser:"
echo "  http://your-server:6080/vnc.html"
