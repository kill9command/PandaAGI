<script lang="ts">
  import Markdown from './Markdown.svelte';
  import Spinner from '$lib/components/common/Spinner.svelte';

  export let content: string;
  export let timestamp: number;
  export let isLoading = false;

  let copied = false;

  $: timeStr = new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  async function copyContent() {
    try {
      await navigator.clipboard.writeText(content);
      copied = true;
      setTimeout(() => copied = false, 2000);
    } catch {}
  }
</script>

<div class="response-message">
  {#if isLoading && !content}
    <div class="loading">
      <Spinner size={14} />
      <span>Thinking...</span>
    </div>
  {:else}
    <div class="content">
      <Markdown {content} />
    </div>
    <div class="footer">
      <span class="time">{timeStr}</span>
      <button class="copy-btn" on:click={copyContent}>
        {copied ? '✓' : '📋'}
      </button>
    </div>
  {/if}
</div>

<style>
  .response-message {
    align-self: flex-start;
    max-width: 90%;
    background: #202025;
    color: #ececf1;
    padding: 12px 16px;
    border-radius: 16px 16px 16px 4px;
    border-left: 3px solid #445fe6;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
  }

  .loading {
    display: flex;
    align-items: center;
    gap: 8px;
    color: #9aa3c2;
    font-style: italic;
  }

  .content {
    line-height: 1.6;
  }

  .footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid #2a2a33;
  }

  .time {
    font-size: 0.75em;
    color: #9aa3c2;
  }

  .copy-btn {
    background: transparent;
    border: none;
    color: #9aa3c2;
    cursor: pointer;
    padding: 2px 6px;
    font-size: 0.9em;
  }

  .copy-btn:hover {
    color: #ececf1;
  }
</style>
