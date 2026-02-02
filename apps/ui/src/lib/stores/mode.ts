import { writable } from 'svelte/store';
import { browser } from '$app/environment';

const MODE_KEY = 'pandora.mode';

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

// Repo root (for code mode)
const REPO_KEY = 'pandora.repoRoot';

export const repoRoot = writable<string>(
  browser ? localStorage.getItem(REPO_KEY) || '' : ''
);

repoRoot.subscribe(v => {
  if (browser) localStorage.setItem(REPO_KEY, v);
});
