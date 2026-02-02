<script lang="ts">
  import { createEventDispatcher } from 'svelte';

  export let title = '';
  export let show = true;

  const dispatch = createEventDispatcher();

  function handleClose() {
    dispatch('close');
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') handleClose();
  }

  function handleBackdropClick(e: MouseEvent) {
    if (e.target === e.currentTarget) handleClose();
  }
</script>

<svelte:window on:keydown={handleKeydown} />

{#if show}
  <div class="modal-backdrop" on:click={handleBackdropClick} role="dialog" aria-modal="true">
    <div class="modal-content">
      {#if title}
        <header class="modal-header">
          <h3>{title}</h3>
          <button class="close-btn" on:click={handleClose} aria-label="Close">&times;</button>
        </header>
      {/if}
      <div class="modal-body">
        <slot />
      </div>
    </div>
  </div>
{/if}

<style>
  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.7);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
  }

  .modal-content {
    background: #1a1a22;
    border: 1px solid #2a2a33;
    border-radius: 12px;
    max-width: 90vw;
    max-height: 90vh;
    overflow: auto;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
  }

  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid #2a2a33;
  }

  .modal-header h3 {
    margin: 0;
    color: #ececf1;
    font-size: 1.1em;
  }

  .close-btn {
    background: none;
    border: none;
    color: #9aa3c2;
    font-size: 1.5em;
    cursor: pointer;
    padding: 0;
    line-height: 1;
  }

  .close-btn:hover {
    color: #ececf1;
  }

  .modal-body {
    padding: 20px;
  }
</style>
