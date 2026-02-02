/**
 * Permission prompt handler for code mode operations outside saved repo.
 *
 * Polls for pending permission requests and displays inline approval prompts
 * in the chat window when operations target paths outside the saved repository.
 */

class PermissionHandler {
    constructor() {
        this.pendingPermissions = new Map();
        this.pollInterval = null;
        this.pollMs = 2000;  // Poll every 2 seconds

        // Start polling for permission requests
        this.startPolling();
    }

    startPolling() {
        if (this.pollInterval) return;

        console.log('[PermissionHandler] Starting permission polling');
        this.pollInterval = setInterval(() => this.checkPendingPermissions(), this.pollMs);

        // Initial check
        this.checkPendingPermissions();
    }

    stopPolling() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
            console.log('[PermissionHandler] Stopped permission polling');
        }
    }

    async checkPendingPermissions() {
        try {
            const response = await fetch('/api/permissions/pending');
            if (!response.ok) {
                console.warn('[PermissionHandler] Failed to fetch pending permissions:', response.status);
                return;
            }

            const data = await response.json();
            const requests = data.requests || [];

            // Show new permission requests
            for (const request of requests) {
                if (!this.pendingPermissions.has(request.request_id)) {
                    this.pendingPermissions.set(request.request_id, request);
                    this.showPermissionPrompt(request);
                }
            }

            // Remove resolved requests from our tracking
            const currentIds = new Set(requests.map(r => r.request_id));
            for (const [id] of this.pendingPermissions) {
                if (!currentIds.has(id)) {
                    this.pendingPermissions.delete(id);
                }
            }
        } catch (error) {
            // Silently fail - permission endpoint may not be available
            console.debug('[PermissionHandler] Error checking permissions:', error.message);
        }
    }

    showPermissionPrompt(request) {
        console.log('[PermissionHandler] Showing permission prompt:', request);

        const chatWindow = document.getElementById('chat-window');
        if (!chatWindow) {
            console.warn('[PermissionHandler] Chat window not found');
            return;
        }

        // Check if already displayed
        if (document.getElementById(`permission-${request.request_id}`)) {
            return;
        }

        // Create inline permission prompt
        const promptDiv = document.createElement('div');
        promptDiv.className = 'message assistant';
        promptDiv.style.background = '#1a2a1a';
        promptDiv.style.borderLeft = '4px solid #ffa500';
        promptDiv.id = `permission-${request.request_id}`;

        const tool = request.tool || 'unknown';
        const targetPath = request.target_path || 'unknown path';
        const savedRepo = request.operation_details?.saved_repo || 'not configured';

        // Extract just the path relative to home for cleaner display
        const displayPath = targetPath.replace(/^\/home\/[^/]+\//, '~/');
        const displaySavedRepo = savedRepo.replace(/^\/home\/[^/]+\//, '~/');

        promptDiv.innerHTML = `
            <div style="margin-bottom: 10px;">
                <strong style="color: #ffa500;">⚠️ Permission Required</strong>
                <span style="background: #ffa500; color: #1a1a22; padding: 2px 8px; border-radius: 4px; margin-left: 8px; font-size: 0.85em; font-weight: bold;">${this.escapeHtml(tool)}</span>
            </div>
            <div style="color: #cfd3e9; margin-bottom: 12px;">
                Operation targets path <strong>outside</strong> your saved repository:
            </div>
            <div style="background: #101014; padding: 10px; border-radius: 4px; margin-bottom: 12px; font-family: monospace; font-size: 0.9em;">
                <div style="margin-bottom: 6px;">
                    <span style="color: #9aa3c2;">Target:</span>
                    <span style="color: #ff6b6b;">${this.escapeHtml(displayPath)}</span>
                </div>
                <div>
                    <span style="color: #9aa3c2;">Saved Repo:</span>
                    <span style="color: #7fd288;">${this.escapeHtml(displaySavedRepo)}</span>
                </div>
            </div>
            <div style="color: #9aa3c2; font-size: 0.85em; margin-bottom: 12px;">
                Do you want to allow this operation?
            </div>
            <div style="display: flex; gap: 8px;">
                <button onclick="window.permissionHandler.resolvePermission('${request.request_id}', true)"
                        style="padding: 8px 16px; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;">
                    ✓ Approve
                </button>
                <button onclick="window.permissionHandler.resolvePermission('${request.request_id}', false)"
                        style="padding: 8px 16px; background: #dc3545; color: white; border: none; border-radius: 4px; cursor: pointer;">
                    ✗ Deny
                </button>
            </div>
        `;

        chatWindow.appendChild(promptDiv);
        chatWindow.scrollTop = chatWindow.scrollHeight;

        // Play a subtle notification sound if available
        this.playNotificationSound();
    }

    async resolvePermission(requestId, approved) {
        console.log('[PermissionHandler] Resolving permission:', requestId, 'approved:', approved);

        try {
            const response = await fetch(`/api/permissions/${requestId}/resolve`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    approved: approved,
                    reason: approved ? 'user_approved' : 'user_denied'
                })
            });

            if (response.ok) {
                console.log('[PermissionHandler] Permission resolved successfully');
                this.updatePromptStatus(requestId, approved);
            } else {
                const errorData = await response.json().catch(() => ({}));
                console.error('[PermissionHandler] Failed to resolve permission:', errorData.error || response.statusText);
                alert('Failed to resolve permission request. Please try again.');
            }
        } catch (error) {
            console.error('[PermissionHandler] Error resolving permission:', error);
            alert('Error resolving permission: ' + error.message);
        }
    }

    updatePromptStatus(requestId, approved) {
        const promptDiv = document.getElementById(`permission-${requestId}`);
        if (!promptDiv) return;

        // Fade out and show status
        promptDiv.style.opacity = '0.6';
        promptDiv.style.pointerEvents = 'none';

        // Update border color based on result
        promptDiv.style.borderLeftColor = approved ? '#4caf50' : '#dc3545';

        // Add status message
        const statusDiv = document.createElement('div');
        statusDiv.style.marginTop = '8px';
        statusDiv.style.fontWeight = 'bold';
        statusDiv.style.color = approved ? '#4caf50' : '#dc3545';
        statusDiv.innerHTML = approved
            ? '✓ Approved - Operation proceeding...'
            : '✗ Denied - Operation cancelled';
        promptDiv.appendChild(statusDiv);

        // Remove from tracking
        this.pendingPermissions.delete(requestId);
    }

    playNotificationSound() {
        // Create a subtle beep for permission requests
        try {
            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = audioContext.createOscillator();
            const gainNode = audioContext.createGain();

            oscillator.connect(gainNode);
            gainNode.connect(audioContext.destination);

            oscillator.frequency.value = 440;  // A4 note
            oscillator.type = 'sine';
            gainNode.gain.value = 0.1;  // Low volume

            oscillator.start();
            oscillator.stop(audioContext.currentTime + 0.1);  // 100ms beep
        } catch (e) {
            // Audio not available, ignore
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    shutdown() {
        this.stopPolling();
    }
}

// Global instance - auto-initialize
if (typeof window !== 'undefined') {
    window.permissionHandler = new PermissionHandler();
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = PermissionHandler;
}
