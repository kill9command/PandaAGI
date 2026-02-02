# Pandora UI Modernization Plan

## Overview

Modernize the Pandora UI by adopting Open WebUI's Svelte component patterns while preserving Pandora-specific features: profile management, chat/code mode selection, repo configuration, thinking visualization, and intervention handling.

---

## Current State

### Existing UI (`static/`)
| File | Purpose |
|------|---------|
| `index.html` | Monolithic HTML with inline structure |
| `app_v2.js` | ~1800 lines vanilla JS |
| `styles.css` | CSS styling |
| `intervention_handler.js` | CAPTCHA/auth wall handling |
| `research_progress.js` | WebSocket research progress |
| `permission_prompt.js` | Code mode permission handling |

### Features to Preserve
1. **Chat/Code Mode Toggle** - Radio buttons switching between chat and code modes
2. **Profile System** - Dropdown selector, name adder, "Remember" checkbox, localStorage persistence
3. **Repo Configuration** - Input for repo root path (shown in code mode)
4. **Thinking Visualization** - 6-stage progress panel with confidence bars
5. **Intervention System** - CAPTCHA resolution, permission prompts
6. **Research Progress** - WebSocket-based real-time updates
7. **IDE Workspace** - Monaco editor, file tree, task tracker (code mode)

---

## Target Architecture

```
apps/ui/                          # New Svelte-based UI
├── src/
│   ├── lib/
│   │   ├── components/
│   │   │   ├── chat/             # Cloned from Open WebUI + customized
│   │   │   │   ├── Messages/
│   │   │   │   │   ├── Message.svelte
│   │   │   │   │   ├── UserMessage.svelte
│   │   │   │   │   ├── ResponseMessage.svelte
│   │   │   │   │   ├── CodeBlock.svelte
│   │   │   │   │   ├── Markdown.svelte
│   │   │   │   │   └── Skeleton.svelte
│   │   │   │   ├── MessageInput/
│   │   │   │   │   ├── MessageInput.svelte
│   │   │   │   │   └── FileUpload.svelte
│   │   │   │   └── Chat.svelte
│   │   │   │
│   │   │   ├── common/           # Cloned from Open WebUI
│   │   │   │   ├── Modal.svelte
│   │   │   │   ├── ConfirmDialog.svelte
│   │   │   │   ├── Spinner.svelte
│   │   │   │   ├── Tooltip.svelte
│   │   │   │   ├── Dropdown.svelte
│   │   │   │   └── Badge.svelte
│   │   │   │
│   │   │   └── pandora/          # Pandora-specific (build custom)
│   │   │       ├── ModeSelector.svelte      # Chat/Code toggle
│   │   │       ├── ProfileManager.svelte    # Profile dropdown + adder
│   │   │       ├── RepoConfig.svelte        # Repo path input
│   │   │       ├── ThinkingPanel.svelte     # 8-phase visualization
│   │   │       ├── PhaseProgress.svelte     # Individual phase card
│   │   │       ├── InterventionModal.svelte # CAPTCHA/permission UI
│   │   │       ├── ResearchProgress.svelte  # WebSocket progress
│   │   │       ├── ContextStatusBar.svelte  # Repo/mode/CWD display
│   │   │       └── IDEWorkspace.svelte      # Monaco + file tree
│   │   │
│   │   ├── stores/               # Svelte stores for state
│   │   │   ├── chat.ts           # Messages, session state
│   │   │   ├── profile.ts        # Profile selection, persistence
│   │   │   ├── mode.ts           # Chat/code mode
│   │   │   ├── thinking.ts       # Thinking panel state
│   │   │   └── research.ts       # Research progress state
│   │   │
│   │   └── api/                  # Gateway API client
│   │       ├── client.ts         # Main HTTP client
│   │       ├── thinking.ts       # SSE thinking stream
│   │       ├── research.ts       # WebSocket research events
│   │       └── interventions.ts  # Intervention resolution
│   │
│   ├── routes/
│   │   ├── +layout.svelte        # App shell
│   │   ├── +page.svelte          # Main chat page
│   │   └── transcripts/
│   │       └── +page.svelte      # Transcript viewer
│   │
│   └── app.css                   # Global styles (Tailwind)
│
├── static/
│   └── icons/                    # Pandora icons
│
├── package.json
├── svelte.config.js
├── tailwind.config.js
└── vite.config.ts
```

---

## Implementation Phases

### Phase 1: Project Setup (Day 1)

#### 1.1 Initialize SvelteKit Project
```bash
cd /home/henry/pythonprojects/pandaai
npx sv create apps/ui --template minimal --types ts
cd apps/ui
npm install
```

