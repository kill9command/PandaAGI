<script lang="ts">
  import { actions } from '$lib/stores/actions';
  import Spinner from '$lib/components/common/Spinner.svelte';

  // Filter to source-related action types
  const sourceTypes = new Set(['memory', 'search', 'fetch', 'fetch_retry', 'tool', 'error', 'decision', 'route']);

  $: sourceActions = $actions.actions.filter(a => sourceTypes.has(a.type));
  $: hasSourceActions = sourceActions.length > 0;

  // Type badge colors
  const typeColors: Record<string, string> = {
    memory: '#c792ea',
    search: '#68a8ef',
    fetch: '#6befa8',
    fetch_retry: '#ffa500',
    tool: '#ef9b6b',
    error: '#ef6b6b',
    decision: '#a8ef6b',
    route: '#9b6bef',
  };
</script>

{#if hasSourceActions}
  <div class="sources-panel">
    <div class="sources-header">
      <span class="sources-title">SOURCES</span>
      <span class="sources-count">{sourceActions.length}</span>
    </div>
    <div class="source-list">
      {#each sourceActions as action (action.id)}
        <div
          class="source-item"
          class:success={action.success === true}
          class:error={action.success === false}
          class:pending={action.success === undefined || action.success === null}
        >
          <span class="source-icon">{action.icon}</span>
          <span
            class="type-badge"
            style="--type-color: {typeColors[action.type] || '#9aa3c2'}"
          >
            {action.type}
          </span>
          <span class="source-label">{action.label}</span>
          {#if action.detail}
            <span class="source-detail">{action.detail}</span>
          {/if}
          <span class="source-status">
            {#if action.success === true}
              <span class="status-icon success-icon">&#10003;</span>
            {:else if action.success === false}
              <span class="status-icon error-icon">&#10007;</span>
            {:else}
              <Spinner size={10} />
            {/if}
          </span>
        </div>
      {/each}
    </div>
  </div>
{/if}

<style>
  .sources-panel {
    margin: 12px;
    margin-top: 4px;
    background: #12121a;
    border: 1px solid #2a2a33;
    border-radius: 6px;
    overflow: hidden;
  }

  .sources-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background: #1a1a22;
    border-bottom: 1px solid #2a2a33;
  }

  .sources-title {
    font-size: 0.75em;
    font-weight: 600;
    color: #9aa3c2;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .sources-count {
    font-size: 0.65em;
    color: #6b7280;
    background: #2a2a33;
    padding: 2px 6px;
    border-radius: 8px;
  }

  .source-list {
    padding: 6px;
    display: flex;
    flex-direction: column;
    gap: 3px;
    max-height: 180px;
    overflow-y: auto;
  }

  .source-item {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 5px 8px;
    background: #0a0a0e;
    border-radius: 4px;
    border-left: 2px solid #3a3a44;
    transition: border-color 0.2s;
    min-height: 28px;
  }

  .source-item.success {
    border-left-color: #7fd288;
  }

  .source-item.error {
    border-left-color: #ef6b6b;
    background: #1a0a0a;
  }

  .source-item.pending {
    border-left-color: #68a8ef;
  }

  .source-icon {
    font-size: 0.8em;
    flex-shrink: 0;
  }

  .type-badge {
    font-size: 0.6em;
    padding: 1px 5px;
    background: color-mix(in srgb, var(--type-color) 20%, transparent);
    color: var(--type-color);
    border-radius: 3px;
    text-transform: uppercase;
    font-weight: 600;
    letter-spacing: 0.03em;
    flex-shrink: 0;
    white-space: nowrap;
  }

  .source-label {
    font-size: 0.72em;
    color: #ececf1;
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .source-detail {
    font-size: 0.62em;
    color: #6b7280;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 120px;
    flex-shrink: 0;
  }

  .source-status {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    width: 16px;
    justify-content: center;
  }

  .status-icon {
    font-size: 0.75em;
    font-weight: bold;
  }

  .success-icon {
    color: #7fd288;
  }

  .error-icon {
    color: #ef6b6b;
  }
</style>
