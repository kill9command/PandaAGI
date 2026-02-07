<script lang="ts">
  import { modelProvider } from '$lib/stores/mode';
  import { onMount } from 'svelte';

  let claudeAvailable = false;

  onMount(async () => {
    try {
      const resp = await fetch('/v1/model_providers');
      if (resp.ok) {
        const data = await resp.json();
        const claude = data.providers?.find((p: any) => p.id === 'claude');
        claudeAvailable = claude?.available ?? false;
      }
    } catch {
      claudeAvailable = false;
    }
  });

  const providers = [
    { value: 'panda', label: 'Panda' },
    { value: 'claude', label: 'Claude' }
  ] as const;
</script>

{#if claudeAvailable}
  <div class="model-selector">
    {#each providers as p}
      <label class:active={$modelProvider === p.value}>
        <input type="radio" name="provider" value={p.value} bind:group={$modelProvider} />
        <span class="label">{p.label}</span>
      </label>
    {/each}
  </div>
{/if}

<style>
  .model-selector {
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
    font-size: 0.9em;
    font-weight: 500;
  }

  label:hover {
    background: #1a1a22;
  }

  label.active {
    background: #243a49;
    color: #7dd3fc;
  }

  input[type="radio"] {
    display: none;
  }
</style>