#### 1.2 Add Dependencies
```bash
npm install -D tailwindcss postcss autoprefixer
npm install highlight.js marked dompurify
npm install @sveltejs/adapter-static
npx tailwindcss init -p
```

#### 1.3 Configure Static Adapter
Update `svelte.config.js` for static build that can be served by Gateway:
```javascript
import adapter from '@sveltejs/adapter-static';

export default {
  kit: {
    adapter: adapter({
      pages: '../../static/app',  // Output to static/app/
      assets: '../../static/app',
      fallback: 'index.html'
    })
  }
};
```

---

### Phase 2: Clone Open WebUI Components (Day 1-2)

#### 2.1 Message Components
Clone and adapt from `open-webui/src/lib/components/chat/Messages/`:

| Source File | Adaptations Needed |
|-------------|-------------------|
| `ResponseMessage.svelte` | Remove OpenAI-specific fields, add Pandora thinking integration |
| `UserMessage.svelte` | Simplify, keep core rendering |
| `CodeBlock.svelte` | Keep as-is, uses highlight.js |
| `Markdown.svelte` | Keep as-is, uses marked + DOMPurify |
| `Skeleton.svelte` | Adapt for Pandora's thinking stages |

#### 2.2 Input Components
Clone from `open-webui/src/lib/components/chat/MessageInput/`:
- Keep textarea auto-resize logic
- Keep keyboard shortcuts (Ctrl+Enter, etc.)
- Remove file attachment (optional, can add later)

#### 2.3 Common Components
Clone from `open-webui/src/lib/components/common/`:
- `Modal.svelte` - For interventions, settings
- `Spinner.svelte` - Loading states
- `Tooltip.svelte` - Help hints
- `Dropdown.svelte` - Profile selector

---

### Phase 3: Build Pandora-Specific Components (Day 2-3)

#### 3.1 ModeSelector.svelte
```svelte
<script lang="ts">
  import { mode } from '$lib/stores/mode';

  const modes = [
    { value: 'chat', label: 'Chat', icon: '💬' },
    { value: 'code', label: 'Code', icon: '💻' }
  ];
</script>

<div class="mode-selector">
  {#each modes as m}
    <label class:active={$mode === m.value}>
      <input type="radio" name="mode" value={m.value} bind:group={$mode} />
      <span>{m.icon} {m.label}</span>
    </label>
  {/each}
</div>
```

#### 3.2 ProfileManager.svelte
```svelte
<script lang="ts">
  import { profile, profiles, addProfile, remember } from '$lib/stores/profile';
  import Dropdown from '$lib/components/common/Dropdown.svelte';

  let newProfileName = '';

  function handleAdd() {
    if (newProfileName.trim()) {
      addProfile(newProfileName.trim());
      newProfileName = '';
    }
  }
</script>

<div class="profile-manager">
  <label>Profile:</label>
  <Dropdown items={$profiles} bind:value={$profile} />

  <input
    type="text"
    bind:value={newProfileName}
    placeholder="Add profile"
    on:keydown={(e) => e.key === 'Enter' && handleAdd()}
  />
  <button on:click={handleAdd}>Add</button>

  <label>
    <input type="checkbox" bind:checked={$remember} />
    Remember
  </label>
</div>
```

#### 3.3 ThinkingPanel.svelte
```svelte
<script lang="ts">
  import { thinking } from '$lib/stores/thinking';
  import PhaseProgress from './PhaseProgress.svelte';

  const phases = [
    { key: 'query_received', label: 'Query Received', icon: '📩', color: '#68a8ef' },
    { key: 'guide_analyzing', label: 'Guide Analyzing', icon: '🧠', color: '#9b6bef' },
    { key: 'coordinator_planning', label: 'Coordinator Planning', icon: '📋', color: '#ffa500' },
    { key: 'orchestrator_executing', label: 'Orchestrator Executing', icon: '⚙️', color: '#ef6b9b' },
    { key: 'guide_synthesizing', label: 'Guide Synthesizing', icon: '✨', color: '#6befa8' },
    { key: 'response_complete', label: 'Response Complete', icon: '✅', color: '#7fd288' }
  ];
</script>

{#if $thinking.active}
  <div class="thinking-panel">
    <header>
      <span class="spinner"></span>
      <strong>THINKING</strong>
      <span class="status">{$thinking.status}</span>
    </header>

    <div class="phases">
      {#each phases as phase}
        <PhaseProgress
          {...phase}
          status={$thinking.phases[phase.key]?.status || 'pending'}
          confidence={$thinking.phases[phase.key]?.confidence || 0}
          reasoning={$thinking.phases[phase.key]?.reasoning || ''}
          duration={$thinking.phases[phase.key]?.duration}
        />
      {/each}
    </div>
  </div>
{/if}
```

