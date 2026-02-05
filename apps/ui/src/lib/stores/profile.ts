import { writable, get } from 'svelte/store';
import { browser } from '$app/environment';

const PROFILE_KEY = 'pandora.profile';
const PROFILES_KEY = 'pandora.profileList';
const REMEMBER_KEY = 'pandora.profileRemember';
const DEFAULT_PROFILES = ['default', 'user2', 'user3'];

function getStored<T>(key: string, fallback: T): T {
  if (!browser) return fallback;
  try {
    const val = localStorage.getItem(key);
    return val ? JSON.parse(val) : fallback;
  } catch {
    return fallback;
  }
}

function setStored(key: string, value: unknown) {
  if (!browser) return;
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {}
}

// Profiles list
export const profiles = writable<string[]>(getStored(PROFILES_KEY, DEFAULT_PROFILES));
profiles.subscribe(v => setStored(PROFILES_KEY, v));

// Remember toggle
export const remember = writable<boolean>(getStored(REMEMBER_KEY, true));
remember.subscribe(v => setStored(REMEMBER_KEY, v));

// Current profile
const initialProfile = browser && getStored(REMEMBER_KEY, true)
  ? getStored(PROFILE_KEY, 'default')
  : 'default';
export const profile = writable<string>(initialProfile);
profile.subscribe(v => {
  if (get(remember)) setStored(PROFILE_KEY, v);
});

// Add new profile
export function addProfile(name: string) {
  const trimmed = name.trim();
  if (!trimmed) return;

  profiles.update(p => {
    if (p.includes(trimmed)) return p;
    return [...p, trimmed];
  });
  profile.set(trimmed);
}
