# User Interface Architecture

**Status:** SPECIFICATION
**Version:** 2.1
**Updated:** 2026-01-25

---

## 1. Overview

PandaAI provides multiple interface options:

1. **Web UI (Primary)** - SvelteKit-based chat interface served by Gateway
2. **VSCode Extension** - IDE-integrated chat and status panels
3. **CLI Tool** - Terminal-first for quick queries
4. **Obsidian Vault** - Document exploration (optional)

### 1.1 Design Principles

1. **Web UI for general use** - Browser-based, no install required
2. **VSCode for developers** - IDE integration for code workflows
3. **CLI for quick queries** - Terminal-first for simple interactions
4. **Real-time visibility** - See what's happening during research
5. **Intervention when needed** - CAPTCHA/blockers handled seamlessly

---

## 2. Web UI (SvelteKit)

The primary web interface is a SvelteKit application served by the Gateway at port 9000.

### 2.1 Technology Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| SvelteKit | 2.5.0 (pinned) | App framework |
| Svelte | 4.x | Component framework |
| Tailwind CSS | 3.4.x | Styling |
| TypeScript | 5.x | Type safety |
| Vite | 5.x | Build tool |

> **Version Constraint:** SvelteKit is pinned to `2.5.0` (not `^2.5.0`) because versions 2.8+ progressively require Svelte 5 runtime features (`untrack`, `fork`, `settled`) that don't exist in Svelte 4. Do not upgrade SvelteKit without also upgrading to Svelte 5.

### 2.2 Directory Structure

```
apps/ui/
├── package.json           # Dependencies (pinned versions)
├── svelte.config.js       # SvelteKit config (static adapter)
├── vite.config.ts         # Vite build config
├── tailwind.config.js     # Tailwind theme
├── tsconfig.json          # TypeScript config
├── src/
│   ├── app.html           # HTML template with loading screen
│   ├── app.css            # Global styles
│   ├── routes/
│   │   ├── +layout.svelte # Root layout (hides loader on mount)
│   │   ├── +layout.ts     # SSR disabled, prerender enabled
│   │   ├── +page.svelte   # Main chat page
│   │   └── transcripts/
│   │       └── +page.svelte
│   └── lib/
│       ├── api/
│       │   └── client.ts  # Gateway API client
│       ├── stores/
│       │   ├── chat.ts    # Message history
│       │   ├── mode.ts    # Chat/code mode
│       │   ├── profile.ts # User profile
│       │   ├── thinking.ts # Phase visualization
│       │   └── research.ts # Research progress
│       └── components/
│           ├── chat/
│           │   ├── Chat.svelte
│           │   ├── MessageInput.svelte
│           │   └── Messages/
│           ├── common/
│           │   ├── Modal.svelte
│           │   ├── Spinner.svelte
│           │   └── Dropdown.svelte
│           └── pandora/
│               ├── ModeSelector.svelte
│               ├── ProfileManager.svelte
│               ├── ThinkingPanel.svelte
│               └── InterventionModal.svelte
├── static/
│   └── icons/
│       └── panda-hamster.svg
└── build/                 # Production build output
```

### 2.3 Key Components

| Component | Purpose |
|-----------|---------|
| `+page.svelte` | Main chat interface with header, toolbar, chat area |
| `Chat.svelte` | Message list and input handling |
| `ThinkingPanel.svelte` | Real-time phase visualization during processing |
| `InterventionModal.svelte` | CAPTCHA/blocker resolution UI |
| `ModeSelector.svelte` | Chat vs Code mode toggle |
| `ProfileManager.svelte` | User profile selection |

### 2.4 API Integration

The client (`src/lib/api/client.ts`) communicates with the Gateway:

```typescript
// API endpoint
const API_BASE = '/v1';

// Chat completions (OpenAI-compatible)
POST /v1/chat/completions
Headers: Authorization: Bearer {api_key}

// Thinking visualization (SSE)
GET /v1/thinking/{trace_id}

// Research progress (WebSocket)
WS /ws/research/{session_id}
```

**Authentication:** The UI sends `Authorization: Bearer {key}` where key defaults to `qwen-local` (matching `GATEWAY_API_KEY` in `.env`).

### 2.5 Build & Deploy

```bash
cd apps/ui

# Development
npm run dev          # Starts on localhost:5173

# Production build
npm run build        # Outputs to build/

# Build and copy to static
npm run build:static # Copies to ../../static/app/
```

