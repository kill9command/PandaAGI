<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { selectedFile, fileContent, fileLoading, fileError } from '$lib/stores/editor';

  let editorContainer: HTMLDivElement;
  let monaco: any = null;
  let editor: any = null;

  // Language detection from file extension
  function getLanguage(filePath: string): string {
    const ext = filePath.split('.').pop()?.toLowerCase();
    const languageMap: Record<string, string> = {
      ts: 'typescript',
      tsx: 'typescript',
      js: 'javascript',
      jsx: 'javascript',
      py: 'python',
      svelte: 'html',
      html: 'html',
      css: 'css',
      scss: 'scss',
      json: 'json',
      md: 'markdown',
      yml: 'yaml',
      yaml: 'yaml',
      sh: 'shell',
      bash: 'shell',
      sql: 'sql',
      go: 'go',
      rs: 'rust',
      c: 'c',
      cpp: 'cpp',
      h: 'c',
      hpp: 'cpp',
    };
    return languageMap[ext || ''] || 'plaintext';
  }

  async function initMonaco() {
    // Dynamic import of Monaco loader
    const monacoLoader = await import('@monaco-editor/loader');
    monaco = await monacoLoader.default.init();

    editor = monaco.editor.create(editorContainer, {
      value: '// Select a file from the tree to view its contents',
      language: 'javascript',
      theme: 'vs-dark',
      automaticLayout: true,
      fontSize: 14,
      minimap: { enabled: true },
      scrollBeyondLastLine: false,
      readOnly: false,
      lineNumbers: 'on',
      renderWhitespace: 'selection',
      tabSize: 2,
      wordWrap: 'on',
    });
  }

  // Update editor when file content changes
  $: if (editor && $fileContent !== null) {
    const language = $selectedFile ? getLanguage($selectedFile) : 'plaintext';
    const model = editor.getModel();

    if (model) {
      monaco.editor.setModelLanguage(model, language);
      editor.setValue($fileContent);
    }
  }

  onMount(() => {
    initMonaco().catch((err) => {
      console.error('Failed to initialize Monaco:', err);
    });
  });

  onDestroy(() => {
    if (editor) {
      editor.dispose();
    }
  });
</script>

<div class="editor-wrapper">
  {#if $fileLoading}
    <div class="editor-overlay">
      <div class="loading-indicator">Loading file...</div>
    </div>
  {/if}

  {#if $fileError}
    <div class="editor-overlay error">
      <div class="error-message">{$fileError}</div>
    </div>
  {/if}

  <div class="monaco-container" bind:this={editorContainer}></div>
</div>

<style>
  .editor-wrapper {
    position: relative;
    width: 100%;
    height: 100%;
  }

  .monaco-container {
    width: 100%;
    height: 100%;
  }

  .editor-overlay {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(13, 13, 17, 0.8);
    z-index: 10;
  }

  .loading-indicator {
    color: #68a8ef;
    font-size: 0.9em;
  }

  .editor-overlay.error {
    background: rgba(30, 20, 20, 0.9);
  }

  .error-message {
    color: #ff6b6b;
    font-size: 0.9em;
    padding: 16px;
    text-align: center;
  }
</style>
