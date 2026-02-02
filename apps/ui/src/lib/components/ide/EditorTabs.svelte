<script lang="ts">
  import { openTabs, selectedFile, openFile, closeTab } from '$lib/stores/editor';

  function getFileName(path: string): string {
    return path.split('/').pop() || path;
  }

  function handleTabClick(path: string) {
    openFile(path);
  }

  function handleCloseTab(event: MouseEvent, path: string) {
    event.stopPropagation();
    closeTab(path);
  }
</script>

<div class="tabs-bar">
  {#if $openTabs.length === 0}
    <div class="no-tabs">No files open</div>
  {:else}
    {#each $openTabs as tabPath (tabPath)}
      <button
        class="tab"
        class:active={$selectedFile === tabPath}
        on:click={() => handleTabClick(tabPath)}
        title={tabPath}
      >
        <span class="tab-name">{getFileName(tabPath)}</span>
        <button
          class="tab-close"
          on:click={(e) => handleCloseTab(e, tabPath)}
          title="Close tab"
        >
          ×
        </button>
      </button>
    {/each}
  {/if}
</div>

<style>
  .tabs-bar {
    display: flex;
    gap: 2px;
    padding: 4px;
    background: #0d0d11;
    border-bottom: 1px solid #2a2a33;
    overflow-x: auto;
    flex-shrink: 0;
    min-height: 36px;
    align-items: center;
  }

  .no-tabs {
    color: #666;
    font-size: 0.8em;
    padding: 0 8px;
  }

  .tab {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    background: #1a1a22;
    border: none;
    border-radius: 4px 4px 0 0;
    color: #9aa3c2;
    cursor: pointer;
    font-size: 0.85em;
    max-width: 180px;
    transition: background 0.15s, color 0.15s;
  }

  .tab:hover {
    background: #252530;
    color: #cfd3e9;
  }

  .tab.active {
    background: #1e1e1e;
    color: #fff;
    border-bottom: 2px solid #68a8ef;
  }

  .tab-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .tab-close {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    padding: 0;
    background: transparent;
    border: none;
    border-radius: 3px;
    color: #666;
    cursor: pointer;
    font-size: 1.1em;
    line-height: 1;
    transition: background 0.15s, color 0.15s;
  }

  .tab-close:hover {
    background: #ff6b6b33;
    color: #ff6b6b;
  }
</style>
