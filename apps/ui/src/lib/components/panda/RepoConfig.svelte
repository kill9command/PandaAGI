<script lang="ts">
  import { repoRoot } from '$lib/stores/mode';

  let inputValue = $repoRoot;
  let saved = false;

  function handleSave() {
    repoRoot.set(inputValue);
    saved = true;
    setTimeout(() => saved = false, 1500);
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') handleSave();
  }
</script>

<div class="repo-config">
  <label class="label">Repo:</label>
  <input
    type="text"
    bind:value={inputValue}
    placeholder="/home/user/project"
    on:keydown={handleKeydown}
    autocomplete="off"
  />
  <button on:click={handleSave}>
    {saved ? '✓' : 'Save'}
  </button>
</div>

<style>
  .repo-config {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .label {
    color: #9aa3c2;
    font-size: 0.9em;
  }

  input {
    background: #101014;
    border: 1px solid #2a2a33;
    border-radius: 6px;
    padding: 6px 10px;
    color: #ececf1;
    font-size: 0.9em;
    font-family: monospace;
    width: 250px;
  }

  input:focus {
    outline: none;
    border-color: #445fe6;
  }

  button {
    background: #2a2a88;
    color: #fff;
    border: none;
    border-radius: 6px;
    padding: 6px 12px;
    cursor: pointer;
    font-size: 0.85em;
    min-width: 50px;
  }

  button:hover {
    background: #3a3a98;
  }
</style>
