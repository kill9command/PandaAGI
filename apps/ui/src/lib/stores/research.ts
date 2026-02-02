import { writable, get } from 'svelte/store';

export interface Intervention {
  id: string;
  type: string;
  url: string;
  message: string;
  screenshotUrl?: string;
  cdpUrl?: string;
}

export interface ResearchProgress {
  checked: number;
  accepted: number;
  rejected: number;
  total: number;
}

export const interventions = writable<Intervention[]>([]);
export const researchProgress = writable<ResearchProgress>({
  checked: 0, accepted: 0, rejected: 0, total: 0
});
export const isResearching = writable(false);

let ws: WebSocket | null = null;
let pollInterval: number | null = null;

export function connectResearch(sessionId: string) {
  disconnectResearch();

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${protocol}//${window.location.host}/ws/research/${sessionId}`;

  ws = new WebSocket(url);

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleResearchEvent(data);
    } catch (e) {
      console.error('[Research] Parse error:', e);
    }
  };

  ws.onerror = (e) => console.error('[Research] WebSocket error:', e);
  ws.onclose = () => { ws = null; };

  // Also start polling for interventions as fallback
  startInterventionPolling();
}

export function disconnectResearch() {
  if (ws) {
    ws.close();
    ws = null;
  }
  stopInterventionPolling();
  isResearching.set(false);
  researchProgress.set({ checked: 0, accepted: 0, rejected: 0, total: 0 });
}

function handleResearchEvent(event: { type: string; data?: Record<string, unknown> }) {
  const { type, data = {} } = event;

  switch (type) {
    case 'research_started':
      isResearching.set(true);
      researchProgress.set({ checked: 0, accepted: 0, rejected: 0, total: 0 });
      break;

    case 'intervention_needed':
      interventions.update(list => [...list, {
        id: data.intervention_id as string,
        type: data.blocker_type as string,
        url: data.url as string,
        message: `${data.blocker_type} detected`,
        screenshotUrl: data.screenshot_path ? `/screenshots/${(data.screenshot_path as string).split('/').pop()}` : undefined,
        cdpUrl: data.cdp_url as string | undefined
      }]);
      break;

    case 'intervention_resolved':
      interventions.update(list => list.filter(i => i.id !== data.intervention_id));
      break;

    case 'progress':
      researchProgress.set({
        checked: data.checked as number || 0,
        accepted: data.accepted as number || 0,
        rejected: data.rejected as number || 0,
        total: data.total as number || 0
      });
      break;

    case 'research_complete':
      isResearching.set(false);
      break;
  }
}

function startInterventionPolling() {
  if (pollInterval) return;

  pollInterval = window.setInterval(async () => {
    try {
      const resp = await fetch('/interventions/pending');
      if (!resp.ok) return;

      const data = await resp.json();
      const pending = data.interventions || [];
      const current = get(interventions);

      for (const intervention of pending) {
        if (!current.find(i => i.id === intervention.intervention_id)) {
          interventions.update(list => [...list, {
            id: intervention.intervention_id,
            type: intervention.type,
            url: intervention.url,
            message: `${intervention.type} detected`,
            screenshotUrl: intervention.screenshot_path ? `/screenshots/${intervention.screenshot_path.split('/').pop()}` : undefined,
            cdpUrl: intervention.cdp_url
          }]);
        }
      }
    } catch {}
  }, 2000);
}

function stopInterventionPolling() {
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
}

export async function resolveIntervention(id: string, success: boolean) {
  try {
    await fetch(`/interventions/${id}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resolved: success, cookies: null })
    });
    interventions.update(list => list.filter(i => i.id !== id));
  } catch (e) {
    console.error('[Research] Failed to resolve intervention:', e);
  }
}
