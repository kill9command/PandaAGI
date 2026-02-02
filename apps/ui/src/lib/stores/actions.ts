/**
 * Actions Store - Tracks the journey/decisions made during a turn
 *
 * Shows where information came from (memory, search, fetch) and key decisions
 */

import { writable, get } from 'svelte/store';

export type ActionType =
  | 'memory'      // Loaded memory file
  | 'search'      // Web search
  | 'fetch'       // URL fetch
  | 'fetch_retry' // Fetch retry with browser
  | 'route'       // Route decision
  | 'tool'        // Generic tool
  | 'error'       // Error occurred
  | 'decision';   // Key decision point

export interface Action {
  id: string;
  type: ActionType;
  icon: string;
  label: string;
  detail?: string;
  timestamp: number;
  success?: boolean;
}

interface ActionsState {
  actions: Action[];
  turnId: string | null;
}

function createActionsStore() {
  const { subscribe, set, update } = writable<ActionsState>({
    actions: [],
    turnId: null
  });

  let actionCounter = 0;

  return {
    subscribe,

    // Start tracking a new turn
    startTurn(turnId: string) {
      actionCounter = 0;
      set({ actions: [], turnId });
    },

    // Add an action to the log
    addAction(type: ActionType, label: string, detail?: string, success?: boolean) {
      const icons: Record<ActionType, string> = {
        memory: '📄',
        search: '🔍',
        fetch: '🌐',
        fetch_retry: '🔄',
        route: '🛤️',
        tool: '🔧',
        error: '❌',
        decision: '💡'
      };

      const action: Action = {
        id: `action-${++actionCounter}`,
        type,
        icon: icons[type] || '•',
        label,
        detail,
        timestamp: Date.now(),
        success
      };

      update(state => ({
        ...state,
        actions: [...state.actions, action]
      }));
    },

    // Clear all actions
    clear() {
      set({ actions: [], turnId: null });
    },

    // Get current actions
    getActions() {
      return get({ subscribe }).actions;
    }
  };
}

export const actions = createActionsStore();

// Helper to parse action from backend message
export function parseActionFromMessage(data: any) {
  if (data.type === 'action') {
    actions.addAction(
      data.action_type || 'tool',
      data.label || data.action,
      data.detail,
      data.success
    );
  }
}
