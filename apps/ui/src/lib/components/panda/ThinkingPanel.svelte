<script lang="ts">
  import { thinking } from '$lib/stores/thinking';
  import { actions } from '$lib/stores/actions';
  import Spinner from '$lib/components/common/Spinner.svelte';

  // Phase definitions matching the backend stage names from unified_flow.py
  // Backend emits: phase_0_query_analyzer, phase_1_context_gatherer, etc.
  const phaseDefinitions = [
    { key: 'phase_0_query_analyzer', label: 'Analyze', icon: '🔍', color: '#68a8ef' },
    { key: 'phase_1_context_gatherer', label: 'Gather', icon: '📚', color: '#ffa500' },
    { key: 'phase_2_reflection', label: 'Reflect', icon: '🤔', color: '#c792ea' },
    { key: 'phase_3_planner', label: 'Plan', icon: '📋', color: '#ef9b6b' },
    { key: 'phase_4_executor', label: 'Execute', icon: '⚡', color: '#ef6b9b' },
    { key: 'phase_5_coordinator', label: 'Coordinate', icon: '🔧', color: '#6befa8' },
    { key: 'phase_6_synthesis', label: 'Synthesize', icon: '✍️', color: '#a8ef6b' },
    { key: 'phase_7_validation', label: 'Validate', icon: '✓', color: '#6b9bef' }
  ];

  let expanded = false;
  let expandedPhase: string | null = null;
  let activeTabs: Record<string, 'input' | 'output'> = {};

  // REACTIVE: Merge phase definitions with live store data
  $: phases = phaseDefinitions.map(def => {
    const data = $thinking.phases[def.key];
    return {
      ...def,
      status: data?.status || 'pending',
      content: data?.content || '',
      reasoning: data?.reasoning || '',
      input: data?.input || '',
      output: data?.output || '',
      hasData: !!(data?.input || data?.output || data?.content)
    };
  });

  // Count completed phases
  $: completedCount = phases.filter(p => p.status === 'completed').length;

  // Get current active phase name for header display
  $: activePhase = phases.find(p => p.status === 'active');

  function toggleExpanded() {
    expanded = !expanded;
  }

  function togglePhaseContent(key: string) {
    if (expandedPhase === key) {
      expandedPhase = null;
    } else {
      expandedPhase = key;
      // Default to output tab if not set
      if (!activeTabs[key]) {
        activeTabs[key] = 'output';
      }
    }
  }

  function setActiveTab(key: string, tab: 'input' | 'output') {
    activeTabs[key] = tab;
    activeTabs = activeTabs; // Trigger reactivity
  }

  // Check if we should show the panel
  $: showPanel = $thinking.active || $thinking.completed;

  // Check if we have journey actions
  $: hasActions = $actions.actions.length > 0;
</script>

