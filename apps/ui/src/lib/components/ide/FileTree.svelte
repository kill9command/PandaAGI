<script lang="ts">
  import { repoRoot } from '$lib/stores/mode';
  import { selectedFile, openFile } from '$lib/stores/editor';
  import { onMount } from 'svelte';

  interface TreeNode {
    id: string;
    text: string;
    type: 'file' | 'folder';
    path?: string;
    children?: TreeNode[];
  }

  let treeData: TreeNode[] = [];
  let expandedFolders = new Set<string>();
  let loading = false;
  let error: string | null = null;

  async function loadFileTree() {
    if (!$repoRoot) {
      treeData = [];
      return;
    }

    loading = true;
    error = null;

    try {
      const response = await fetch(`/ui/filetree?repo=${encodeURIComponent($repoRoot)}`);
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        if (response.status === 403) {
          throw new Error(`Access denied: ${errorData.detail || 'Repo path not allowed. Check REPOS_BASE config.'}`);
        } else if (response.status === 404) {
          throw new Error(`Path not found: ${$repoRoot}`);
        }
        throw new Error(errorData.detail || `Failed to load file tree: ${response.statusText}`);
      }
      const data = await response.json();
      treeData = data.tree || [];
      console.log('[FileTree] Loaded', treeData.length, 'items from', $repoRoot);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load file tree';
      treeData = [];
      console.error('[FileTree] Error:', error);
    } finally {
      loading = false;
    }
  }

  function toggleFolder(nodeId: string) {
    if (expandedFolders.has(nodeId)) {
      expandedFolders.delete(nodeId);
    } else {
      expandedFolders.add(nodeId);
    }
    expandedFolders = expandedFolders; // Trigger reactivity
  }

  function handleFileClick(node: TreeNode) {
    if (node.type === 'file' && node.path) {
      openFile(node.path);
    }
  }

  function getFileIcon(filename: string): string {
    const ext = filename.split('.').pop()?.toLowerCase();
    const icons: Record<string, string> = {
      ts: '📘',
      js: '📒',
      svelte: '🧡',
      py: '🐍',
      md: '📝',
      json: '📋',
      html: '🌐',
      css: '🎨',
      yml: '⚙️',
      yaml: '⚙️',
      sh: '💻',
      sql: '🗃️',
    };
    return icons[ext || ''] || '📄';
  }

  // Reload when repo changes
  $: if ($repoRoot) {
    loadFileTree();
  }

  onMount(() => {
    if ($repoRoot) {
      loadFileTree();
    }
  });

  export function refresh() {
    loadFileTree();
  }
</script>

<div class="file-tree">
  {#if loading}
    <div class="loading">Loading...</div>
  {:else if error}
    <div class="error">{error}</div>
  {:else if treeData.length === 0}
    <div class="empty">
      {#if $repoRoot}
        No files found
      {:else}
        Set a repository path to browse files
      {/if}
    </div>
  {:else}
    <ul class="tree-root">
      {#each treeData as node (node.id)}
        <li class="tree-node">
          {#if node.type === 'folder'}
            <button
              class="node-toggle"
              class:expanded={expandedFolders.has(node.id)}
              on:click={() => toggleFolder(node.id)}
            >
              <span class="toggle-icon">{expandedFolders.has(node.id) ? '▼' : '▶'}</span>
              <span class="folder-icon">📁</span>
              <span class="node-name">{node.text}</span>
            </button>
            {#if expandedFolders.has(node.id) && node.children}
              <ul class="tree-children">
                {#each node.children as child (child.id)}
                  <svelte:self {...child} />
                {/each}
              </ul>
            {/if}
          {:else}
            <button
              class="node-file"
              class:selected={$selectedFile === node.path}
              on:click={() => handleFileClick(node)}
            >
              <span class="file-icon">{getFileIcon(node.text)}</span>
              <span class="node-name">{node.text}</span>
            </button>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .file-tree {
    padding: 8px;
    font-size: 0.9em;
    color: #cfd3e9;
  }

  .loading,
  .error,
  .empty {
    padding: 16px;
    text-align: center;
    color: #9aa3c2;
    font-size: 0.85em;
  }

  .error {
    color: #ff6b6b;
  }

  .tree-root,
  .tree-children {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .tree-children {
    padding-left: 16px;
  }

  .tree-node {
    margin: 1px 0;
  }

  .node-toggle,
  .node-file {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    padding: 4px 8px;
    background: transparent;
    border: none;
    border-radius: 4px;
    color: #cfd3e9;
    cursor: pointer;
    text-align: left;
    font-size: inherit;
    transition: background 0.15s;
  }

  .node-toggle:hover,
  .node-file:hover {
    background: #2a2a33;
  }

  .node-file.selected {
    background: #3a3a53;
    color: #fff;
  }

  .toggle-icon {
    font-size: 0.7em;
    width: 12px;
    color: #9aa3c2;
  }

  .folder-icon,
  .file-icon {
    font-size: 1em;
  }

  .node-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
