/**
 * Research Progress Handler
 *
 * Connects to Gateway WebSocket for real-time research monitoring.
 * Displays progress updates and intervention modals during research queries.
 */

class ResearchProgressHandler {
    constructor() {
        this.websocket = null;
        this.currentSessionId = null;
        this.isResearching = false;
        this.progressStats = {
            checked: 0,
            accepted: 0,
            rejected: 0,
            total: 0
        };

        console.log('[ResearchProgress] Handler initialized');
    }

    /**
     * Connect to WebSocket for a research session
     * @param {string} sessionId - Session/profile ID
     */
    connect(sessionId) {
        // Don't reconnect if already connected to same session
        if (this.websocket && this.websocket.readyState === WebSocket.OPEN && this.currentSessionId === sessionId) {
            console.log('[ResearchProgress] Already connected to session:', sessionId);
            return;
        }

        // Close existing connection if any
        this.disconnect();

        this.currentSessionId = sessionId;

        // Start polling for interventions as fallback (in case WebSocket events don't fire)
        this.startInterventionPolling();

        // Determine WebSocket protocol (ws or wss based on location protocol)
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        const wsUrl = `${protocol}//${host}/ws/research/${sessionId}`;

        console.log('[ResearchProgress] Connecting to WebSocket:', wsUrl);

        try {
            this.websocket = new WebSocket(wsUrl);

            this.websocket.onopen = () => {
                console.log('[ResearchProgress] WebSocket connected for session:', sessionId);
            };

            this.websocket.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleEvent(data);
                } catch (error) {
                    console.error('[ResearchProgress] Error parsing message:', error, event.data);
                }
            };

            this.websocket.onerror = (error) => {
                console.error('[ResearchProgress] WebSocket error:', error);
            };

