<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { isLoading, currentTraceId } from '$lib/stores/chat';
  import { cancelRequest } from '$lib/api/client';

  export let placeholder = 'Type your message...';

  const dispatch = createEventDispatcher();

  let value = '';
  let textareaEl: HTMLTextAreaElement;

  function handleSubmit() {
    if (!value.trim() || $isLoading) return;
    dispatch('submit', value.trim());
    value = '';
    if (textareaEl) textareaEl.style.height = 'auto';
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }

  function handleInput() {
    if (textareaEl) {
      textareaEl.style.height = 'auto';
      textareaEl.style.height = Math.min(textareaEl.scrollHeight, 200) + 'px';
    }
  }

  async function handleCancel() {
    if ($currentTraceId) {
      await cancelRequest($currentTraceId);
    }
  }
</script>

<div class="input-container">
  <textarea
    bind:this={textareaEl}
    bind:value
    {placeholder}
    on:keydown={handleKeydown}
    on:input={handleInput}
    rows="1"
    disabled={$isLoading}
  ></textarea>

  <div class="buttons">
    {#if $isLoading}
      <button class="cancel-btn" on:click={handleCancel}>Cancel</button>
    {:else}
      <button class="send-btn" on:click={handleSubmit} disabled={!value.trim()}>
        Send
      </button>
    {/if}
  </div>
</div>

<style>
  .input-container {
    display: flex;
    gap: 10px;
    padding: 12px;
    background: #181820;
    border-top: 1px solid #22222a;
  }

  textarea {
    flex: 1;
    resize: none;
    border: none;
    padding: 12px;
    border-radius: 8px;
    font-size: 1em;
    font-family: inherit;
    background: #101014;
    color: #ececf1;
    outline: none;
    min-height: 44px;
    max-height: 200px;
  }

  textarea:focus {
    box-shadow: 0 0 0 2px rgba(68, 95, 230, 0.3);
  }

  textarea:disabled {
    opacity: 0.7;
    cursor: not-allowed;
  }

  .buttons {
    display: flex;
    gap: 8px;
    align-items: flex-end;
  }

  .send-btn {
    background: linear-gradient(90deg, #31318e 60%, #4263eb 100%);
    color: #fff;
    border: none;
    border-radius: 8px;
    padding: 10px 20px;
    font-size: 1em;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.2s;
  }

  .send-btn:hover:not(:disabled) {
    background: linear-gradient(90deg, #21214c 60%, #364fc7 100%);
  }

  .send-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .cancel-btn {
    background: #dc3545;
    color: #fff;
    border: none;
    border-radius: 8px;
    padding: 10px 20px;
    font-size: 1em;
    font-weight: 600;
    cursor: pointer;
  }

  .cancel-btn:hover {
    background: #c82333;
  }
</style>