**Gateway Integration:** The Gateway serves the built UI:
- `apps/ui/build/index.html` → served at `/`
- `apps/ui/build/_app/` → served at `/_app/`
- Legacy UI available at `/legacy/`

### 2.6 Loading Screen

The `app.html` template includes an inline loading screen that displays while SvelteKit hydrates:

```html
<div id="app-loading">
  <div class="spinner"></div>
  <p>Loading Pandora AI...</p>
</div>
```

The `+layout.svelte` hides it on mount:

```svelte
<script>
  import { onMount } from 'svelte';
  onMount(() => {
    document.getElementById('app-loading')?.classList.add('hidden');
  });
</script>
```

### 2.7 Stores

Svelte stores manage application state:

| Store | Purpose |
|-------|---------|
| `chat` | Messages, loading state, trace ID |
| `mode` | Current mode (chat/code), repo root |
| `profile` | Selected user profile |
| `thinking` | Phase progress, confidence, reasoning |
| `research` | WebSocket connection, research events |

---

## 3. VSCode Extension

### 1.1 Design Principles

1. **VSCode is the hub** - Don't fight where developers live
2. **CLI for quick queries** - Terminal-first for simple interactions
3. **Real-time visibility** - See what's happening during research
4. **Intervention when needed** - CAPTCHA/blockers handled seamlessly
5. **Documents are browsable** - Past turns accessible as files
6. **Reviewable changes** - Proposed edits show as diffs with apply/undo
7. **CLI parity** - Core workflows usable from both terminal and UI

### 1.2 Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| VSCode Extension | Primary interface | TypeScript + Webview |
| CLI Tool | Quick terminal queries | Python (Typer + Rich) |
| Obsidian Vault | Document exploration (optional) | Markdown |
| noVNC | Human intervention | Browser/Webview |

---

## 2. Interface Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            VSCode Window                                 │
├─────────────┬───────────────────────────────────────┬───────────────────┤
│   SIDEBAR   │           EDITOR AREA                 │    CHAT PANEL     │
│             │                                       │                   │
│ ┌─────────┐ │  ┌─────────────────────────────────┐  │ ┌───────────────┐ │
│ │ PANDA   │ │  │                                 │  │ │ What would    │ │
│ │ STATUS  │ │  │     Your Code Files             │  │ │ you like to   │ │
│ │         │ │  │                                 │  │ │ know?         │ │
│ │ ● Idle  │ │  │     context.md (viewable)       │  │ │               │ │
│ │         │ │  │                                 │  │ │ ┌───────────┐ │ │
│ │ ─────── │ │  │     research.md (viewable)      │  │ │ │ Message   │ │ │
│ │ Recent  │ │  │                                 │  │ │ └───────────┘ │ │
│ │ Turn 42 │ │  └─────────────────────────────────┘  │ │    [Send]     │ │
│ │ Turn 41 │ │                                       │ │               │ │
│ │ Turn 40 │ │                                       │ │ ─────────────── │
│ │         │ │                                       │ │               │ │
│ │ ─────── │ │                                       │ │ [Research     │ │
│ │ Quality │ │                                       │ │  Progress]    │ │
│ │ ▁▂▄▆█   │ │                                       │ │               │ │
│ │ 0.85    │ │                                       │ │ Phase 2/7     │ │
│ │         │ │                                       │ │ ██████░░░ 67% │ │
│ │ ─────── │ │                                       │ │               │ │
│ │ Models  │ │                                       │ │ Vendors:      │ │
│ │ REFLEX ●│ │                                       │ │ ✓ bestbuy     │ │
│ │ MIND   ●│ │                                       │ │ ◐ walmart     │ │
│ │ VOICE  ○│ │                                       │ │ ○ newegg      │ │
│ │ EYES   ○│ │                                       │ │               │ │
│ └─────────┘ │                                       │ │ Products: 5   │ │
│             │                                       │ └───────────────┘ │
├─────────────┴───────────────────────────────────────┴───────────────────┤
│                         TERMINAL / OUTPUT                                │
│                                                                          │
│  $ panda "find me a cheap laptop with RTX"                              │
│  [Phase 1] Intelligence gathering... done                                │
│  [Phase 2] Visiting vendors...                                          │
│    bestbuy.com ✓ (3 products)                                           │
│    walmart.com ✓ (2 products)                                           │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 3. VSCode Extension: `panda-dashboard`

> **Status:** Planned - not yet implemented. The web UI is the current primary interface.

### 3.1 Sidebar Panel

The sidebar provides always-visible system status.

**Sections:**