#### 3.4 InterventionModal.svelte
```svelte
<script lang="ts">
  import { interventions, resolveIntervention } from '$lib/stores/research';
  import Modal from '$lib/components/common/Modal.svelte';

  $: currentIntervention = $interventions[0];
</script>

{#if currentIntervention}
  <Modal title="Human Assistance Required" on:close={() => resolveIntervention(currentIntervention.id, false)}>
    <div class="intervention">
      <span class="badge">{currentIntervention.type}</span>
      <p>{currentIntervention.message}</p>

      {#if currentIntervention.cdp_url}
        <button on:click={() => window.open(currentIntervention.cdp_url, '_blank', 'width=1400,height=900')}>
          🖥️ Open Browser
        </button>
      {/if}

      {#if currentIntervention.screenshot_url}
        <img src={currentIntervention.screenshot_url} alt="Page screenshot" />
      {/if}

      <div class="actions">
        <button class="primary" on:click={() => resolveIntervention(currentIntervention.id, true)}>
          ✓ I've Solved It
        </button>
        <button on:click={() => resolveIntervention(currentIntervention.id, false)}>
          Skip
        </button>
      </div>
    </div>
  </Modal>
{/if}
```

---

### Phase 4: API Integration (Day 3-4)

#### 4.1 Gateway Client (`src/lib/api/client.ts`)
```typescript
const API_BASE = '/v1';

export interface ChatRequest {
  messages: { role: string; content: string }[];
  mode: 'chat' | 'code';
  session_id: string;
  user_id: string;
  repo?: string;
}

export async function sendChat(request: ChatRequest): Promise<Response> {
  const apiKey = localStorage.getItem('pandora.apiKey') || 'sk-local';

  return fetch(`${API_BASE}/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${apiKey}`,
      'X-User-Id': request.user_id
    },
    body: JSON.stringify(request)
  });
}
```

#### 4.2 Thinking SSE Stream (`src/lib/api/thinking.ts`)
```typescript
export function connectThinkingStream(traceId: string, onEvent: (event: ThinkingEvent) => void) {
  const eventSource = new EventSource(`/v1/thinking/${traceId}`);

  eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    onEvent(data);
  };

  eventSource.onerror = () => {
    eventSource.close();
  };

  return () => eventSource.close();
}
```

#### 4.3 Research WebSocket (`src/lib/api/research.ts`)
```typescript
export function connectResearchWebSocket(sessionId: string, onEvent: (event: ResearchEvent) => void) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${protocol}//${window.location.host}/ws/research/${sessionId}`);

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    onEvent(data);
  };

  return () => ws.close();
}
```

---

### Phase 5: Svelte Stores (Day 4)

#### 5.1 Profile Store (`src/lib/stores/profile.ts`)
```typescript
import { writable, derived } from 'svelte/store';
import { browser } from '$app/environment';

const PROFILE_KEY = 'pandora.profile';
const PROFILES_KEY = 'pandora.profileList';
const REMEMBER_KEY = 'pandora.profileRemember';

const DEFAULT_PROFILES = ['henry', 'wife', 'daughter'];

function createProfileStore() {
  const profiles = writable<string[]>(
    browser ? JSON.parse(localStorage.getItem(PROFILES_KEY) || 'null') || DEFAULT_PROFILES : DEFAULT_PROFILES
  );

  const remember = writable<boolean>(
    browser ? localStorage.getItem(REMEMBER_KEY) !== '0' : true
  );

  const profile = writable<string>(
    browser && localStorage.getItem(REMEMBER_KEY) !== '0'
      ? localStorage.getItem(PROFILE_KEY) || 'henry'
      : 'henry'
  );

  // Persist on change
  if (browser) {
    profiles.subscribe(v => localStorage.setItem(PROFILES_KEY, JSON.stringify(v)));
    remember.subscribe(v => localStorage.setItem(REMEMBER_KEY, v ? '1' : '0'));
    profile.subscribe(v => {
      if (localStorage.getItem(REMEMBER_KEY) !== '0') {
        localStorage.setItem(PROFILE_KEY, v);
      }
    });
  }

  function addProfile(name: string) {
    profiles.update(p => [...p, name]);
    profile.set(name);
  }

  return { profile, profiles, remember, addProfile };
}

