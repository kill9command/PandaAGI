<script lang="ts">
  import FileTree from './FileTree.svelte';
  import Editor from './Editor.svelte';
  import EditorTabs from './EditorTabs.svelte';
  import TaskTracker from './TaskTracker.svelte';
  import Terminal from './Terminal.svelte';
  import MessageInput from '$lib/components/chat/MessageInput.svelte';
  import ThinkingPanel from '$lib/components/pandora/ThinkingPanel.svelte';
  import ResponseMessage from '$lib/components/chat/Messages/ResponseMessage.svelte';
  import { terminalVisible } from '$lib/stores/terminal';
  import { messages, isLoading } from '$lib/stores/chat';
  import { sendMessage } from '$lib/api/client';

  // Get the last assistant message for display
  $: lastAssistantMessage = $messages.filter(m => m.role === 'assistant').slice(-1)[0];

  function handleSubmit(e: CustomEvent<string>) {
    const history = $messages.map(m => ({
      role: m.role as 'user' | 'assistant',
      content: m.content
    }));
    sendMessage(e.detail, history);
  }
</script>

<div class="ide-workspace">
  <!-- Thinking Panel at top -->
  <ThinkingPanel />

  <div class="ide-panels">
    <!-- Left Panel: File Tree -->
    <div class="panel file-tree-panel">
      <div class="panel-header">
        <span class="panel-title">FILES</span>
        <button class="refresh-btn" title="Refresh file tree">↻</button>
      </div>
      <div class="panel-content">
        <FileTree />
      </div>
    </div>

    <!-- Center Panel: Editor -->
    <div class="panel editor-panel">
      <EditorTabs />
      <div class="editor-container">
        <Editor />
      </div>
    </div>

    <!-- Right Panel: Task Tracker + AI Response -->
    <div class="panel task-panel">
      <div class="panel-header">
        <span class="panel-title">TASKS & AI</span>
      </div>
      <div class="panel-content">
        <TaskTracker />

        <!-- Show last AI response -->
        {#if lastAssistantMessage}
          <div class="ai-response-section">
            <div class="response-header">AI Response</div>
            <div class="response-content">
              <ResponseMessage
                content={lastAssistantMessage.content}
                timestamp={lastAssistantMessage.timestamp}
                isLoading={$isLoading && lastAssistantMessage === $messages[$messages.length - 1]}
              />
            </div>
          </div>
        {/if}
      </div>
    </div>
  </div>

  <!-- Chat Input Bar -->
  <div class="chat-input-bar">
    <MessageInput on:submit={handleSubmit} placeholder="Ask the AI to help with code..." />
  </div>

  <!-- Bottom Panel: Terminal (collapsible) -->
  {#if $terminalVisible}
    <div class="terminal-panel">
      <Terminal />
    </div>
  {/if}
</div>

<style>
  .ide-workspace {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: #0d0d11;
    overflow: hidden;
  }

  .ide-panels {
    display: flex;
    flex: 1;
    min-height: 0;
    gap: 1px;
    background: #2a2a33;
  }

  .panel {
    display: flex;
    flex-direction: column;
    background: #101014;
    overflow: hidden;
  }

  .file-tree-panel {
    width: 20%;
    min-width: 180px;
    max-width: 350px;
    border-right: 1px solid #2a2a33;
  }

  .editor-panel {
    flex: 1;
    min-width: 300px;
  }

  .task-panel {
    width: 30%;
    min-width: 250px;
    max-width: 450px;
    border-left: 1px solid #2a2a33;
  }

  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    background: #1a1a22;
    border-bottom: 1px solid #2a2a33;
    flex-shrink: 0;
  }

  .panel-title {
    font-size: 0.8em;
    font-weight: 600;
    color: #9aa3c2;
    letter-spacing: 0.05em;
  }

  .panel-content {
    flex: 1;
    overflow: auto;
  }

  .refresh-btn {
    background: transparent;
    border: none;
    color: #68a8ef;
    cursor: pointer;
    font-size: 1.1em;
    padding: 2px 6px;
    border-radius: 4px;
    transition: background 0.2s;
  }

  .refresh-btn:hover {
    background: #2a2a33;
  }

  .editor-container {
    flex: 1;
    min-height: 0;
    background: #1e1e1e;
  }

  .chat-input-bar {
    flex-shrink: 0;
    border-top: 1px solid #2a2a33;
    background: #101014;
  }

  .ai-response-section {
    margin-top: 16px;
    border-top: 1px solid #2a2a33;
    padding-top: 12px;
  }

  .response-header {
    font-size: 0.8em;
    font-weight: 600;
    color: #9aa3c2;
    letter-spacing: 0.05em;
    margin-bottom: 8px;
    text-transform: uppercase;
  }

  .response-content {
    max-height: 300px;
    overflow-y: auto;
  }

  .terminal-panel {
    height: 200px;
    border-top: 2px solid #2a2a33;
    flex-shrink: 0;
  }

  /* Responsive adjustments */
  @media (max-width: 1200px) {
    .file-tree-panel {
      width: 25%;
    }
    .task-panel {
      width: 35%;
    }
  }

  @media (max-width: 900px) {
    .ide-panels {
      flex-direction: column;
    }

    .file-tree-panel,
    .task-panel {
      width: 100%;
      max-width: none;
      height: 200px;
      border: none;
      border-bottom: 1px solid #2a2a33;
    }

    .editor-panel {
      flex: 1;
    }
  }
</style>
