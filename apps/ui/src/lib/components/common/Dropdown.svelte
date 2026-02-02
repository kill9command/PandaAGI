<script lang="ts">
  export let items: string[] = [];
  export let value = '';
  export let placeholder = 'Select...';
</script>

<select bind:value class="dropdown">
  {#if placeholder && !value}
    <option value="" disabled>{placeholder}</option>
  {/if}
  {#each items as item}
    <option value={item}>{item}</option>
  {/each}
</select>

<style>
  .dropdown {
    appearance: none;
    -webkit-appearance: none;
    -moz-appearance: none;
    background: #101014 url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%239aa3c2' d='M6 8L2 4h8z'/%3E%3C/svg%3E") no-repeat right 10px center;
    color: #ececf1;
    border: 1px solid #2a2a33;
    border-radius: 6px;
    padding: 6px 30px 6px 10px;
    font-size: 0.95em;
    cursor: pointer;
    min-width: 100px;
  }

  .dropdown:focus {
    outline: none;
    border-color: #445fe6;
  }

  .dropdown option {
    background: #1a1a22;
    color: #ececf1;
    padding: 8px;
  }
</style>