export const { profile, profiles, remember, addProfile } = createProfileStore();
```

#### 5.2 Mode Store (`src/lib/stores/mode.ts`)
```typescript
import { writable } from 'svelte/store';
import { browser } from '$app/environment';

const MODE_KEY = 'pandora.mode';

export const mode = writable<'chat' | 'code'>(
  browser ? (localStorage.getItem(MODE_KEY) as 'chat' | 'code') || 'chat' : 'chat'
);

if (browser) {
  mode.subscribe(v => localStorage.setItem(MODE_KEY, v));
}
```

---

### Phase 6: Main Page Assembly (Day 4-5)

#### 6.1 Layout (`src/routes/+layout.svelte`)
```svelte
<script>
  import '../app.css';
</script>

<div class="app">
  <slot />
</div>

<style>
  .app {
    min-height: 100vh;
    background: #101014;
    color: #ececf1;
  }
</style>
```

#### 6.2 Main Page (`src/routes/+page.svelte`)
```svelte
<script lang="ts">
  import Chat from '$lib/components/chat/Chat.svelte';
  import ModeSelector from '$lib/components/pandora/ModeSelector.svelte';
  import ProfileManager from '$lib/components/pandora/ProfileManager.svelte';
  import RepoConfig from '$lib/components/pandora/RepoConfig.svelte';
  import ThinkingPanel from '$lib/components/pandora/ThinkingPanel.svelte';
  import InterventionModal from '$lib/components/pandora/InterventionModal.svelte';
  import ContextStatusBar from '$lib/components/pandora/ContextStatusBar.svelte';
  import IDEWorkspace from '$lib/components/pandora/IDEWorkspace.svelte';

  import { mode } from '$lib/stores/mode';
  import { profile } from '$lib/stores/profile';
  import { thinking } from '$lib/stores/thinking';
</script>

<svelte:head>
  <title>Pandora AI</title>
</svelte:head>