            this.websocket.onclose = () => {
                console.log('[ResearchProgress] WebSocket closed');
                this.websocket = null;
            };
        } catch (error) {
            console.error('[ResearchProgress] Error creating WebSocket:', error);
        }
    }

    /**
     * Disconnect from WebSocket
     */
    disconnect() {
        if (this.websocket) {
            console.log('[ResearchProgress] Disconnecting WebSocket');
            this.websocket.close();
            this.websocket = null;
        }
        this.stopInterventionPolling();
        this.currentSessionId = null;
        this.isResearching = false;
        this.progressStats = { checked: 0, accepted: 0, rejected: 0, total: 0 };
    }

    /**
     * Handle incoming WebSocket event
     * @param {object} event - Event data from server
     */
    handleEvent(event) {
        const eventType = event.type;
        const data = event.data || {};

        console.log('[ResearchProgress] Event:', eventType, data);

        switch (eventType) {
            case 'research_started':
                this.handleResearchStarted(data);
                break;
            case 'strategy_selected':
                this.handleStrategySelected(data);
                break;
            case 'search_started':
                this.handleSearchStarted(data);
                break;
            case 'candidate_checking':
                this.handleCandidateChecking(data);
                break;
            case 'fetch_complete':
                this.handleFetchComplete(data);
                break;
            case 'blocker_detected':
                this.handleBlockerDetected(data);
                break;
            case 'intervention_needed':
                this.handleInterventionNeeded(data);
                break;
            case 'intervention_resolved':
                this.handleInterventionResolved(data);
                break;
            case 'candidate_accepted':
                this.handleCandidateAccepted(data);
                break;
            case 'candidate_rejected':
                this.handleCandidateRejected(data);
                break;
            case 'progress':
                this.handleProgress(data);
                break;
            case 'phase_started':
                this.handlePhaseStarted(data);
                break;
            case 'phase_complete':
                this.handlePhaseComplete(data);
                break;
            case 'search_complete':
                this.handleSearchComplete(data);
                break;
            case 'research_complete':
                this.handleResearchComplete(data);
                break;
            default:
                console.log('[ResearchProgress] Unknown event type:', eventType);
        }
    }

    /**
     * Update thinking message with progress
     */
    updateThinkingMessage(message) {
        // Update existing thinking visualizer if available
        if (window.thinkingVisualizer && window.thinkingVisualizer.updateInlineMessage) {
            window.thinkingVisualizer.updateInlineMessage(message);
        }
    }

    /**
     * Add progress message to chat window
     */
    addProgressMessage(message, type = 'info') {
        const chatWindow = document.getElementById('chat-window');
        if (!chatWindow) return;

        const progressDiv = document.createElement('div');
        progressDiv.className = `research-progress research-${type}`;
        progressDiv.style.cssText = `
            background: #1a1a22;
            border-left: 3px solid ${type === 'success' ? '#7fd288' : type === 'warning' ? '#ffa500' : '#68a8ef'};
            padding: 8px 12px;
            margin: 4px 0;
            font-size: 0.85em;
            color: #9aa3c2;
            border-radius: 4px;
        `;
        progressDiv.textContent = message;

        chatWindow.appendChild(progressDiv);
        chatWindow.scrollTop = chatWindow.scrollHeight;
    }

    // Event handlers

    /**
     * Handle research_started event - clear previous progress messages
     */
    handleResearchStarted(data) {
        console.log('[ResearchProgress] New research session started, clearing previous progress');

        // Clear all previous progress messages
        const chatWindow = document.getElementById('chat-window');
        if (chatWindow) {
            const progressMessages = chatWindow.querySelectorAll('.research-progress');
            progressMessages.forEach(msg => msg.remove());
        }

        // Reset stats
        this.progressStats = { checked: 0, accepted: 0, rejected: 0, total: 0 };
        this.isResearching = true;

        this.addProgressMessage('🔍 Research session started', 'info');
    }

    handleStrategySelected(data) {
        const { strategy, reason, confidence, estimated_duration } = data;
        const strategyEmoji = strategy === 'quick' ? '⚡' : strategy === 'standard' ? '📦' : '🔬';
        const strategyLabel = strategy.toUpperCase();
        const durationText = estimated_duration ? `~${estimated_duration}s` : '';

        this.updateThinkingMessage(`${strategyEmoji} Strategy: ${strategyLabel} ${durationText}`);
        this.addProgressMessage(
            `${strategyEmoji} Selected ${strategyLabel} strategy (confidence: ${(confidence * 100).toFixed(0)}%) - ${reason}`,
            'info'
        );
    }

    handleSearchStarted(data) {
        this.isResearching = true;
        this.progressStats = { checked: 0, accepted: 0, rejected: 0, total: data.max_candidates || 0 };
        this.updateThinkingMessage(`Starting research: ${data.query}`);
        this.addProgressMessage(`🔍 Searching for: ${data.query} (checking up to ${data.max_candidates} sources)`, 'info');
    }

    handleCandidateChecking(data) {
        const { index, total, url, title } = data;
        this.updateThinkingMessage(`Checking source ${index}/${total}: ${title || url}`);
    }

    handleFetchComplete(data) {
        const { url, success, error } = data;
        if (!success && error) {
            console.log('[ResearchProgress] Fetch failed:', url, error);
        }
    }

    handleBlockerDetected(data) {
        const { url, blocker_type, confidence } = data;
        console.log('[ResearchProgress] Blocker detected:', blocker_type, 'at', url, 'confidence:', confidence);
        this.updateThinkingMessage(`⚠️ Blocker detected: ${blocker_type}`);
    }

    handleInterventionNeeded(data) {
        const { intervention_id, url, blocker_type, screenshot_path, cdp_url } = data;
        console.log('[ResearchProgress] Intervention needed:', intervention_id, blocker_type, 'at', url);

        // Make intervention messages more user-friendly
        const friendlyMessages = {
            'captcha': '🔒 CAPTCHA detected - please solve',
            'unknown_blocker': '⏳ Waiting for page to load...',
            'rate_limit': '⏸️ Rate limit detected - please verify',
            'access_denied': '🚫 Access denied - verification needed',
            'login_required': '🔐 Login required'
        };

        const message = friendlyMessages[blocker_type] || `🔒 Verification needed: ${blocker_type}`;
        this.updateThinkingMessage(message);

        // Show intervention UI inline in chat window instead of separate panel
        this.showInterventionInChat(intervention_id, url, blocker_type, screenshot_path, cdp_url);
    }

    showInterventionPanel(intervention_id, url, blocker_type, screenshot_path) {
        const panel = document.getElementById('research-panel');
        if (!panel) return;

        // Create intervention section in the panel
        const interventionSection = document.createElement('div');
        interventionSection.id = `intervention-${intervention_id}`;
        interventionSection.className = 'intervention-section';
        interventionSection.style.cssText = `
            background: #2a1a1a;
            border: 2px solid #ff6b6b;
            border-radius: 8px;
            padding: 16px;
            margin: 16px 0;
        `;

        const domain = new URL(url).hostname.replace('www.', '');
        const typeLabels = {
            'captcha_recaptcha': 'reCAPTCHA',
            'captcha_hcaptcha': 'hCaptcha',
            'captcha_cloudflare': 'Cloudflare Challenge',
            'captcha_generic': 'CAPTCHA',
            'login_required': 'Login Required',
            'rate_limit': 'Rate Limited',
            'bot_detection': 'Bot Detection',
        };
        const typeLabel = typeLabels[blocker_type] || blocker_type;

        interventionSection.innerHTML = `
            <div style="margin-bottom: 12px;">
                <strong style="color: #ff6b6b; font-size: 1.1em;">🔒 Human Assistance Required</strong>
                <span style="background: #ff6b6b; color: white; padding: 4px 12px; border-radius: 4px; margin-left: 12px; font-size: 0.9em;">${typeLabel}</span>
            </div>
            <div style="color: #cfd3e9; margin-bottom: 12px;">
                <strong>${domain}</strong> requires you to solve a ${typeLabel}. Solve the challenge in the live browser below - cookies will be automatically captured and saved to your server session.
            </div>
            <div style="background: #1a1a22; padding: 10px; border-radius: 4px; margin-bottom: 16px; font-family: monospace; font-size: 0.85em; color: #9aa3c2; word-break: break-all;">
                ${url}
            </div>
            <div style="margin-bottom: 16px;">
                <div id="browser-stream-container-${intervention_id}" style="min-height: 400px;"></div>
            </div>
            <div style="display: flex; gap: 12px; flex-wrap: wrap;">
                <button onclick="window.researchProgressHandler.resolveIntervention('${intervention_id}', true)"
                        style="padding: 10px 20px; background: #7fd288; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;">
                    ✓ Solved - Continue
                </button>
                <button onclick="window.researchProgressHandler.resolveIntervention('${intervention_id}', false)"
                        style="padding: 10px 20px; background: #9aa3c2; color: white; border: none; border-radius: 4px; cursor: pointer;">
                    Skip This Page
                </button>
                <button onclick="window.open('${url}', '_blank')"
                        style="padding: 10px 20px; background: #3a3a43; color: white; border: none; border-radius: 4px; cursor: pointer;">
                    🔗 Open in New Tab (Fallback)
                </button>
            </div>
        `;

        // Start browser streaming after DOM is ready
        setTimeout(() => {
            this.startBrowserStream(intervention_id);
        }, 100);

        // Insert at top of progress messages
        const progressMessages = panel.querySelector('.progress-messages');
        if (progressMessages && progressMessages.firstChild) {
            progressMessages.insertBefore(interventionSection, progressMessages.firstChild);
        } else if (progressMessages) {
            progressMessages.appendChild(interventionSection);
        }
    }

    showInterventionInChat(intervention_id, url, blocker_type, screenshot_path, cdp_url) {
        const chatWindow = document.getElementById('chat-window');
        if (!chatWindow) {
            console.warn('[ResearchProgress] Chat window not found, cannot show intervention');
            return;
        }

        const domain = new URL(url).hostname.replace('www.', '');
        const typeLabels = {
            'captcha_recaptcha': 'reCAPTCHA',
            'captcha_hcaptcha': 'hCaptcha',
            'captcha_cloudflare': 'Cloudflare Challenge',
            'captcha_generic': 'CAPTCHA',
            'login_required': 'Login Required',
            'rate_limit': 'Rate Limited',
            'bot_detection': 'Bot Detection',
            'extraction_failed': 'Extraction Failed',
        };
        const typeLabel = typeLabels[blocker_type] || blocker_type;

        // Determine icon and title based on blocker type
        const isExtractionFailed = blocker_type === 'extraction_failed';
        const icon = isExtractionFailed ? '🔍' : '🔒';
        const title = isExtractionFailed ? 'Extraction Failed' : 'CAPTCHA Detected';
        const borderColor = isExtractionFailed ? '#f0ad4e' : '#ff6b6b';
        const buttonColor = isExtractionFailed ? '#f0ad4e' : '#ff6b6b';

        // Create intervention message in chat
        const interventionDiv = document.createElement('div');
        interventionDiv.className = 'message assistant';
        interventionDiv.style.background = '#2a1a1a';
        interventionDiv.style.borderLeft = `4px solid ${borderColor}`;
        interventionDiv.id = `intervention-chat-${intervention_id}`;

        // Extract screenshot filename
        const screenshotFilename = screenshot_path ? screenshot_path.split('/').pop() : null;
        const screenshotUrl = screenshotFilename ? `/screenshots/${screenshotFilename}` : null;

        // Message text based on type
        const messageText = isExtractionFailed
            ? 'Could not extract products from this page. Click "Open Browser" to see what the browser sees.'
            : (cdp_url
                ? 'Click "Open Browser" to view the live browser session via noVNC and solve the CAPTCHA.'
                : 'Open the challenge page and solve the CAPTCHA, then click "I Solved It".');

        interventionDiv.innerHTML = `
            <div style="margin-bottom: 10px;">
                <strong style="color: ${borderColor};">${icon} ${title}</strong>
                <span style="background: ${borderColor}; color: white; padding: 2px 8px; border-radius: 4px; margin-left: 8px; font-size: 0.85em;">${domain}</span>
                <span style="color: #888; margin-left: 8px; font-size: 0.85em;">${typeLabel}</span>
            </div>
            <div style="color: #cfd3e9; margin-bottom: 12px;">
                ${messageText}
            </div>
            ${screenshotUrl ? `
            <div style="margin-bottom: 12px;">
                <img src="${screenshotUrl}"
                     style="max-width: 100%; border: 1px solid #444; border-radius: 4px; cursor: pointer;"
                     onclick="window.open('${screenshotUrl}', '_blank')"
                     title="Click to view full size" />
            </div>` : ''}
            <div style="display: flex; gap: 8px;">
                ${cdp_url ? `
                <button onclick="window.open('${cdp_url}', '_blank', 'width=1400,height=900')"
                        style="padding: 10px 20px; background: ${buttonColor}; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 1.05em;">
                    🖥️ Open Browser
                </button>` : `
                <button onclick="window.open('${url}', '_blank')"
                        style="padding: 10px 20px; background: #3a3a43; color: white; border: none; border-radius: 4px; cursor: pointer;">
                    🔗 Open Challenge Page
                </button>`}
                <button onclick="window.researchProgressHandler.resolveInterventionInChat('${intervention_id}', false)"
                        style="padding: 10px 20px; background: #666; color: white; border: none; border-radius: 4px; cursor: pointer;">
                    ${isExtractionFailed ? 'Continue' : 'Skip'}
                </button>
            </div>
        `;

        chatWindow.appendChild(interventionDiv);
        chatWindow.scrollTop = chatWindow.scrollHeight;
    }

    async resolveInterventionInChat(intervention_id, success) {
        console.log('[ResearchProgress] Resolving intervention from chat:', intervention_id, 'success:', success);

        try {
            const response = await fetch(`/interventions/${intervention_id}/resolve`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ resolved: success, cookies: null })
            });

            if (response.ok) {
                console.log('[ResearchProgress] Intervention resolved successfully');

                // Update the intervention div in chat
                const interventionDiv = document.getElementById(`intervention-chat-${intervention_id}`);
                if (interventionDiv) {
                    interventionDiv.style.opacity = '0.5';
                    interventionDiv.style.pointerEvents = 'none';

                    // Add success/skip message
                    const statusDiv = document.createElement('div');
                    statusDiv.style.marginTop = '12px';
                    statusDiv.style.padding = '8px';
                    statusDiv.style.background = success ? '#1a2f1a' : '#2a2a2a';
                    statusDiv.style.borderRadius = '4px';
                    statusDiv.style.color = success ? '#4caf50' : '#999';
                    statusDiv.style.fontWeight = 'bold';
                    statusDiv.innerHTML = success ?
                        '✓ Resolved - Research continuing...' :
                        '⏭️ Skipped - Research continuing...';
                    interventionDiv.appendChild(statusDiv);
                }

                if (success) {
                    this.addProgressMessage(`✓ CAPTCHA solved - resuming research`, 'success');
                } else {
                    this.addProgressMessage(`⏭️ Page skipped - continuing with other sources`, 'info');
                }
            } else {
                console.error('[ResearchProgress] Failed to resolve intervention:', response.statusText);
                alert('Failed to resolve intervention. Please try again.');
            }
        } catch (error) {
            console.error('[ResearchProgress] Error resolving intervention:', error);
            alert('Error resolving intervention: ' + error.message);
        }
    }

    async resolveIntervention(intervention_id, success) {
        try {
            const response = await fetch(`/interventions/${intervention_id}/resolve`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ resolved: success, cookies: null })
            });

            if (response.ok) {
                console.log('[ResearchProgress] Intervention resolved:', intervention_id, success);

                // Remove the intervention UI
                const interventionSection = document.getElementById(`intervention-${intervention_id}`);
                if (interventionSection) {
                    interventionSection.remove();
                }

                if (success) {
                    this.addProgressMessage(`✓ CAPTCHA solved - resuming research`, 'success');
                } else {
                    this.addProgressMessage(`⏭️ Page skipped - continuing with other sources`, 'info');
                }
            }
        } catch (error) {
            console.error('[ResearchProgress] Error resolving intervention:', error);
            alert('Error resolving intervention: ' + error.message);
        }
    }

    handleInterventionResolved(data) {
        const { intervention_id, action, success } = data;
        if (success) {
            this.updateThinkingMessage(`✓ Intervention resolved, continuing research...`);
            this.addProgressMessage(`✓ CAPTCHA solved - resuming research`, 'success');
        } else {
            this.updateThinkingMessage(`Skipped intervention, continuing...`);
            this.addProgressMessage(`⏭️ Page skipped - continuing with other sources`, 'info');
        }
    }

    handleCandidateAccepted(data) {
        const { url, title, quality_score, partial } = data;
        this.progressStats.accepted++;
        this.updateThinkingMessage(`✓ Accepted: ${title || url}`);

        // Only show message for full extractions (not partial reads)
        if (!partial) {
            const domain = new URL(url).hostname.replace('www.', '');
            this.addProgressMessage(`✓ Extracted data from ${domain} (quality: ${(quality_score * 100).toFixed(0)}%)`, 'success');
        }
    }

    handleCandidateRejected(data) {
        const { url, title, reason } = data;
        this.progressStats.rejected++;
        console.log('[ResearchProgress] Rejected:', title || url, 'reason:', reason);
    }

    handleProgress(data) {
        const { checked, total, accepted, rejected, progress_pct } = data;
        this.progressStats = { checked, accepted, rejected, total };
        this.updateThinkingMessage(`Progress: ${checked}/${total} checked (${accepted} accepted, ${rejected} rejected)`);
    }

    handlePhaseStarted(data) {
        const { phase, description } = data;
        this.updateThinkingMessage(`Phase: ${phase} - ${description}`);
        this.addProgressMessage(`📋 ${description}`, 'info');
    }

    handlePhaseComplete(data) {
        const { phase, result } = data;
        console.log('[ResearchProgress] Phase complete:', phase, result);
    }

    handleSearchComplete(data) {
        const { total_checked, total_accepted, total_rejected, duration_ms } = data;
        const durationSec = (duration_ms / 1000).toFixed(1);
        this.updateThinkingMessage(`Search complete: ${total_accepted} sources found in ${durationSec}s`);
        this.addProgressMessage(`✓ Search complete: Found ${total_accepted} relevant sources (checked ${total_checked} candidates in ${durationSec}s)`, 'success');
    }

    handleResearchComplete(data) {
        this.isResearching = false;
        const { synthesis } = data;
        console.log('[ResearchProgress] Research complete:', synthesis);
        this.updateThinkingMessage(`Research complete - synthesizing results...`);

        // Disconnect WebSocket after research completes
        setTimeout(() => {
            this.disconnect();
        }, 2000);
    }

    startBrowserStream(intervention_id) {
        console.log('[ResearchProgress] Starting browser stream for intervention:', intervention_id);

        // Create browser stream viewer instance
        const containerId = `browser-stream-container-${intervention_id}`;
        const viewer = new BrowserStreamViewer(containerId);

        // Connect to stream
        viewer.connect(intervention_id);

        // Store viewer instance for cleanup
        if (!this.browserStreamViewers) {
            this.browserStreamViewers = {};
        }
        this.browserStreamViewers[intervention_id] = viewer;

        console.log('[ResearchProgress] Browser stream viewer created and connected');
    }

    startInterventionPolling() {
        // Poll for interventions every 2 seconds as fallback
        if (this.interventionPollInterval) {
            clearInterval(this.interventionPollInterval);
        }

        this.interventionPollInterval = setInterval(async () => {
            try {
                // Use /interventions/pending to get ALL intervention types
                // (captcha, extraction_failed, login_required, etc.)
                const response = await fetch('/interventions/pending');
                if (response.ok) {
                    const data = await response.json();
                    const interventions = data.interventions || [];

                    for (const intervention of interventions) {
                        // Check if we've already shown this intervention
                        const interventionDiv = document.getElementById(`intervention-chat-${intervention.intervention_id}`);
                        if (!interventionDiv) {
                            console.log('[ResearchProgress] Found pending intervention via polling:', intervention.intervention_id);
                            // Show it in chat
                            this.showInterventionInChat(
                                intervention.intervention_id,
                                intervention.url,
                                intervention.type,
                                intervention.screenshot_path,
                                intervention.cdp_url
                            );
                        }
                    }
                }
            } catch (error) {
                console.warn('[ResearchProgress] Error polling for interventions:', error);
            }
        }, 2000);

        console.log('[ResearchProgress] Started intervention polling (every 2s)');
    }

    stopInterventionPolling() {
        if (this.interventionPollInterval) {
            clearInterval(this.interventionPollInterval);
            this.interventionPollInterval = null;
            console.log('[ResearchProgress] Stopped intervention polling');
        }
    }
}

// Global instance - auto-initialize
if (typeof window !== 'undefined') {
    window.researchProgressHandler = new ResearchProgressHandler();
    console.log('[ResearchProgress] Global handler created');

    // Start polling immediately on page load to catch any existing interventions
    window.addEventListener('DOMContentLoaded', () => {
        console.log('[ResearchProgress] Starting intervention polling on page load');
        window.researchProgressHandler.startInterventionPolling();
    });
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ResearchProgressHandler;
}
