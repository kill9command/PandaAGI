<script lang="ts">
  import { interventions, resolveIntervention } from '$lib/stores/research';
  import Modal from '$lib/components/common/Modal.svelte';

  $: current = $interventions[0];

  const typeLabels: Record<string, string> = {
    'captcha_recaptcha': 'reCAPTCHA',
    'captcha_hcaptcha': 'hCaptcha',
    'captcha_cloudflare': 'Cloudflare Challenge',
    'captcha_generic': 'CAPTCHA',
    'login_required': 'Login Required',
    'rate_limit': 'Rate Limited',
    'bot_detection': 'Bot Detection',
    'extraction_failed': 'Extraction Failed',
  };

  function getTypeLabel(type: string): string {
    return typeLabels[type] || type;
  }

  function getDomain(url: string): string {
    try {
      return new URL(url).hostname.replace('www.', '');
    } catch {
      return url;
    }
  }

  function handleSolved() {
    if (current) resolveIntervention(current.id, true);
  }

  function handleSkip() {
    if (current) resolveIntervention(current.id, false);
  }

  function openBrowser() {
    if (current?.cdpUrl) {
      window.open(current.cdpUrl, '_blank', 'width=1400,height=900');
    } else if (current?.url) {
      window.open(current.url, '_blank');
    }
  }
</script>

{#if current}
  <Modal title="Human Assistance Required" on:close={handleSkip}>
    <div class="intervention">
      <div class="header">
        <span class="badge">{getTypeLabel(current.type)}</span>
        <span class="domain">{getDomain(current.url)}</span>
      </div>

      <p class="message">
        {#if current.cdpUrl}
          Click "Open Browser" to view the live browser session and solve the challenge.
        {:else}
          Open the page and solve the challenge, then click "I've Solved It".
        {/if}
      </p>

      <div class="url-display">
        <code>{current.url}</code>
      </div>

      {#if current.screenshotUrl}
        <div class="screenshot">
          <img src={current.screenshotUrl} alt="Page screenshot" on:click={() => window.open(current.screenshotUrl, '_blank')} />
        </div>
      {/if}

      <div class="actions">
        <button class="primary" on:click={openBrowser}>
          🖥️ Open Browser
        </button>
        <button class="success" on:click={handleSolved}>
          ✓ I've Solved It
        </button>
        <button class="secondary" on:click={handleSkip}>
          Skip
        </button>
      </div>
    </div>
  </Modal>
{/if}

<style>
  .intervention {
    min-width: 400px;
    max-width: 600px;
  }

  .header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
  }

  .badge {
    background: #ff6b6b;
    color: #fff;
    padding: 4px 12px;
    border-radius: 4px;
    font-size: 0.85em;
    font-weight: 500;
  }

  .domain {
    color: #ececf1;
    font-weight: 500;
  }

  .message {
    color: #9aa3c2;
    margin: 0 0 16px;
    line-height: 1.5;
  }

  .url-display {
    background: #101014;
    border: 1px solid #2a2a33;
    border-radius: 6px;
    padding: 10px;
    margin-bottom: 16px;
    overflow-x: auto;
  }

  .url-display code {
    font-family: monospace;
    font-size: 0.85em;
    color: #9aa3c2;
    word-break: break-all;
  }

  .screenshot {
    margin-bottom: 16px;
  }

  .screenshot img {
    max-width: 100%;
    border: 1px solid #2a2a33;
    border-radius: 6px;
    cursor: pointer;
  }

  .screenshot img:hover {
    border-color: #445fe6;
  }

  .actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }

  button {
    padding: 10px 20px;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.95em;
    font-weight: 500;
    transition: opacity 0.15s;
  }

  button:hover {
    opacity: 0.9;
  }

  .primary {
    background: #ff6b6b;
    color: #fff;
  }

  .success {
    background: #7fd288;
    color: #000;
  }

  .secondary {
    background: #3a3a43;
    color: #ececf1;
  }
</style>
