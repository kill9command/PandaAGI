
// ==================== CAPTCHA INTERVENTION SYSTEM ====================

let captchaPollInterval = null;
let pendingChallenges = [];

let displayedInterventions = new Set();

async function checkPendingCaptchas() {
  try {
    // Use Gateway endpoint (port 9000) instead of Orchestrator
    const gateway_url = window.location.protocol + '//' + window.location.hostname + ':' + window.location.port;
    const resp = await fetch(`${gateway_url}/interventions/pending`);

    if (!resp.ok) return;

    const data = await resp.json();
    pendingChallenges = data.interventions || [];

    const banner = document.getElementById('captcha-banner');
    const countSpan = document.getElementById('captcha-count');

    if (pendingChallenges.length > 0) {
      banner.style.display = 'block';
      countSpan.textContent = ` - ${pendingChallenges.length} site${pendingChallenges.length > 1 ? 's' : ''} need${pendingChallenges.length === 1 ? 's' : ''} help`;

      // Show interventions in chat (only once per intervention)
      if (window.interventionHandler) {
        for (const intervention of pendingChallenges) {
          if (!displayedInterventions.has(intervention.intervention_id)) {
            displayedInterventions.add(intervention.intervention_id);

            // Map blocker type to label
            const typeLabels = {
              'captcha_recaptcha': 'reCAPTCHA',
              'captcha_hcaptcha': 'hCaptcha',
              'captcha_cloudflare': 'Cloudflare Challenge',
              'captcha_generic': 'CAPTCHA',
              'login_required': 'Login Required',
              'rate_limit': 'Rate Limited',
              'bot_detection': 'Bot Detection',
            };
            const blockerType = intervention.blocker_type || intervention.type || intervention.intervention_type;
            const typeLabel = typeLabels[blockerType] || blockerType || 'Challenge';

            window.interventionHandler.addInterventionToChatWindow(intervention, typeLabel);
          }
        }
      }
    } else {
      banner.style.display = 'none';
    }
  } catch (err) {
    // Silently ignore network errors (common when using tunnel)
    if (!(err instanceof TypeError && err.message.includes('fetch'))) {
      console.error('[Captcha] Check failed:', err);
    }
  }
}

async function solveCaptcha() {
  if (pendingChallenges.length === 0) return;

  const intervention = pendingChallenges[0]; // Solve first pending intervention

  // Open the intervention URL in a new tab for user to solve
  window.open(intervention.url, '_blank');

  // Show instructions
  const typeLabels = {
    'captcha_recaptcha': 'reCAPTCHA',
    'captcha_hcaptcha': 'hCaptcha',
    'captcha_cloudflare': 'Cloudflare Challenge',
    'captcha_generic': 'CAPTCHA',
    'login_required': 'Login Required',
    'rate_limit': 'Rate Limited',
    'bot_detection': 'Bot Detection',
  };

  const blockerType = intervention.blocker_type || intervention.type;
  const typeLabel = typeLabels[blockerType] || blockerType;
  const domain = new URL(intervention.url).hostname.replace('www.', '');

  if (confirm(`Opened ${domain} in new tab.\n\nSolve the ${typeLabel}, then click OK to continue research.`)) {
    // Mark as resolved
    try {
      const gateway_url = window.location.protocol + '//' + window.location.hostname + ':' + window.location.port;
      const resp = await fetch(`${gateway_url}/interventions/${intervention.intervention_id}/resolve`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ resolved: true, cookies: null })
      });

      if (resp.ok) {
        console.log('[Captcha] Intervention resolved:', intervention.intervention_id);
        // Refresh pending challenges
        setTimeout(() => checkPendingCaptchas(), 1000);
      } else {
        console.error('[Captcha] Failed to resolve intervention:', await resp.text());
      }
    } catch (err) {
      console.error('[Captcha] Error resolving intervention:', err);
    }
  }
}

// Set up captcha polling (every 5 seconds for responsiveness)
function initCaptchaPolling() {
  checkPendingCaptchas(); // Check immediately

  if (!captchaPollInterval) {
    captchaPollInterval = setInterval(checkPendingCaptchas, 5000); // Poll every 5 seconds
    console.log('[Captcha] Polling initialized (every 5s)');
  }

  // Attach solve button
  const solveBtn = document.getElementById('solve-captcha-btn');
  if (solveBtn) {
    solveBtn.addEventListener('click', solveCaptcha);
  }
}

// Initialize on page load
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initCaptchaPolling);
} else {
  initCaptchaPolling();
}

console.log('[Captcha] Intervention system loaded');
