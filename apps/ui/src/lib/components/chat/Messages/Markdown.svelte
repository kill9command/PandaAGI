<script lang="ts">
  import { marked } from 'marked';
  import DOMPurify from 'dompurify';
  import CodeBlock from './CodeBlock.svelte';

  export let content: string = '';

  interface CodeMatch {
    lang: string;
    code: string;
    placeholder: string;
  }

  // Extract code blocks and replace with placeholders
  function extractCodeBlocks(text: string | null | undefined): { html: string; codeBlocks: CodeMatch[] } {
    if (!text) return { html: '', codeBlocks: [] };

    const codeBlocks: CodeMatch[] = [];
    const regex = /```(\w*)\n([\s\S]*?)```/g;
    let match;
    let result = text;
    let index = 0;

    while ((match = regex.exec(text)) !== null) {
      const placeholder = `__CODE_BLOCK_${index}__`;
      codeBlocks.push({
        lang: match[1] || '',
        code: match[2].trim(),
        placeholder
      });
      result = result.replace(match[0], placeholder);
      index++;
    }

    return { html: result, codeBlocks };
  }

  $: ({ html: textWithPlaceholders, codeBlocks } = extractCodeBlocks(content));
  $: parsedHtml = textWithPlaceholders ? DOMPurify.sanitize(marked.parse(textWithPlaceholders, { async: false }) as string) : '';

  // Split parsed HTML by placeholders
  $: parts = parsedHtml.split(/(__CODE_BLOCK_\d+__)/g);
</script>

<div class="markdown">
  {#each parts as part}
    {#if part.startsWith('__CODE_BLOCK_')}
      {@const blockIndex = parseInt(part.match(/\d+/)?.[0] || '0')}
      {@const block = codeBlocks[blockIndex]}
      {#if block}
        <CodeBlock code={block.code} language={block.lang} />
      {/if}
    {:else}
      {@html part}
    {/if}
  {/each}
</div>

<style>
  .markdown {
    line-height: 1.6;
  }

  .markdown :global(p) {
    margin: 0.5em 0;
  }

  .markdown :global(ul), .markdown :global(ol) {
    margin: 0.5em 0;
    padding-left: 1.5em;
  }

  .markdown :global(li) {
    margin: 0.25em 0;
  }

  .markdown :global(a) {
    color: #68a8ef;
    text-decoration: none;
  }

  .markdown :global(a:hover) {
    text-decoration: underline;
  }

  .markdown :global(code) {
    background: #2a2a33;
    padding: 2px 6px;
    border-radius: 4px;
    font-family: 'Fira Mono', 'Consolas', monospace;
    font-size: 0.9em;
  }

  .markdown :global(blockquote) {
    border-left: 3px solid #445fe6;
    margin: 0.5em 0;
    padding-left: 1em;
    color: #9aa3c2;
  }

  .markdown :global(h1), .markdown :global(h2), .markdown :global(h3) {
    margin: 1em 0 0.5em;
    color: #ececf1;
  }

  .markdown :global(table) {
    border-collapse: collapse;
    margin: 0.5em 0;
    width: 100%;
  }

  .markdown :global(th), .markdown :global(td) {
    border: 1px solid #2a2a33;
    padding: 8px;
    text-align: left;
  }

  .markdown :global(th) {
    background: #1a1a22;
  }
</style>