| Section | Content |
|---------|---------|
| Status | Current state: Idle, Researching, Waiting for Intervention, Error |
| Current Turn | Turn number, elapsed time, current phase |
| Recent Turns | Last 10 turns, clickable to open context.md |
| Quality Trend | Sparkline of recent quality scores |
| Model Status | Which models are currently loaded/active |
| Token Usage | Today's token count by model |

**Data Source:** WebSocket subscription to Gateway events + file watcher on `turns/`

### 3.2 Chat Webview Panel

The chat panel is a webview that handles all conversational interaction.

**Features:**

| Feature | Description |
|---------|-------------|
| Message Input | Text input with send button, supports multiline |
| Response Display | Markdown rendering with syntax highlighting |
| Context Chips | Attached files/selection/memory shown above responses; click to open |
| Code Actions | Inline actions to open file, open diff, apply patch, revert |
| Streaming | Responses stream in real-time as they generate |
| Research Progress | Progress bar and vendor status during active research |
| Product Cards | Rich cards for commerce results (image, price, link) |
| Injection Controls | Buttons for "Cancel", "Skip Vendor", "Focus On..." |
| Intervention Alerts | Alert banner when CAPTCHA detected with "Open Browser" button |
| History | Scrollable conversation history within session |

**Layout:**

```
┌─────────────────────────────────┐
│         CHAT PANEL              │
├─────────────────────────────────┤
│                                 │
│  [Previous messages...]         │
│                                 │
│  ┌─────────────────────────┐    │
│  │ User: find me a cheap   │    │
│  │ laptop with RTX GPU     │    │
│  └─────────────────────────┘    │
│                                 │
│  ┌─────────────────────────┐    │
│  │ Panda: I found 3        │    │
│  │ options under $800:     │    │
│  │                         │    │
│  │ ┌─────────────────────┐ │    │
│  │ │ HP Victus 15        │ │    │
│  │ │ $649 - Walmart      │ │    │
│  │ │ RTX 4050, 16GB RAM  │ │    │
│  │ │ [View] [Save]       │ │    │
│  │ └─────────────────────┘ │    │
│  └─────────────────────────┘    │
│                                 │
├─────────────────────────────────┤
│  [Research in Progress]         │
│  Phase: Coordinator (4/7)       │
│  ██████████░░░░░ 67%           │
│                                 │
│  Vendors:                       │
│  ✓ bestbuy.com (3 products)    │
│  ◐ walmart.com (visiting...)   │
│  ○ newegg.com (pending)        │
│                                 │
│  [Cancel] [Skip Current]        │
├─────────────────────────────────┤
│  ┌───────────────────────────┐  │
│  │ Type your message...      │  │
│  └───────────────────────────┘  │
│                       [Send]    │
└─────────────────────────────────┘
```

### 3.2.1 Coding Workflow (Diff-First)

The chat panel supports a review-first coding loop:

1. Assistant proposes a patch (unified or side-by-side diff).
2. User reviews with inline file links and context chips.
3. User chooses Apply, Open Diff, or Reject.
4. Optional Run Tests action executes in the integrated terminal.

Edits are never applied without an explicit user action.

### 3.3 Intervention Handling

When a blocker is detected (CAPTCHA, login wall, Cloudflare):

```
┌─────────────────────────────────┐
│  ⚠️ INTERVENTION REQUIRED       │
├─────────────────────────────────┤
│                                 │
│  CAPTCHA detected on:           │
│  walmart.com                    │
│                                 │
│  [Screenshot preview]           │
│                                 │
│  ┌───────────┐ ┌───────────┐    │
│  │Open Browser│ │  Skip     │    │
│  └───────────┘ └───────────┘    │
│                                 │
│  Research paused. Solve the     │
│  CAPTCHA and click "I Solved    │
│  It" to continue.               │
│                                 │
└─────────────────────────────────┘
```

**Flow:**
1. Blocker detected during research
2. Alert appears in chat panel
3. User clicks "Open Browser" → Playwright browser window comes to foreground
4. User solves CAPTCHA directly in the browser
5. User clicks "Done" in VSCode
6. Research continues

### 3.4 Commands

