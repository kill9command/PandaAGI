<script lang="ts">
  import { terminalLines, terminalVisible, clearTerminal, toggleTerminal } from '$lib/stores/terminal';
  import { onMount, afterUpdate } from 'svelte';

  let terminalContent: HTMLDivElement;

  const typeColors: Record<string, string> = {
    stdout: '#cfd3e9',
    stderr: '#ff6b6b',
    info: '#68a8ef',
  };

  // Auto-scroll to bottom on new output
  afterUpdate(() => {
    if (terminalContent) {
      terminalContent.scrollTop = terminalContent.scrollHeight;
    }
  });
</script>

<div class="terminal">
  <div class="terminal-header">
    <span class="terminal-title">TERMINAL</span>
    <div class="terminal-actions">
      <button class="action-btn" on:click={clearTerminal} title="Clear terminal">
        Clear
      </button>
      <button class="action-btn" on:click={toggleTerminal} title="Hide terminal">
        −
      </button>
    </div>
  </div>

  <div class="terminal-content" bind:this={terminalContent}>
    {#if $terminalLines.length === 0}
      <div class="terminal-empty">Terminal output will appear here...</div>
    {:else}
      {#each $terminalLines as line (line.timestamp)}
        <div class="terminal-line" style="color: {typeColors[line.type] || typeColors.stdout}">
          {line.text}
        </div>
      {/each}
    {/if}
  </div>
</div>

<style>
  .terminal {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: #0d0d11;
  }

  .terminal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 12px;
    background: #1a1a22;
    border-bottom: 1px solid #2a2a33;
    flex-shrink: 0;
  }

  .terminal-title {
    font-size: 0.8em;
    font-weight: 600;
    color: #9aa3c2;
    letter-spacing: 0.05em;
  }

  .terminal-actions {
    display: flex;
    gap: 8px;
  }

  .action-btn {
    background: transparent;
    border: none;
    color: #68a8ef;
    cursor: pointer;
    font-size: 0.85em;
    padding: 2px 8px;
    border-radius: 4px;
    transition: background 0.15s;
  }

  .action-btn:hover {
    background: #2a2a33;
  }

  .terminal-content {
    flex: 1;
    overflow-y: auto;
    padding: 8px 12px;
    font-family: 'Fira Mono', 'Consolas', 'Monaco', monospace;
    font-size: 0.85em;
    line-height: 1.5;
  }

  .terminal-empty {
    color: #666;
    font-style: italic;
  }

  .terminal-line {
    white-space: pre-wrap;
    word-break: break-all;
  }
</style>
