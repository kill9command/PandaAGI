import { writable } from 'svelte/store';

export interface PhaseState {
  status: 'pending' | 'active' | 'completed' | 'error';
  confidence: number;
  reasoning: string;
  duration?: number;
  content?: string;  // Full phase output text for display
  input?: string;    // What the phase received as input
  output?: string;   // What the phase produced as output
}

export interface ThinkingState {
  active: boolean;
  completed: boolean;  // True after turn completes, keeps panel visible
  status: string;
  sseStatus: string;  // SSE connection status for debugging
  phases: Record<string, PhaseState>;
}

const initialState: ThinkingState = {
  active: false,
  completed: false,
  status: 'Ready',
  sseStatus: 'idle',
  phases: {}
};

export const thinking = writable<ThinkingState>(initialState);

export function startThinking() {
  thinking.set({
    active: true,
    completed: false,
    status: 'Starting...',
    sseStatus: 'connecting',
    phases: {}
  });
}

export function updateSseStatus(status: string) {
  thinking.update(t => ({ ...t, sseStatus: status }));
}

export function updatePhase(stage: string, data: Partial<PhaseState>) {
  console.log('[ThinkingStore] updatePhase called:', { stage, data });
  thinking.update(t => {
    const newState = {
      ...t,
      status: data.reasoning || t.status,
      phases: {
        ...t.phases,
        [stage]: {
          ...t.phases[stage],
          status: 'active',
          confidence: 0,
          reasoning: '',
          ...data
        }
      }
    };
    console.log('[ThinkingStore] New phases:', Object.keys(newState.phases));
    return newState;
  });
}

export function stopThinking() {
  thinking.update(t => ({
    ...t,
    active: false,
    completed: true,  // Keep showing panel in completed state
    status: 'Complete'
  }));
}

export function resetThinking() {
  thinking.set(initialState);
}