{#if showPanel}
  <div class="thinking-panel" class:completed={$thinking.completed && !$thinking.active}>
    <header on:click={toggleExpanded}>
      <div class="left">
        {#if $thinking.active}
          <Spinner size={12} />
          <strong>THINKING</strong>
          <span class="status">{activePhase ? activePhase.label : 'Starting...'}</span>
        {:else}
          <span class="check-icon">&#10003;</span>
          <strong>COMPLETED</strong>
          <span class="phase-count">{completedCount}/{phaseDefinitions.length} phases</span>
        {/if}
      </div>
      <button class="toggle" title={expanded ? 'Collapse' : 'Expand to see phase details'}>
        {expanded ? '▲' : '▼'}
      </button>
    </header>

    {#if expanded}
      <div class="phases">
        {#each phases as phase (phase.key)}
          <div
            class="phase"
            class:active={phase.status === 'active'}
            class:completed={phase.status === 'completed'}
            class:has-content={phase.hasData}
            style="--phase-color: {phase.color}"
          >
            <button
              class="phase-header"
              on:click={() => phase.hasData && togglePhaseContent(phase.key)}
              disabled={!phase.hasData}
            >
              <span class="icon">{phase.icon}</span>
              <span class="label">{phase.label}</span>
              <span class="badge"
                class:active={phase.status === 'active'}
                class:completed={phase.status === 'completed'}>
                {phase.status}
              </span>
              {#if phase.hasData}
                <span class="expand-icon">{expandedPhase === phase.key ? '▼' : '▶'}</span>
              {/if}
            </button>

            {#if expandedPhase === phase.key && phase.hasData}
              <div class="phase-content">
                <!-- Tab buttons -->
                <div class="tabs">
                  <button
                    class="tab"
                    class:active={activeTabs[phase.key] === 'input'}
                    on:click|stopPropagation={() => setActiveTab(phase.key, 'input')}
                    disabled={!phase.input}
                  >
                    <span class="tab-icon">→</span> INPUT
                    <span class="tab-hint">What I received</span>
                  </button>
                  <button
                    class="tab"
                    class:active={activeTabs[phase.key] === 'output'}
                    on:click|stopPropagation={() => setActiveTab(phase.key, 'output')}
                    disabled={!phase.output && !phase.content}
                  >
                    <span class="tab-icon">←</span> OUTPUT
                    <span class="tab-hint">What I produced</span>
                  </button>
                </div>

                <!-- Content area -->
                <div class="content-area">
                  {#if activeTabs[phase.key] === 'input'}
                    {#if phase.input}
                      <pre>{phase.input}</pre>
                    {:else}
                      <div class="no-content">No input data captured</div>
                    {/if}
                  {:else}
                    {#if phase.output}
                      <pre>{phase.output}</pre>
                    {:else if phase.content}
                      <pre>{phase.content}</pre>
                    {:else}
                      <div class="no-content">No output data captured</div>
                    {/if}
                  {/if}
                </div>
              </div>
            {/if}
          </div>
        {/each}
      </div>

      <!-- Journey section (actions log) - only shown when panel is expanded -->
      {#if hasActions}
        <div class="journey-section">
          <div class="journey-header">
            <span class="journey-title">🛤️ Journey</span>
            <span class="journey-count">{$actions.actions.length} steps</span>
          </div>
          <div class="journey-actions">
            {#each $actions.actions as action (action.id)}
              <div class="journey-action" class:error={action.type === 'error'} class:success={action.success === true}>
                <span class="action-icon">{action.icon}</span>
                <div class="action-content">
                  <span class="action-label">{action.label}</span>
                  {#if action.detail}
                    <span class="action-detail">{action.detail}</span>
                  {/if}
                </div>
                {#if action.success === false}
                  <span class="action-status error">✗</span>
                {:else if action.success === true}
                  <span class="action-status success">✓</span>
                {/if}
              </div>
            {/each}
          </div>
        </div>
      {/if}
    {/if}
  </div>
{/if}

<style>
  .thinking-panel {
    background: #1a1a22;
    border: 1px solid #2a2a33;
    border-radius: 8px;
    margin: 8px;
    max-height: 60vh;
    overflow-y: auto;
  }

  .thinking-panel.completed {
    border-color: #3d5a3d;
    background: #161a16;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 14px;
    background: #22222a;
    cursor: pointer;
    border-radius: 7px 7px 0 0;
  }

  .thinking-panel.completed header {
    background: #1a2a1a;
  }

  .left {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  strong {
    color: #ececf1;
    font-size: 0.85em;
    letter-spacing: 0.05em;
  }

  .status {
    color: #9aa3c2;
    font-size: 0.8em;
  }

  .check-icon {
    font-size: 1em;
    color: #7fd288;
  }

  .phase-count {
    color: #7fd288;
    font-size: 0.8em;
  }

  .toggle {
    background: transparent;
    border: none;
    color: #68a8ef;
    font-size: 0.9em;
    cursor: pointer;
    padding: 4px 8px;
  }

  .toggle:hover {
    color: #8dc8ff;
  }

  .phases {
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .phase {
    background: #101014;
    border-left: 3px solid var(--phase-color, #68a8ef);
    border-radius: 6px;
    padding: 8px 12px;
    opacity: 0.4;
    transition: opacity 0.2s, background 0.2s;
  }

  .phase.active, .phase.completed {
    opacity: 1;
  }

  .phase.has-content:hover {
    background: #14141a;
  }

  .phase-header {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    background: transparent;
    border: none;
    padding: 0;
    cursor: pointer;
    text-align: left;
    color: inherit;
  }

  .phase-header:disabled {
    cursor: default;
  }

  .icon {
    font-size: 1em;
  }

  .label {
    color: #ececf1;
    font-size: 0.85em;
    font-weight: 500;
    flex: 1;
  }

  .badge {
    font-size: 0.7em;
    padding: 2px 6px;
    background: #2a2a33;
    border-radius: 4px;
    color: #9aa3c2;
    text-transform: uppercase;
  }

  .badge.active {
    background: var(--phase-color, #68a8ef);
    color: #fff;
  }

  .badge.completed {
    background: #7fd288;
    color: #000;
  }

  .expand-icon {
    color: #68a8ef;
    font-size: 0.7em;
    margin-left: 4px;
  }

  .phase-content {
    margin-top: 10px;
    background: #0a0a0e;
    border-radius: 6px;
    overflow: hidden;
  }

  /* Tabs */
  .tabs {
    display: flex;
    border-bottom: 1px solid #2a2a33;
  }

  .tab {
    flex: 1;
    padding: 8px 12px;
    background: transparent;
    border: none;
    color: #6b7280;
    font-size: 0.75em;
    font-weight: 500;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    transition: all 0.2s;
  }

  .tab:hover:not(:disabled) {
    background: #14141a;
    color: #9aa3c2;
  }

  .tab.active {
    background: #1a1a22;
    color: #ececf1;
    border-bottom: 2px solid var(--phase-color, #68a8ef);
  }

  .tab:disabled {
    cursor: not-allowed;
    opacity: 0.4;
  }

  .tab-icon {
    font-size: 1.1em;
  }

  .tab-hint {
    font-size: 0.85em;
    opacity: 0.7;
  }

  /* Content area */
  .content-area {
    max-height: 300px;
    overflow-y: auto;
  }

  .content-area pre {
    margin: 0;
    padding: 12px;
    font-size: 0.75em;
    line-height: 1.5;
    color: #c8d0e8;
    white-space: pre-wrap;
    word-wrap: break-word;
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  }

  .no-content {
    padding: 20px;
    text-align: center;
    color: #6b7280;
    font-size: 0.8em;
    font-style: italic;
  }

  /* Journey section styles */
  .journey-section {
    margin: 12px;
    margin-top: 4px;
    background: #12121a;
    border: 1px solid #2a2a33;
    border-radius: 6px;
    overflow: hidden;
  }

  .journey-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background: #1a1a22;
    border-bottom: 1px solid #2a2a33;
  }

  .journey-title {
    font-size: 0.75em;
    font-weight: 600;
    color: #9aa3c2;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .journey-count {
    font-size: 0.7em;
    color: #6b7280;
  }

  .journey-actions {
    padding: 8px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    max-height: 150px;
    overflow-y: auto;
  }

  .journey-action {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 6px 8px;
    background: #0a0a0e;
    border-radius: 4px;
    border-left: 2px solid #3a3a44;
    transition: border-color 0.2s;
  }

  .journey-action.success {
    border-left-color: #7fd288;
  }

  .journey-action.error {
    border-left-color: #ef6b6b;
    background: #1a0a0a;
  }

  .action-icon {
    font-size: 0.85em;
    flex-shrink: 0;
    margin-top: 1px;
  }

  .action-content {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .action-label {
    font-size: 0.75em;
    color: #ececf1;
    font-weight: 500;
  }

  .action-detail {
    font-size: 0.65em;
    color: #6b7280;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .action-status {
    font-size: 0.7em;
    flex-shrink: 0;
  }

  .action-status.success {
    color: #7fd288;
  }

  .action-status.error {
    color: #ef6b6b;
  }
</style>
