<script lang="ts">
  import { thinking } from '$lib/stores/thinking';
  import Spinner from '$lib/components/common/Spinner.svelte';
  import SourcesPanel from './SourcesPanel.svelte';

  // Phase definitions matching the backend stage names from phase_metrics.py
  // Backend emits: phase_0_query_analyzer, phase_1_reflection, phase_2_context_gatherer, etc.
  const phaseDefinitions = [
    { key: 'phase_0_query_analyzer', label: 'Analyze', icon: '🔍', color: '#68a8ef' },
    { key: 'phase_1_reflection', label: 'Reflect', icon: '🤔', color: '#c792ea' },
    { key: 'phase_2_context_gatherer', label: 'Gather', icon: '📚', color: '#ffa500' },
    { key: 'phase_3_planner', label: 'Plan', icon: '📋', color: '#ef9b6b' },
    { key: 'phase_4_executor', label: 'Execute', icon: '⚡', color: '#ef6b9b' },
    { key: 'phase_5_coordinator', label: 'Coordinate', icon: '🔧', color: '#6befa8' },
    { key: 'phase_6_synthesis', label: 'Synthesize', icon: '✍️', color: '#a8ef6b' },
    { key: 'phase_7_validation', label: 'Validate', icon: '✓', color: '#6b9bef' },
    { key: 'phase_8_save', label: 'Save', icon: '💾', color: '#9b6bef' }
  ];

  let expanded = false;
  let expandedPhase: string | null = null;
  let activeTabs: Record<string, 'input' | 'output'> = {};
  let rawMode: Record<string, boolean> = {};

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
      inputRaw: data?.inputRaw || '',
      outputRaw: data?.outputRaw || '',
      duration: data?.duration || 0,
      confidence: data?.confidence || 0,
      hasData: !!(data?.input || data?.output || data?.content || data?.inputRaw || data?.outputRaw)
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

  function toggleRawMode(key: string) {
    rawMode[key] = !rawMode[key];
    rawMode = rawMode; // Trigger reactivity
  }

  function getDisplayContent(phase: typeof phases[0], tab: 'input' | 'output'): string {
    const isRaw = rawMode[phase.key] || false;
    if (tab === 'input') {
      return isRaw ? (phase.inputRaw || phase.input || '') : (phase.input || '');
    } else {
      return isRaw ? (phase.outputRaw || phase.output || phase.content || '') : (phase.output || phase.content || '');
    }
  }

  function hasRawContent(phase: typeof phases[0], tab: 'input' | 'output'): boolean {
    if (tab === 'input') {
      return !!(phase.inputRaw && phase.inputRaw !== phase.input);
    } else {
      return !!(phase.outputRaw && phase.outputRaw !== phase.output);
    }
  }

  function formatDuration(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }

  // Check if we should show the panel
  $: showPanel = $thinking.active || $thinking.completed;
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
              {#if phase.duration > 0}
                <span class="duration">{formatDuration(phase.duration)}</span>
              {/if}
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
                    disabled={!phase.input && !phase.inputRaw}
                  >
                    <span class="tab-icon">&rarr;</span> INPUT
                  </button>
                  <button
                    class="tab"
                    class:active={activeTabs[phase.key] === 'output'}
                    on:click|stopPropagation={() => setActiveTab(phase.key, 'output')}
                    disabled={!phase.output && !phase.content && !phase.outputRaw}
                  >
                    <span class="tab-icon">&larr;</span> OUTPUT
                  </button>
                  <!-- Raw toggle -->
                  {#if hasRawContent(phase, activeTabs[phase.key] || 'output')}
                    <button
                      class="raw-toggle"
                      class:active={rawMode[phase.key]}
                      on:click|stopPropagation={() => toggleRawMode(phase.key)}
                      title={rawMode[phase.key] ? 'Show summary' : 'Show raw content'}
                    >
                      {rawMode[phase.key] ? 'SUMMARY' : 'RAW'}
                    </button>
                  {/if}
                </div>

                <!-- Content area -->
                <div class="content-area">
                  {#if getDisplayContent(phase, activeTabs[phase.key] || 'output')}
                    <pre>{getDisplayContent(phase, activeTabs[phase.key] || 'output')}</pre>
                  {:else}
                    <div class="no-content">No {activeTabs[phase.key] || 'output'} data captured</div>
                  {/if}
                </div>
              </div>
            {/if}
          </div>
        {/each}
      </div>

      <!-- Sources panel (replaces old Journey section) -->
      <SourcesPanel />
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

  .duration {
    font-size: 0.65em;
    color: #6b7280;
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
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

  .raw-toggle {
    padding: 4px 10px;
    background: #1a1a22;
    border: 1px solid #2a2a33;
    border-bottom: none;
    color: #6b7280;
    font-size: 0.6em;
    font-weight: 600;
    cursor: pointer;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    transition: all 0.2s;
    flex-shrink: 0;
  }

  .raw-toggle:hover {
    color: #9aa3c2;
    background: #22222a;
  }

  .raw-toggle.active {
    color: #68a8ef;
    background: #14141a;
    border-color: #68a8ef;
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
</style>
