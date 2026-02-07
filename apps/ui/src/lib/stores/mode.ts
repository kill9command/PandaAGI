import { writable } from 'svelte/store';
import { browser } from '$app/environment';

const MODE_KEY = 'panda.mode';

type Mode = 'chat' | 'code';

function getInitialMode(): Mode {
  if (!browser) return 'chat';
  const stored = localStorage.getItem(MODE_KEY);
  return (stored === 'code') ? 'code' : 'chat';
}

export const mode = writable<Mode>(getInitialMode());

mode.subscribe(v => {
  if (browser) localStorage.setItem(MODE_KEY, v);
});

// Model provider toggle (panda = local Qwen, claude = Claude API)
const PROVIDER_KEY = 'panda.modelProvider';

type ModelProvider = 'panda' | 'claude';

function getInitialProvider(): ModelProvider {
  if (!browser) return 'panda';
  const stored = localStorage.getItem(PROVIDER_KEY);
  return (stored === 'claude') ? 'claude' : 'panda';
}

export const modelProvider = writable<ModelProvider>(getInitialProvider());

modelProvider.subscribe(v => {
  if (browser) localStorage.setItem(PROVIDER_KEY, v);
});

// Repo root (for code mode)
const REPO_KEY = 'panda.repoRoot';

export const repoRoot = writable<string>(
  browser ? localStorage.getItem(REPO_KEY) || '' : ''
);

repoRoot.subscribe(v => {
  if (browser) localStorage.setItem(REPO_KEY, v);
});
