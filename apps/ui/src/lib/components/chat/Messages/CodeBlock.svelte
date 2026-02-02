<script lang="ts">
  import { onMount } from 'svelte';
  import hljs from 'highlight.js';

  export let code: string;
  export let language = '';

  let codeEl: HTMLElement;
  let copied = false;

  onMount(() => {
    if (codeEl && language) {
      hljs.highlightElement(codeEl);
    }
  });

  async function copyCode() {
    try {
      await navigator.clipboard.writeText(code);
      copied = true;
      setTimeout(() => copied = false, 2000);
    } catch {}
  }
</script>

<div class="code-block">
  <div class="code-header">
    <span class="language">{language || 'code'}</span>
    <button class="copy-btn" on:click={copyCode}>
      {copied ? '✓ Copied' : 'Copy'}
    </button>
  </div>
  <pre><code bind:this={codeEl} class="language-{language}">{code}</code></pre>
</div>

<style>
  .code-block {
    margin: 8px 0;
    border-radius: 8px;
    overflow: hidden;
    background: #1e1e1e;
    border: 1px solid #2a2a33;
  }

  .code-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 6px 12px;
    background: #2a2a33;
    font-size: 0.8em;
  }

  .language {
    color: #9aa3c2;
    text-transform: lowercase;
  }

  .copy-btn {
    background: transparent;
    border: 1px solid #3a3a43;
    color: #9aa3c2;
    padding: 2px 8px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.85em;
  }

  .copy-btn:hover {
    background: #3a3a43;
    color: #ececf1;
  }

  pre {
    margin: 0;
    padding: 12px;
    overflow-x: auto;
  }

  code {
    font-family: 'Fira Mono', 'Consolas', monospace;
    font-size: 0.9em;
    line-height: 1.5;
  }
</style>
