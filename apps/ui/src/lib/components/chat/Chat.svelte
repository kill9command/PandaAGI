<script lang="ts">
  import { onMount, afterUpdate } from 'svelte';
  import { messages, isLoading, clearMessages } from '$lib/stores/chat';
  import { sendMessage } from '$lib/api/client';
  import UserMessage from './Messages/UserMessage.svelte';
  import ResponseMessage from './Messages/ResponseMessage.svelte';
  import MessageInput from './MessageInput.svelte';
  import ThinkingPanel from '$lib/components/pandora/ThinkingPanel.svelte';

  let chatWindowEl: HTMLElement;

  // Scroll to bottom on mount (page load)
  onMount(() => {
    if (chatWindowEl) {
      chatWindowEl.scrollTop = chatWindowEl.scrollHeight;
    }
  });

  // Scroll to bottom when messages change
  afterUpdate(() => {
    if (chatWindowEl) {
      chatWindowEl.scrollTop = chatWindowEl.scrollHeight;
    }
  });

  function handleSubmit(e: CustomEvent<string>) {
    const history = $messages.map(m => ({
      role: m.role as 'user' | 'assistant',
      content: m.content
    }));
    sendMessage(e.detail, history);
  }

  function handleClear() {
    if (confirm('Start a new conversation? This will clear the current chat.')) {
      clearMessages();
    }
  }
</script>

<div class="chat-container">
  <!-- Thinking panel at top, outside scroll area, always visible when active -->
  <ThinkingPanel />

  <div class="chat-window" bind:this={chatWindowEl}>
    {#if $messages.length === 0}
      <div class="empty-state">
        <p>Start a conversation...</p>
      </div>
    {:else}
      {#each $messages as message (message.id)}
        {#if message.role === 'user'}
          <UserMessage content={message.content} timestamp={message.timestamp} />
        {:else}
          <ResponseMessage
            content={message.content}
            timestamp={message.timestamp}
            isLoading={$isLoading && message === $messages[$messages.length - 1]}
          />
        {/if}
      {/each}
    {/if}
  </div>

  <div class="input-area">
    <MessageInput on:submit={handleSubmit} />
    <div class="actions">
      <button class="clear-btn" on:click={handleClear} title="New conversation">
        🗑️ New
      </button>
    </div>
  </div>
</div>

<style>
  .chat-container {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    background: #17171c;
    border-radius: 12px;
    overflow: hidden;
  }

  .chat-window {
    flex: 1;
    overflow-y: auto;
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .empty-state {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #9aa3c2;
  }

  .input-area {
    border-top: 1px solid #22222a;
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    padding: 0 12px 12px;
    gap: 8px;
  }

  .clear-btn {
    background: transparent;
    border: 1px solid #2a2a33;
    color: #9aa3c2;
    padding: 6px 12px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.85em;
  }

  .clear-btn:hover {
    background: #2a2a33;
    color: #ececf1;
  }
</style>
