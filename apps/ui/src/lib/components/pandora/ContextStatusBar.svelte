<script lang="ts">
  import { mode, repoRoot } from '$lib/stores/mode';

  $: modePermissions = $mode === 'chat' ? '(read-only)' : '(read/write)';
  $: permColor = $mode === 'code' ? '#ff6b6b' : '#7fd288';
</script>

<div class="status-bar">
  <div class="item">
    <span class="label">Repo:</span>
    <span class="value mono" title={$repoRoot || 'Not set'}>
      {$repoRoot || '<not set>'}
    </span>
  </div>

  <div class="item">
    <span class="label">Mode:</span>
    <span class="value">{$mode}</span>
    <span class="perms" style="color: {permColor}">{modePermissions}</span>
  </div>
</div>

<style>
  .status-bar {
    background: #1a1a22;
    border-bottom: 1px solid #2a2a33;
    padding: 8px 16px;
    display: flex;
    gap: 24px;
    flex-wrap: wrap;
    font-size: 0.85em;
  }

  .item {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .label {
    color: #9aa3c2;
  }

  .value {
    color: #7fd288;
  }

  .mono {
    font-family: monospace;
    max-width: 300px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .perms {
    font-size: 0.9em;
  }
</style>
