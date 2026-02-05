import { writable, derived, get } from 'svelte/store';
import { profile } from './profile';
import { browser } from '$app/environment';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  traceId?: string;
}

const CHAT_PREFIX = 'panda.chat.';

function getChatKey(profileName: string): string {
  return CHAT_PREFIX + profileName.replace(/[^a-z0-9_-]/gi, '_');
}

function loadMessages(profileName: string): Message[] {
  if (!browser) return [];
  try {
    const stored = localStorage.getItem(getChatKey(profileName));
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

function saveMessages(profileName: string, messages: Message[]) {
  if (!browser) return;
  try {
    localStorage.setItem(getChatKey(profileName), JSON.stringify(messages));
  } catch {}
}

// Messages store
export const messages = writable<Message[]>(loadMessages(get(profile)));

// Re-load when profile changes
profile.subscribe(p => {
  messages.set(loadMessages(p));
});

// Save when messages change
messages.subscribe(m => {
  saveMessages(get(profile), m);
});

// Loading state
export const isLoading = writable(false);

// Current trace ID for thinking panel
export const currentTraceId = writable<string | null>(null);

// Add message
export function addMessage(role: 'user' | 'assistant', content: string, traceId?: string) {
  const msg: Message = {
    id: crypto.randomUUID(),
    role,
    content,
    timestamp: Date.now(),
    traceId
  };
  messages.update(m => [...m, msg]);
  return msg;
}

// Update last assistant message (for streaming)
export function updateLastAssistant(content: string) {
  messages.update(m => {
    // Find last assistant message (compatible with older browsers)
    let idx = -1;
    for (let i = m.length - 1; i >= 0; i--) {
      if (m[i].role === 'assistant') {
        idx = i;
        break;
      }
    }
    if (idx >= 0) {
      m[idx] = { ...m[idx], content };
    }
    return [...m];
  });
}

// Clear messages
export function clearMessages() {
  messages.set([]);
}
