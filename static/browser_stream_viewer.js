/**
 * Browser Stream Viewer - Interactive canvas for remote browser control
 *
 * Displays live browser frames from server's Playwright and forwards user interactions.
 * Used for remote CAPTCHA solving - works on phone, tablet, laptop.
 */

class BrowserStreamViewer {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.ws = null;
        this.streamId = null;
        this.canvas = null;
        this.ctx = null;
        this.currentImage = null;
        this.isConnected = false;

        console.log('[BrowserStreamViewer] Initialized');
    }

    /**
     * Start streaming from server's browser
     * @param {string} streamId - Intervention/stream identifier
     */
    async connect(streamId) {
        this.streamId = streamId;

        console.log(`[BrowserStreamViewer] Connecting to stream: ${streamId}`);

        // Create canvas if it doesn't exist
        if (!this.canvas) {
            this.createCanvas();
        }

        // Connect to Gateway WebSocket
        const wsUrl = `ws://${window.location.host}/ws/browser-stream/${streamId}`;
        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('[BrowserStreamViewer] WebSocket connected');
            this.isConnected = true;
            this.showStatus('Connected - Loading browser...', 'success');
        };

        this.ws.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                this.handleMessage(message);
            } catch (e) {
                console.error('[BrowserStreamViewer] Error parsing message:', e);
            }
        };

        this.ws.onerror = (error) => {
            console.error('[BrowserStreamViewer] WebSocket error:', error);
            this.showStatus('Connection error', 'error');
        };

        this.ws.onclose = () => {
            console.log('[BrowserStreamViewer] WebSocket closed');
            this.isConnected = false;
            this.showStatus('Disconnected', 'error');
        };
    }

    /**
     * Create canvas element and attach event handlers
     */
    createCanvas() {
        const wrapper = document.createElement('div');
        wrapper.className = 'browser-stream-wrapper';
        wrapper.style.cssText = `
            position: relative;
            width: 100%;
            height: 500px;
            background: #1a1a1a;
            border-radius: 8px;
            overflow: hidden;
        `;

        this.canvas = document.createElement('canvas');
        this.canvas.style.cssText = `
            width: 100%;
            height: 100%;
            cursor: pointer;
            object-fit: contain;
        `;
        this.ctx = this.canvas.getContext('2d');

        // Status overlay
        this.statusDiv = document.createElement('div');
        this.statusDiv.className = 'stream-status';
        this.statusDiv.style.cssText = `
            position: absolute;
            top: 10px;
            left: 10px;
            padding: 8px 12px;
            background: rgba(0, 0, 0, 0.7);
            color: white;
            border-radius: 4px;
            font-size: 12px;
            z-index: 10;
        `;
        this.statusDiv.textContent = 'Connecting...';

        wrapper.appendChild(this.canvas);
        wrapper.appendChild(this.statusDiv);
        this.container.appendChild(wrapper);

        // Attach event handlers
        this.attachEventHandlers();

        console.log('[BrowserStreamViewer] Canvas created');
    }

    /**
     * Attach mouse/touch event handlers to canvas
     */
    attachEventHandlers() {
        // Click handler
        this.canvas.addEventListener('click', (e) => {
            if (!this.isConnected) return;

            const rect = this.canvas.getBoundingClientRect();
            const scaleX = this.canvas.width / rect.width;
            const scaleY = this.canvas.height / rect.height;

            const x = Math.floor((e.clientX - rect.left) * scaleX);
            const y = Math.floor((e.clientY - rect.top) * scaleY);

            console.log(`[BrowserStreamViewer] Click at (${x}, ${y})`);
            this.sendEvent({type: 'click', x, y});
        });

        // Touch handler (for mobile)
        this.canvas.addEventListener('touchstart', (e) => {
            if (!this.isConnected) return;
            e.preventDefault();

            const touch = e.touches[0];
            const rect = this.canvas.getBoundingClientRect();
            const scaleX = this.canvas.width / rect.width;
            const scaleY = this.canvas.height / rect.height;

            const x = Math.floor((touch.clientX - rect.left) * scaleX);
            const y = Math.floor((touch.clientY - rect.top) * scaleY);

            console.log(`[BrowserStreamViewer] Touch at (${x}, ${y})`);
            this.sendEvent({type: 'click', x, y});
        });

        // Scroll handler
        this.canvas.addEventListener('wheel', (e) => {
            if (!this.isConnected) return;
            e.preventDefault();

            console.log(`[BrowserStreamViewer] Scroll delta=(${e.deltaX}, ${e.deltaY})`);
            this.sendEvent({
                type: 'scroll',
                delta_x: Math.floor(e.deltaX),
                delta_y: Math.floor(e.deltaY)
            });
        });

        console.log('[BrowserStreamViewer] Event handlers attached');
    }

    /**
     * Handle incoming WebSocket messages
     */
    handleMessage(message) {
        if (message.type === 'frame') {
            // Received a browser frame - display it
            this.displayFrame(message);
        } else if (message.type === 'error') {
            console.error('[BrowserStreamViewer] Server error:', message.message);
            this.showStatus(`Error: ${message.message}`, 'error');
        }
    }

    /**
     * Display a frame on the canvas
     */
    displayFrame(frame) {
        const img = new Image();
        img.onload = () => {
            // Update canvas dimensions to match frame
            if (this.canvas.width !== frame.width || this.canvas.height !== frame.height) {
                this.canvas.width = frame.width;
                this.canvas.height = frame.height;
            }

            // Draw frame
            this.ctx.drawImage(img, 0, 0);
            this.currentImage = img;

            // Update status
            this.showStatus('Live', 'success');
        };

        img.onerror = (e) => {
            console.error('[BrowserStreamViewer] Error loading frame:', e);
        };

        // Load image from base64
        img.src = `data:image/${frame.format};base64,${frame.image}`;
    }

    /**
     * Send interaction event to server
     */
    sendEvent(event) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            console.warn('[BrowserStreamViewer] WebSocket not connected, cannot send event');
            return;
        }

        this.ws.send(JSON.stringify(event));
    }

    /**
     * Show status message
     */
    showStatus(message, type = 'info') {
        if (!this.statusDiv) return;

        this.statusDiv.textContent = message;

        const colors = {
            success: '#4ade80',
            error: '#f87171',
            info: '#60a5fa'
        };

        this.statusDiv.style.color = colors[type] || colors.info;
    }

    /**
     * Disconnect and clean up
     */
    disconnect() {
        console.log('[BrowserStreamViewer] Disconnecting');

        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }

        this.isConnected = false;
        this.showStatus('Disconnected', 'error');
    }
}

// Make available globally
window.BrowserStreamViewer = BrowserStreamViewer;
