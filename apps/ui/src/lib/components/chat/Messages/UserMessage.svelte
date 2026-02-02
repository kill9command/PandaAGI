<script lang="ts">
  export let content: string;
  export let timestamp: number;

  $: timeStr = new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
</script>

<div class="user-message">
  <div class="content">{content}</div>
  <span class="time">{timeStr}</span>
</div>

<style>
  .user-message {
    align-self: flex-end;
    max-width: 85%;
    background: linear-gradient(90deg, #242449 70%, #31318e 100%);
    color: #f8f8fb;
    padding: 12px 16px;
    border-radius: 16px 16px 4px 16px;
    box-shadow: 0 2px 8px rgba(34, 34, 90, 0.3);
  }

  .content {
    white-space: pre-wrap;
    word-break: break-word;
  }

  .time {
    display: block;
    font-size: 0.75em;
    color: rgba(255, 255, 255, 0.5);
    text-align: right;
    margin-top: 4px;
  }
</style>