| Command | Keybinding | Description |
|---------|------------|-------------|
| `Panda: New Chat` | `Ctrl+Shift+P` | Open/focus chat panel |
| `Panda: Send Message` | `Ctrl+Enter` | Send current message |
| `Panda: Cancel Research` | - | Stop current research |
| `Panda: Show Turn` | - | Open picker to select turn |
| `Panda: Show Current Turn` | - | Open current turn's context.md |
| `Panda: Show Metrics` | - | Open observability dashboard |
| `Panda: Retry Last` | - | Retry the last failed turn |
| `Panda: Clear History` | - | Clear chat history |
| `Panda: Show Diff` | - | Open diff for last proposed changes |
| `Panda: Apply Diff` | - | Apply last proposed changes |
| `Panda: Run Tests` | - | Run configured test command in terminal |

### 3.5 Status Bar

```
┌────────────────────────────────────────────────────────────────────────┐
│ $(panda-icon) Panda: Idle │ Turn 42 │ Quality: 0.85 │ Tokens: 12.4k    │
└────────────────────────────────────────────────────────────────────────┘
```

Clicking status bar opens command palette with Panda commands.

### 3.6 Visual Style Directions (Pick One)

Each option should respect VS Code theme tokens for background/foreground to feel native.

- Workbench Minimal: clean panels, subtle grid texture, amber accent for status and progress.
- Field Console: charcoal base, teal accents, data-dense cards, IBM Plex Sans + JetBrains Mono.
- Paper Lab: warm off-white base, ink-black text, terracotta accents, soft dot pattern.

---

## 4. CLI Tool: `panda`

> **Status:** Planned - not yet implemented.

For quick terminal queries without opening the chat panel.

### 4.1 Basic Usage

```bash
# Simple query
$ panda "what's the cheapest RTX 4060 laptop"

# With options
$ panda --no-stream "quick question"    # Wait for full response
$ panda --json "find laptops"           # Output as JSON
$ panda --turn 42                       # Reference specific turn
```

### 4.2 Output Format

```
$ panda "find me a cheap laptop with nvidia gpu"

┌─────────────────────────────────────────────────────────┐
│ Turn 43 │ commerce │ cheapest nvidia gpu laptop         │
└─────────────────────────────────────────────────────────┘

[Phase 0] Query analyzed ✓
[Phase 1] PROCEED ✓
[Phase 2] Context gathered ✓
[Phase 3] Route: coordinator
[Phase 4] Researching...
  ├── bestbuy.com ✓ 3 products (12.3s)
  ├── walmart.com ✓ 2 products (8.7s)
  └── newegg.com ✓ 4 products (15.2s)
[Phase 5] Synthesizing...
[Phase 7] Validated ✓ (quality: 0.87)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

I found 3 laptops under $800 with NVIDIA GPUs:

┌──────────────────────────────────────────────────────────┐
│ 1. HP Victus 15                                          │
│    $649 at Walmart                                       │
│    RTX 4050 • 16GB RAM • 512GB SSD                      │
│    https://walmart.com/ip/12345                         │
├──────────────────────────────────────────────────────────┤
│ 2. Lenovo LOQ 15                                         │
│    $697 at Best Buy                                      │
│    RTX 4050 • 16GB RAM • 512GB SSD                      │
│    https://bestbuy.com/site/lenovo-loq...               │
├──────────────────────────────────────────────────────────┤
│ 3. Acer Nitro V                                          │
│    $749 at Newegg                                        │
│    RTX 4050 • 8GB RAM • 512GB SSD                       │
│    https://newegg.com/acer-nitro...                     │
└──────────────────────────────────────────────────────────┘

Total time: 47.2s │ Tokens: 8,432 │ Sources: 3
```

### 4.3 Subcommands

```bash
# View past turns
$ panda turns                    # List recent turns
$ panda turns 42                 # Show turn 42 summary
$ panda turns 42 --full          # Show full context.md

# Check status
$ panda status                   # System status
$ panda status --metrics         # Today's metrics

# Memory operations
$ panda remember "I prefer RTX GPUs"
$ panda recall "gpu preference"
$ panda forget "budget constraint"

# Research cache
$ panda cache                    # List cached research
$ panda cache laptop             # Show laptop research cache
$ panda cache --clear            # Clear all cache

# Coding workflows
$ panda edit "rename class Foo to Bar"   # Propose unified diff
$ panda edit --apply                      # Apply after confirmation
$ panda diff                              # Show last proposed diff
```

### 4.4 Intervention via CLI

```
$ panda "find hamsters for sale"

[Phase 4] Researching...
  ├── petco.com ✓
  └── petsmart.com ⚠️  CAPTCHA detected

┌─────────────────────────────────────────────────────────┐
│ ⚠️  CAPTCHA REQUIRED                                    │
│                                                         │
│ Open browser to solve: http://localhost:6080            │
│                                                         │
│ Press [Enter] when solved, or [s] to skip this vendor  │
└─────────────────────────────────────────────────────────┘
```

