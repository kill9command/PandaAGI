<script>
  import '../app.css';
  import { onMount } from 'svelte';

  onMount(() => {
    // Hide the loading screen once the app is mounted
    const loader = document.getElementById('app-loading');
    if (loader) {
      loader.classList.add('hidden');
    }
  });
</script>

<div class="app">
  <slot />
</div>

<style>
  .app {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }
</style>
