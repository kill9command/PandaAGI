<script lang="ts">
  import { tasks } from '$lib/stores/tasks';
  import { openFile } from '$lib/stores/editor';

  $: completedCount = $tasks.filter(t => t.status === 'completed').length;
  $: totalCount = $tasks.length;
  $: progressPercent = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

  const statusIcons: Record<string, string> = {
    pending: '☐',
    in_progress: '⏳',
    completed: '☑',
  };

  const statusColors: Record<string, string> = {
    pending: '#9aa3c2',
    in_progress: '#68a8ef',
    completed: '#7fd288',
  };

  function handleFileClick(filePath: string) {
    // Parse file:line format
    const match = filePath.match(/^(.+?):(\d+)$/);
    if (match) {
      const [, path, line] = match;
      openFile(path, parseInt(line, 10));
    } else {
      openFile(filePath);
    }
  }

  function formatDuration(ms: number | undefined): string {
    if (!ms) return '';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }
</script>

<div class="task-tracker">
  {#if $tasks.length === 0}
    <div class="empty">
      <div class="empty-icon">📋</div>
      <div class="empty-text">No active tasks</div>
      <div class="empty-hint">Tasks will appear here during code operations</div>
    </div>
  {:else}
    <!-- Progress bar -->
    <div class="progress-section">
      <div class="progress-bar">
        <div
          class="progress-fill"
          style="width: {progressPercent}%"
        ></div>
      </div>
      <div class="progress-label">
        {completedCount}/{totalCount} tasks completed ({progressPercent}%)
      </div>
    </div>

    <!-- Task list -->
    <div class="task-list">
      {#each $tasks as task (task.id)}
        <div
          class="task-card"
          style="border-left-color: {statusColors[task.status] || statusColors.pending}"
        >
          <div class="task-header">
            <span class="task-status" style="color: {statusColors[task.status]}">
              {statusIcons[task.status] || '○'}
            </span>
            <span class="task-description">{task.description}</span>
            {#if task.duration_ms}
              <span class="task-duration">{formatDuration(task.duration_ms)}</span>
            {/if}
          </div>

          {#if task.tool}
            <div class="task-tool">Tool: {task.tool}</div>
          {/if}

          {#if task.files && task.files.length > 0}
            <div class="task-files">
              {#each task.files as file}
                <button class="file-link" on:click={() => handleFileClick(file)}>
                  📄 {file}
                </button>
              {/each}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .task-tracker {
    padding: 12px;
    height: 100%;
    overflow-y: auto;
  }

  .empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    min-height: 200px;
    color: #9aa3c2;
    text-align: center;
  }

  .empty-icon {
    font-size: 2em;
    margin-bottom: 8px;
    opacity: 0.5;
  }

  .empty-text {
    font-size: 0.9em;
    margin-bottom: 4px;
  }

  .empty-hint {
    font-size: 0.8em;
    opacity: 0.6;
  }

  .progress-section {
    margin-bottom: 16px;
  }

  .progress-bar {
    height: 8px;
    background: #2a2a33;
    border-radius: 4px;
    overflow: hidden;
    position: relative;
  }

  .progress-fill {
    position: absolute;
    top: 0;
    left: 0;
    height: 100%;
    background: #7fd288;
    transition: width 0.3s ease;
  }

  .progress-label {
    font-size: 0.75em;
    color: #9aa3c2;
    margin-top: 6px;
  }

  .task-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .task-card {
    padding: 10px 12px;
    background: #1a1a22;
    border-left: 3px solid #9aa3c2;
    border-radius: 4px;
  }

  .task-header {
    display: flex;
    align-items: flex-start;
    gap: 8px;
  }

  .task-status {
    font-size: 1em;
    flex-shrink: 0;
  }

  .task-description {
    flex: 1;
    font-size: 0.85em;
    color: #cfd3e9;
    line-height: 1.4;
  }

  .task-duration {
    font-size: 0.75em;
    color: #9aa3c2;
    flex-shrink: 0;
  }

  .task-tool {
    font-size: 0.75em;
    color: #68a8ef;
    margin-top: 6px;
    padding-left: 24px;
  }

  .task-files {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-top: 8px;
    padding-left: 24px;
  }

  .file-link {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    background: #252530;
    border: none;
    border-radius: 4px;
    color: #68a8ef;
    cursor: pointer;
    font-size: 0.8em;
    text-align: left;
    transition: background 0.15s;
  }

  .file-link:hover {
    background: #2a2a40;
    text-decoration: underline;
  }
</style>