---

## 5. Obsidian Integration (Optional)

> **Status:** Planned - not yet implemented.

Obsidian provides a human-readable view into the document system for exploration and review.

### 5.1 Vault Structure

```
panda-vault/
├── turns/
│   ├── turn_000042.md      # Wrapper note linking to context.md
│   ├── turn_000041.md
│   └── ...
├── research/
│   ├── laptop-nvidia.md    # Research summaries
│   └── ...
├── memory/
│   ├── preferences.md      # User preferences
│   └── facts.md            # Stored facts
└── dashboard.md            # Overview with embedded queries
```

### 5.2 Turn Wrapper Note

```markdown
---
turn_id: 42
session: default
created: 2026-01-05T14:30:00Z
action_needed: live_search
quality: 0.87
validation: APPROVE
tags: [laptop, nvidia, commerce]
---

# Turn 42: Cheapest NVIDIA Laptop

**Query:** find me a cheap laptop with nvidia gpu
**Quality:** 0.87 ●●●●○
**Validation:** APPROVE

## Quick Links
- [[context.md|Full Context]]
- [[research.md|Research Results]]
- [[metrics.json|Metrics]]

## Summary
Found 3 laptops under $800. Best option: HP Victus 15 at $649.

## Products Found
| Product | Price | Vendor |
|---------|-------|--------|
| HP Victus 15 | $649 | Walmart |
| Lenovo LOQ 15 | $697 | Best Buy |
| Acer Nitro V | $749 | Newegg |
```

### 5.3 Use Cases

| Use Case | How |
|----------|-----|
| Browse past conversations | Open `turns/` folder, sort by date |
| Search all research | Use Obsidian search across vault |
| Review quality trends | Dataview query on turn frontmatter |
| Explore topic clusters | Graph view shows connections |

### 5.4 Principles

- Obsidian is **read-only** for system data
- Never edit context.md through Obsidian
- Wrapper notes are regenerated on each turn
- Graph view shows relationships between turns, topics, vendors

---

## 6. API Gateway

### 6.1 Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/chat` | POST | Submit user message |
| `/chat/stream` | WebSocket | Stream response + progress |
| `/inject` | POST | Inject message during research |
| `/intervention/resolve` | POST | Mark intervention as resolved |
| `/turns` | GET | List recent turns |
| `/turns/{id}` | GET | Get specific turn |
| `/status` | GET | System health |
| `/metrics` | GET | Observability metrics |

### 6.2 WebSocket Events

```typescript
// Client → Server
{ type: "message", content: "find me a laptop" }
{ type: "inject", content: "skip walmart" }
{ type: "cancel" }
{ type: "intervention_resolved", intervention_id: "abc123" }

// Server → Client
{ type: "turn_started", turn_id: 43 }
{ type: "phase_started", phase: 0, name: "query_analyzer" }
{ type: "phase_completed", phase: 0, duration_ms: 450 }
{ type: "research_progress", vendor: "bestbuy.com", status: "visiting" }
{ type: "research_progress", vendor: "bestbuy.com", status: "done", products: 3 }
{ type: "product_found", product: { name: "HP Victus", price: 649, ... } }
{ type: "intervention_required", intervention_id: "abc123", type: "captcha", url: "..." }
{ type: "response_chunk", content: "I found 3 laptops..." }
{ type: "response_complete", quality: 0.87 }
{ type: "turn_complete", turn_id: 43, validation: "APPROVE" }
```

---

## 7. Local Browser Intervention

Since PandaAI runs locally, interventions use the system browser directly - no VNC or remote desktop needed.

### 7.1 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Local Machine                            │
│                                                              │
│  ┌──────────────┐         ┌──────────────────────────────┐  │
│  │  Playwright  │         │     System Browser           │  │
│  │  (headless)  │────────▶│  (Chrome/Edge/Firefox)       │  │
│  │              │ connect │                              │  │
│  └──────────────┘         │  User solves CAPTCHA here    │  │
│         │                 └──────────────────────────────┘  │
│         │                              │                     │
│         ▼                              │                     │
│  Research continues ◀──────────────────┘                     │
│  after intervention                                          │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 Intervention Flow

