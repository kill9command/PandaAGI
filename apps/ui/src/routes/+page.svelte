<script lang="ts">
  import Chat from '$lib/components/chat/Chat.svelte';
  import { IDEWorkspace } from '$lib/components/ide';
  import ModeSelector from '$lib/components/pandora/ModeSelector.svelte';
  import ProfileManager from '$lib/components/pandora/ProfileManager.svelte';
  import RepoConfig from '$lib/components/pandora/RepoConfig.svelte';
  import InterventionModal from '$lib/components/pandora/InterventionModal.svelte';
  import ContextStatusBar from '$lib/components/pandora/ContextStatusBar.svelte';
  import { mode } from '$lib/stores/mode';
</script>

<svelte:head>
  <title>Pandora AI</title>
</svelte:head>

<div class="container" class:ide-mode={$mode === 'code'}>
  <header class="app-header">
    <div class="brand">
      <img src="/icons/panda-hamster.svg" alt="Pandora" class="logo" />
      <h1>Pandora AI</h1>
    </div>
    <nav>
      <a href="/transcripts">Transcripts</a>
      <a href="/research_monitor.html" target="_blank">🔍 Research</a>
    </nav>
  </header>

  <div class="toolbar">
    <ModeSelector />
    <ProfileManager />
    {#if $mode === 'code'}
      <RepoConfig />
    {/if}
  </div>

  <ContextStatusBar />

  <main class="main-content">
    {#if $mode === 'code'}
      <IDEWorkspace />
    {:else}
      <Chat />
    {/if}
  </main>

  <InterventionModal />
</div>

<style>
  .container {
    max-width: 1000px;
    margin: 0 auto;
    height: 100vh;
    display: flex;
    flex-direction: column;
    background: #17171c;
    box-shadow: 0 0 40px rgba(0, 0, 0, 0.5);
    overflow: hidden;
  }

  .container.ide-mode {
    max-width: 100%;
    margin: 0;
    box-shadow: none;
  }

  .app-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    background: #16161a;
    border-bottom: 1px solid #22222a;
    flex-shrink: 0;
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .logo {
    height: 32px;
    width: auto;
  }

  h1 {
    margin: 0;
    font-size: 1.4em;
    font-weight: 700;
    color: #ececf1;
    letter-spacing: 0.02em;
  }

  nav {
    display: flex;
    gap: 16px;
  }

  nav a {
    color: #68a8ef;
    font-size: 0.85em;
    text-decoration: none;
  }

  nav a:hover {
    text-decoration: underline;
  }

  .toolbar {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 12px 16px;
    background: #181820;
    border-bottom: 1px solid #22222a;
    flex-wrap: wrap;
    flex-shrink: 0;
  }

  .main-content {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
  }

  @media (max-width: 768px) {
    .container {
      max-width: 100%;
    }

    .toolbar {
      gap: 12px;
    }

    .app-header {
      flex-direction: column;
      gap: 12px;
    }
  }
</style>
