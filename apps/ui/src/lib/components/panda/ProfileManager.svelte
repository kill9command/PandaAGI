<script lang="ts">
  import { profile, profiles, remember, addProfile } from '$lib/stores/profile';
  import Dropdown from '$lib/components/common/Dropdown.svelte';

  let newProfileName = '';

  function handleAdd() {
    if (newProfileName.trim()) {
      addProfile(newProfileName.trim());
      newProfileName = '';
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') handleAdd();
  }
</script>

<div class="profile-manager">
  <label class="label">Profile:</label>
  <Dropdown items={$profiles} bind:value={$profile} />

  <div class="add-profile">
    <input
      type="text"
      bind:value={newProfileName}
      placeholder="Add profile"
      on:keydown={handleKeydown}
      autocomplete="off"
    />
    <button on:click={handleAdd}>Add</button>
  </div>

  <label class="remember">
    <input type="checkbox" bind:checked={$remember} />
    <span>Remember</span>
  </label>
</div>

<style>
  .profile-manager {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }

  .label {
    color: #9aa3c2;
    font-size: 0.9em;
  }

  .add-profile {
    display: flex;
    gap: 4px;
  }

  .add-profile input {
    background: #101014;
    border: 1px solid #2a2a33;
    border-radius: 6px;
    padding: 6px 10px;
    color: #ececf1;
    font-size: 0.9em;
    width: 120px;
  }

  .add-profile input:focus {
    outline: none;
    border-color: #445fe6;
  }

  .add-profile button {
    background: #2a2a88;
    color: #fff;
    border: none;
    border-radius: 6px;
    padding: 6px 12px;
    cursor: pointer;
    font-size: 0.85em;
  }

  .add-profile button:hover {
    background: #3a3a98;
  }

  .remember {
    display: flex;
    align-items: center;
    gap: 6px;
    color: #9aa3c2;
    font-size: 0.85em;
    cursor: pointer;
  }

  .remember input {
    cursor: pointer;
  }
</style>
