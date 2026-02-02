import { writable, derived, get } from 'svelte/store';
import { repoRoot } from './mode';

// Types
export interface EditorState {
  selectedFile: string | null;
  openTabs: string[];
  fileContent: string | null;
  fileLoading: boolean;
  fileError: string | null;
}

// Initial state
const initialState: EditorState = {
  selectedFile: null,
  openTabs: [],
  fileContent: null,
  fileLoading: false,
  fileError: null,
};

// Main store
const editorStore = writable<EditorState>(initialState);

// Derived stores for individual values
export const selectedFile = derived(editorStore, ($s) => $s.selectedFile);
export const openTabs = derived(editorStore, ($s) => $s.openTabs);
export const fileContent = derived(editorStore, ($s) => $s.fileContent);
export const fileLoading = derived(editorStore, ($s) => $s.fileLoading);
export const fileError = derived(editorStore, ($s) => $s.fileError);

// Actions
export async function openFile(filePath: string, lineNumber?: number) {
  const state = get(editorStore);
  const repo = get(repoRoot);

  // Add to tabs if not already open
  if (!state.openTabs.includes(filePath)) {
    editorStore.update((s) => ({
      ...s,
      openTabs: [...s.openTabs, filePath],
    }));
  }

  // Set as selected file and start loading
  editorStore.update((s) => ({
    ...s,
    selectedFile: filePath,
    fileLoading: true,
    fileError: null,
  }));

  try {
    // Call the file.read tool via the orchestrator
    const response = await fetch('/tool/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tool: 'file.read',
        args: {
          file_path: filePath,
          repo: repo || undefined,
        },
      }),
    });

    if (!response.ok) {
      throw new Error(`Failed to read file: ${response.statusText}`);
    }

    const result = await response.json();

    if (result.error) {
      throw new Error(result.error);
    }

    editorStore.update((s) => ({
      ...s,
      fileContent: result.content || result.data || '',
      fileLoading: false,
    }));

    // TODO: If lineNumber is provided, scroll editor to that line
    // This will be handled by the Editor component
  } catch (error) {
    editorStore.update((s) => ({
      ...s,
      fileLoading: false,
      fileError: error instanceof Error ? error.message : 'Failed to load file',
    }));
  }
}

export function closeTab(filePath: string) {
  editorStore.update((s) => {
    const newTabs = s.openTabs.filter((t) => t !== filePath);

    // If closing the selected file, switch to another tab
    let newSelected = s.selectedFile;
    if (s.selectedFile === filePath) {
      if (newTabs.length > 0) {
        // Select the previous tab, or the first one
        const closedIndex = s.openTabs.indexOf(filePath);
        const newIndex = Math.max(0, closedIndex - 1);
        newSelected = newTabs[newIndex];
      } else {
        newSelected = null;
      }
    }

    return {
      ...s,
      openTabs: newTabs,
      selectedFile: newSelected,
      // Clear content if no file selected
      fileContent: newSelected ? s.fileContent : null,
    };
  });

  // If we switched to a different file, load its content
  const state = get(editorStore);
  if (state.selectedFile && state.selectedFile !== filePath) {
    openFile(state.selectedFile);
  }
}

export function closeAllTabs() {
  editorStore.set(initialState);
}

// Reset editor when repo changes
repoRoot.subscribe(() => {
  editorStore.set(initialState);
});
