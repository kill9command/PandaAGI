<script lang="ts">
  export let size = 16;
  export let color = '#68a8ef';
</script>

<span
  class="spinner"
  style="width: {size}px; height: {size}px; border-color: {color}; border-top-color: transparent;"
></span>

<style>
  .spinner {
    display: inline-block;
    border: 2px solid;
    border-radius: 50%;
    animation: spin 1s linear infinite;
  }

  @keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
  }
</style>