<div class="container">
  <header>
    <img src="/icons/panda-hamster.svg" alt="Pandora" />
    <h1>Pandora AI</h1>
    <nav>
      <a href="/transcripts">Transcripts</a>
      <a href="/research_monitor.html" target="_blank">Research Monitor</a>
    </nav>
  </header>

  <div class="toolbar">
    <ModeSelector />
    <ProfileManager />
    {#if $mode === 'code'}
      <RepoConfig />
    {/if}
  </div>

  <ContextStatusBar />

  {#if $mode === 'code'}
    <IDEWorkspace />
  {/if}

  <ThinkingPanel />

  <Chat />

  <InterventionModal />
</div>
```

---

### Phase 7: Build & Deploy Integration (Day 5)

#### 7.1 Build Script
Add to `package.json`:
```json
{
  "scripts": {
    "build": "vite build",
    "build:static": "vite build && cp -r build/* ../../static/app/"
  }
}
```

#### 7.2 Gateway Route Update
Update `apps/services/gateway/app.py` to serve the new UI:
```python
from fastapi.staticfiles import StaticFiles

# Mount new Svelte UI
app.mount("/app", StaticFiles(directory="static/app", html=True), name="app")

# Redirect root to new UI
@app.get("/")
async def root():
    return RedirectResponse(url="/app")
```

#### 7.3 Development Workflow
```bash
# Terminal 1: Run Svelte dev server
cd apps/ui && npm run dev

# Terminal 2: Run Gateway (API only)
cd /home/henry/pythonprojects/pandaai && ./scripts/start.sh

# Configure Svelte to proxy API calls to Gateway
# vite.config.ts:
export default defineConfig({
  server: {
    proxy: {
      '/v1': 'http://localhost:9000',
      '/ws': { target: 'ws://localhost:9000', ws: true }
    }
  }
});
```

---

## Component Mapping

### From Open WebUI (Clone & Adapt)
| Open WebUI Component | Pandora Component | Adaptations |
|---------------------|-------------------|-------------|
| `Messages/ResponseMessage.svelte` | `chat/Messages/ResponseMessage.svelte` | Add thinking integration |
| `Messages/UserMessage.svelte` | `chat/Messages/UserMessage.svelte` | Simplify |
| `Messages/CodeBlock.svelte` | `chat/Messages/CodeBlock.svelte` | Keep as-is |
| `Messages/Markdown.svelte` | `chat/Messages/Markdown.svelte` | Keep as-is |
| `Messages/Skeleton.svelte` | `chat/Messages/Skeleton.svelte` | Adapt for phases |
| `MessageInput/MessageInput.svelte` | `chat/MessageInput/MessageInput.svelte` | Add mode awareness |
| `common/Modal.svelte` | `common/Modal.svelte` | Keep as-is |
| `common/Spinner.svelte` | `common/Spinner.svelte` | Keep as-is |
| `common/Dropdown.svelte` | `common/Dropdown.svelte` | Keep as-is |

### Pandora-Specific (Build New)
| Component | Purpose | Source Reference |
|-----------|---------|------------------|
| `ModeSelector.svelte` | Chat/Code toggle | `index.html` lines 53-54 |
| `ProfileManager.svelte` | Profile dropdown + adder | `index.html` lines 62-74 |
| `RepoConfig.svelte` | Repo path input | `index.html` lines 76-80 |
| `ThinkingPanel.svelte` | 8-phase visualization | `index.html` lines 229-355 |
| `InterventionModal.svelte` | CAPTCHA resolution | `intervention_handler.js` |
| `ResearchProgress.svelte` | WebSocket progress | `research_progress.js` |
| `ContextStatusBar.svelte` | Repo/mode/CWD bar | `index.html` lines 104-119 |
| `IDEWorkspace.svelte` | Monaco + file tree | `index.html` lines 121-154 |

---

## Migration Strategy

### Phase 1: Parallel Development
- Keep existing `static/` UI operational
- Develop new UI at `apps/ui/`
- New UI available at `/app` route

### Phase 2: Feature Parity Testing
- Test all features in new UI
- Fix any regressions
- Get user feedback

### Phase 3: Cutover
- Make new UI the default at `/`
- Move old UI to `/legacy` (optional)
- Update any hardcoded references

---

## Testing Checklist

### Core Features
- [ ] Chat mode: Send message, receive response
- [ ] Code mode: Send message with repo context
- [ ] Profile: Switch profiles, add new profile, remember toggle
- [ ] Thinking panel: Shows progress during request
- [ ] Message rendering: Markdown, code blocks, links

### Research Features
- [ ] Research progress WebSocket events display
- [ ] Intervention modal appears for CAPTCHAs
- [ ] Intervention resolution sends to Gateway
- [ ] Research progress messages in chat

### Code Mode Features
- [ ] Repo path configuration
- [ ] IDE workspace (Monaco editor)
- [ ] File tree navigation
- [ ] Context status bar updates

---

## Estimated Timeline

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| 1. Project Setup | 4 hours | SvelteKit project with Tailwind |
| 2. Clone Open WebUI | 8 hours | Message rendering, input, common components |
| 3. Pandora Components | 12 hours | Mode selector, profiles, thinking, interventions |
| 4. API Integration | 6 hours | Gateway client, SSE, WebSocket |
| 5. Svelte Stores | 4 hours | State management |
| 6. Page Assembly | 6 hours | Main page, layout, routing |
| 7. Build Integration | 4 hours | Static build, Gateway serving |

**Total: ~44 hours (5-6 days)**

---

## Dependencies

### NPM Packages
```json
{
  "dependencies": {
    "highlight.js": "^11.9.0",
    "marked": "^12.0.0",
    "dompurify": "^3.0.8"
  },
  "devDependencies": {
    "@sveltejs/adapter-static": "^3.0.0",
    "tailwindcss": "^3.4.0",
    "postcss": "^8.4.0",
    "autoprefixer": "^10.4.0",
    "@types/dompurify": "^3.0.5"
  }
}
```

### External Resources
- Open WebUI repo: `https://github.com/open-webui/open-webui`
- Components path: `src/lib/components/`
- License: BSD 3-Clause (attribution required)

---

## File References

### Current UI Files to Port Logic From
- `/home/henry/pythonprojects/pandaai/static/index.html` - HTML structure
- `/home/henry/pythonprojects/pandaai/static/app_v2.js` - App logic
- `/home/henry/pythonprojects/pandaai/static/styles.css` - Styling
- `/home/henry/pythonprojects/pandaai/static/intervention_handler.js` - Interventions
- `/home/henry/pythonprojects/pandaai/static/research_progress.js` - Research WebSocket
- `/home/henry/pythonprojects/pandaai/static/permission_prompt.js` - Permissions

### Gateway API Endpoints
- `POST /v1/chat/completions` - Main chat endpoint
- `GET /v1/thinking/{trace_id}` - SSE thinking stream
- `WS /ws/research/{session_id}` - Research WebSocket
- `GET /interventions/pending` - Pending interventions
- `POST /interventions/{id}/resolve` - Resolve intervention
- `GET /transcripts` - Transcript list
- `GET /health` - Health check