1. **Detection:** Playwright detects blocker (CAPTCHA, Cloudflare, login)
2. **Pause:** Research pauses, browser stays on blocked page
3. **Notify:** WebSocket event sent to UI with screenshot
4. **Alert:** Chat panel / CLI shows intervention alert
5. **Focus:** Click "Open Browser" → Playwright browser window comes to foreground
6. **Solve:** User solves CAPTCHA directly in the browser window
7. **Resume:** User clicks "Done" in VSCode/CLI → research continues
8. **Fallback:** If not solved in 5 minutes, skip vendor

### 7.3 Browser Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `headless` | No visible browser | Normal research, no blockers |
| `headed` | Visible browser window | When intervention needed |

Playwright starts headless by default. When intervention is required, it can either:
- Switch to headed mode (restart browser with state preserved)
- Or run headed from the start if interventions are expected

### 7.4 Intervention Types

| Type | Detection | User Action |
|------|-----------|-------------|
| `captcha_recaptcha` | reCAPTCHA iframe detected | Solve CAPTCHA |
| `captcha_hcaptcha` | hCaptcha iframe detected | Solve CAPTCHA |
| `cloudflare` | Cloudflare challenge page | Wait/solve |
| `login_required` | Login form detected | Log in or skip |
| `age_verification` | Age gate detected | Confirm age |
| `region_blocked` | Region restriction | Use VPN or skip |

---

## 8. Implementation Plan

### Phase 1: CLI Tool (Week 1)

```
app/cli/
├── __init__.py
├── main.py              # Typer CLI entry point
├── commands/
│   ├── chat.py          # Main query command
│   ├── turns.py         # Turn management
│   ├── status.py        # System status
│   └── memory.py        # Memory operations
├── display/
│   ├── progress.py      # Rich progress display
│   ├── response.py      # Response formatting
│   └── tables.py        # Product tables
└── api/
    └── client.py        # Gateway HTTP/WebSocket client
```

**Deliverables:**
- `panda "query"` works end-to-end
- Progress display during research
- Basic intervention handling (terminal prompt)
- Diff preview for coding tasks (no-apply by default)

### Phase 2: VSCode Extension - Basic (Week 2)

```
panda-vscode/
├── package.json
├── src/
│   ├── extension.ts     # Entry point
│   ├── chat/
│   │   ├── ChatPanel.ts
│   │   └── webview/
│   │       ├── index.html
│   │       ├── chat.css
│   │       └── chat.js
│   └── api/
│       └── gateway.ts
└── media/
    └── icon.png
```

**Deliverables:**
- Chat panel opens in VSCode
- Messages send and receive
- Basic response rendering

### Phase 3: VSCode Extension - Full (Week 3)

**Add:**
- Sidebar status panel
- Research progress in chat panel
- Product cards for commerce
- Streaming responses
- Injection buttons
- Diff preview and apply/reject controls for coding tasks

### Phase 4: Intervention + Observability (Week 4)

**Add:**
- Intervention alerts in chat panel
- noVNC integration
- Metrics dashboard webview
- Status bar integration

---

## 9. File Structure

### Extension Package

```
panda-vscode/
├── package.json
├── tsconfig.json
├── webpack.config.js
├── src/
│   ├── extension.ts
│   ├── sidebar/
│   │   ├── StatusProvider.ts
│   │   └── TurnsProvider.ts
│   ├── chat/
│   │   ├── ChatPanel.ts
│   │   └── webview/
│   │       ├── index.html
│   │       ├── styles/
│   │       │   └── chat.css
│   │       └── scripts/
│   │           ├── chat.ts
│   │           ├── progress.ts
│   │           └── intervention.ts
│   ├── metrics/
│   │   ├── MetricsPanel.ts
│   │   └── webview/
│   ├── commands/
│   │   ├── newChat.ts
│   │   ├── showTurn.ts
│   │   ├── cancelResearch.ts
│   │   └── retryLast.ts
│   ├── api/
│   │   ├── gateway.ts
│   │   └── websocket.ts
│   └── utils/
│       ├── markdown.ts
│       └── formatting.ts
├── media/
│   ├── panda-icon.svg
│   └── loading.gif
└── test/
    └── extension.test.ts
```

---

## 10. Related Documents

- `architecture/main-system-patterns/phase*.md` - Pipeline phases
- `architecture/DOCUMENT-IO-SYSTEM/OBSERVABILITY_SYSTEM.md` - Metrics and debugging
- `architecture/mcp-tool-patterns/internet-research-mcp/INTERNET_RESEARCH_ARCHITECTURE.md` - Research system

---

**Last Updated:** 2026-01-25
