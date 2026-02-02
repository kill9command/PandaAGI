/**
 * Human intervention handler for CAPTCHA solving and auth walls.
 *
 * Listens for intervention requests via polling, displays modal with
 * screenshot + iframe, and sends resolution back to Gateway.
 */

class InterventionHandler {
    constructor() {
        this.pendingInterventions = new Map();
        this.currentIntervention = null;
        this.pollInterval = null;

        // Create modal if it doesn't exist
        this.ensureModal();

        // Bind event handlers
        this.bindEventHandlers();

        // Start polling for interventions
        this.startPolling();
    }

    ensureModal() {
        if (!document.getElementById('intervention-modal')) {
            const modalHTML = `
                <div id="intervention-modal" class="modal hidden">
                    <div class="modal-overlay"></div>
                    <div class="modal-content intervention-content">
                        <div class="modal-header">
                            <h3>Human Assistance Required</h3>
                            <span id="intervention-type-badge" class="badge"></span>
                            <button id="intervention-close" class="close-btn">&times;</button>
                        </div>
                        <div class="modal-body">
                            <p id="intervention-message"></p>
                            <div id="intervention-url-display" class="url-display"></div>

                            <div class="intervention-view">
                                <div class="screenshot-container">
                                    <h4>Page Screenshot</h4>
                                    <img id="intervention-screenshot" />
                                </div>

                                <div class="iframe-container">
                                    <h4>Solve the challenge below:</h4>
                                    <iframe id="intervention-frame" sandbox="allow-same-origin allow-scripts allow-forms"></iframe>
                                    <p class="help-text">After solving, click "I've Solved It" below</p>
                                </div>
                            </div>

                            <div class="intervention-actions">
                                <button id="intervention-done" class="btn btn-primary">
                                    ✓ I've Solved It - Continue
                                </button>
                                <button id="intervention-skip" class="btn btn-secondary">
                                    Skip This Page
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            document.body.insertAdjacentHTML('beforeend', modalHTML);
        }
    }

    bindEventHandlers() {
        document.getElementById('intervention-done').onclick = () => this.resolveIntervention(true);
        document.getElementById('intervention-skip').onclick = () => this.resolveIntervention(false);
        document.getElementById('intervention-close').onclick = () => this.closeModal();
    }

    startPolling() {
        // DISABLED: Interventions now handled via WebSocket events in research_progress.js
        // No need to poll - the research monitor panel handles everything
        console.log('[InterventionHandler] Polling disabled - using WebSocket events');
    }

    stopPolling() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
        }
    }

    async checkPendingInterventions() {
        // DISABLED: All intervention handling moved to research_progress.js via WebSocket
        // This prevents duplicate UI elements and popup modals
        return;
    }

    showIntervention(intervention) {
        console.log('[InterventionHandler] DEPRECATED - All interventions handled by Research Monitor panel');
        // DO NOTHING - Research Monitor panel handles all intervention UI
        // This prevents duplicate notifications in chat
    }

    addInterventionToChatWindow(intervention, typeLabel) {
        const chatWindow = document.getElementById('chat-window');
        if (!chatWindow) return;

        // Create inline notification with Playwright browser view and Mark Resolved button
        const interventionDiv = document.createElement('div');
        interventionDiv.className = 'message assistant';
        interventionDiv.style.background = '#2a1a1a';
        interventionDiv.style.borderLeft = '4px solid #ff6b6b';
        interventionDiv.id = `intervention-${intervention.intervention_id}`;

        const domain = new URL(intervention.url).hostname.replace('www.', '');

        // Extract screenshot filename from path
        const screenshotPath = intervention.screenshot_path;
        const screenshotFilename = screenshotPath ? screenshotPath.split('/').pop() : null;
        const screenshotUrl = screenshotFilename ? `/screenshots/${screenshotFilename}` : null;

        // Get CDP URL for Playwright browser access
        const cdpUrl = intervention.cdp_url;

        interventionDiv.innerHTML = `
            <div style="margin-bottom: 10px;">
                <strong style="color: #ff6b6b;">🔒 CAPTCHA Detected</strong>
                <span style="background: #ff6b6b; color: white; padding: 2px 8px; border-radius: 4px; margin-left: 8px; font-size: 0.85em;">${domain}</span>
                <span style="color: #888; margin-left: 8px; font-size: 0.85em;">${typeLabel}</span>
            </div>
            <div style="color: #cfd3e9; margin-bottom: 12px;">
                Solve the CAPTCHA in the browser below, then click "Mark Resolved".
            </div>
            ${cdpUrl ? `
            <div style="margin-bottom: 12px;">
                <iframe src="${cdpUrl}"
                        style="width: 100%; height: 600px; border: 2px solid #ff6b6b; border-radius: 4px; background: white;"
                        sandbox="allow-same-origin allow-scripts allow-forms allow-popups"
                        title="Playwright Browser - Solve CAPTCHA Here">
                </iframe>
                <div style="margin-top: 8px; color: #888; font-size: 0.85em;">
                    ⬆️ Solve the CAPTCHA in the browser above
                </div>
            </div>` : screenshotUrl ? `
            <div style="margin-bottom: 12px;">
                <img src="${screenshotUrl}"
                     style="max-width: 100%; border: 1px solid #444; border-radius: 4px; cursor: pointer;"
                     onclick="window.open('${screenshotUrl}', '_blank')"
                     title="Click to view full size" />
            </div>` : ''}
            <div style="display: flex; gap: 8px;">
                ${cdpUrl ? `
                <button onclick="window.open('${cdpUrl}', '_blank', 'width=1200,height=800')"
                        style="padding: 8px 16px; background: #3a3a43; color: white; border: none; border-radius: 4px; cursor: pointer;">
                    🖥️ Open in New Window
                </button>` : `
                <button onclick="window.open('${intervention.url}', '_blank')"
                        style="padding: 8px 16px; background: #3a3a43; color: white; border: none; border-radius: 4px; cursor: pointer;">
                    🔗 Open Challenge Page
                </button>`}
                <button onclick="window.interventionHandler.resolveInterventionInline('${intervention.intervention_id}', true)"
                        style="padding: 8px 16px; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;">
                    ✓ Mark Resolved
                </button>
                <button onclick="window.interventionHandler.resolveInterventionInline('${intervention.intervention_id}', false)"
                        style="padding: 8px 16px; background: #666; color: white; border: none; border-radius: 4px; cursor: pointer;">
                    Skip
                </button>
            </div>
        `;

        chatWindow.appendChild(interventionDiv);
        chatWindow.scrollTop = chatWindow.scrollHeight;
    }

    async resolveInterventionInline(interventionId, success) {
        console.log('[InterventionHandler] Resolving inline:', interventionId, 'success:', success);

        try {
            const response = await fetch(`/interventions/${interventionId}/resolve`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    resolved: success,
                    cookies: null
                })
            });

            if (response.ok) {
                console.log('[InterventionHandler] Resolution sent successfully');

                // Remove the intervention div from chat
                const interventionDiv = document.getElementById(`intervention-${interventionId}`);
                if (interventionDiv) {
                    interventionDiv.style.opacity = '0.5';
                    interventionDiv.style.pointerEvents = 'none';

                    // Add success message
                    const statusDiv = document.createElement('div');
                    statusDiv.style.marginTop = '8px';
                    statusDiv.style.color = success ? '#4caf50' : '#999';
                    statusDiv.style.fontWeight = 'bold';
                    statusDiv.innerHTML = success ? '✓ Resolved - Research continuing...' : 'Skipped';
                    interventionDiv.appendChild(statusDiv);
                }
            } else {
                console.error('[InterventionHandler] Failed to send resolution:', response.statusText);
                alert('Failed to resolve intervention. Please try again.');
            }
        } catch (error) {
            console.error('[InterventionHandler] Error resolving intervention:', error);
            alert('Error resolving intervention: ' + error.message);
        }
    }

    showModal() {
        // Re-show the modal if it was closed
        document.getElementById('intervention-modal').classList.remove('hidden');
    }

    async resolveIntervention(success) {
        if (!this.currentIntervention) return;

        const interventionId = this.currentIntervention.intervention_id;

        console.log('[InterventionHandler] Resolving:', interventionId, 'success:', success);

        try {
            const response = await fetch(`/interventions/${interventionId}/resolve`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    resolved: success,
                    cookies: null  // TODO: Extract cookies from iframe if possible
                })
            });

            if (response.ok) {
                console.log('[InterventionHandler] Resolution sent successfully');
                this.closeModal();
            } else {
                console.error('[InterventionHandler] Failed to send resolution:', response.statusText);
                alert('Failed to resolve intervention. Please try again.');
            }
        } catch (error) {
            console.error('[InterventionHandler] Error resolving intervention:', error);
            alert('Error resolving intervention: ' + error.message);
        }
    }

    closeModal() {
        document.getElementById('intervention-modal').classList.add('hidden');
        this.currentIntervention = null;

        // Resume polling
        this.startPolling();
    }

    shutdown() {
        this.stopPolling();
    }
}

// Global instance - auto-initialize
if (typeof window !== 'undefined') {
    window.interventionHandler = new InterventionHandler();
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = InterventionHandler;
}
