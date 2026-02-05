<script lang="ts">
  import { mode } from '$lib/stores/mode';

  const modes = [
    { value: 'chat', label: 'Chat', icon: '💬' },
    { value: 'code', label: 'Code', icon: '💻' }
  ] as const;
</script>

<div class="mode-selector">
  {#each modes as m}
    <label class:active={$mode === m.value}>
      <input type="radio" name="mode" value={m.value} bind:group={$mode} />
      <span class="icon">{m.icon}</span>
      <span class="label">{m.label}</span>
    </label>
  {/each}
</div>

<style>
  .mode-selector {
    display: flex;
    gap: 4px;
    background: #101014;
    padding: 4px;
    border-radius: 8px;
    border: 1px solid #2a2a33;
  }

  label {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    border-radius: 6px;
    cursor: pointer;
    color: #9aa3c2;
    transition: all 0.15s;
  }

  label:hover {
    background: #1a1a22;
  }

  label.active {
    background: #242449;
    color: #ececf1;
  }

  input[type="radio"] {
    display: none;
  }

  .icon {
    font-size: 1em;
  }

  .label {
    font-size: 0.9em;
    font-weight: 500;
  }
</style>
