# Svelte IDE Workspace Implementation Plan

## Overview

Implement a 3-panel IDE-style workspace for Code Mode in the Svelte UI, matching the functionality of the vanilla JS implementation in `static/index.html` + `static/app_v2.js`.

## Current State

**Vanilla JS (fully functional):**
- 3-panel layout: File Tree (20%) | Editor (50%) | Task Tracker (30%)
- jsTree for file browsing
- Monaco Editor with tab management
- Task tracker with clickable file anchors
- Terminal panel (collapsible)
- Mode switching (chat ↔ code)

**Svelte UI (missing IDE):**
- Has: Mode switching, profile management, chat, thinking panel
- Missing: All IDE components

---

## Architecture

### New Components to Create

```
src/lib/components/ide/
├── IDEWorkspace.svelte      # Main 3-panel container
├── FileTree.svelte          # Left panel - project file browser
├── Editor.svelte            # Center panel - Monaco editor + tabs
├── EditorTabs.svelte        # Tab bar for open files
├── TaskTracker.svelte       # Right panel - task progress
├── Terminal.svelte          # Bottom panel - bash output (collapsible)
└── index.ts                 # Re-exports
```

### New Stores to Create

```
src/lib/stores/
├── editor.ts                # Editor state (current file, tabs, models)
├── tasks.ts                 # Code tasks from LLM responses
└── terminal.ts              # Terminal output lines
```

---

## Implementation Phases

### Phase 1: Layout Foundation

**Goal:** Create the 3-panel layout that shows when mode = 'code'

**Files to create:**
1. `src/lib/components/ide/IDEWorkspace.svelte`
   - Horizontal flex container
   - Three resizable panels (20% | 50% | 30%)
   - Imports placeholder components

**Files to modify:**
1. `src/routes/+page.svelte`
   - Conditionally render IDEWorkspace when `$mode === 'code'`
   - Keep Chat component for chat mode

**Acceptance criteria:**
- [ ] Mode toggle switches between Chat and IDE layouts
- [ ] Three panels visible with correct proportions
- [ ] Panels have headers ("FILES", "EDITOR", "TASKS")

---

### Phase 2: File Tree

**Goal:** Browse project files and click to open

**Files to create:**
1. `src/lib/components/ide/FileTree.svelte`
   - Fetch from `/ui/filetree?repo={$repoRoot}`
   - Recursive tree rendering (folders expandable)
   - File icons vs folder icons
   - Click file → dispatch event

**Dependencies to evaluate:**
- Option A: `svelte-tree-view` (Svelte-native)
- Option B: Custom recursive `<TreeNode>` component
- Option C: jsTree via dynamic import (jQuery dependency)

**Recommendation:** Start with Option B (custom) for simplicity, no external deps

**Store updates:**
- `editor.ts`: Add `selectFile(path)` action

**Acceptance criteria:**
- [ ] Tree loads from server when repo is set
- [ ] Folders expand/collapse
- [ ] Clicking file triggers editor load
- [ ] Refresh button reloads tree

---

### Phase 3: Monaco Editor

**Goal:** View and edit code files with syntax highlighting

**Files to create:**
1. `src/lib/stores/editor.ts`
   ```typescript
   interface EditorState {
     currentFile: string | null;
     openTabs: string[];
     viewStates: Map<string, any>;  // Monaco view states per file
     isDirty: Map<string, boolean>; // Unsaved changes
   }
   ```

2. `src/lib/components/ide/Editor.svelte`
   - Load Monaco from CDN or npm package
   - Create editor instance on mount
   - Load file content via `/tool/execute` (file.read)
   - Detect language from extension
   - Save/restore view state per file

3. `src/lib/components/ide/EditorTabs.svelte`
   - Tab bar above editor
   - Active tab highlighted
   - Close button per tab
   - Click tab → switch file

**Dependencies:**
- `monaco-editor` npm package or CDN load
- Consider: `@monaco-editor/loader` for easier integration

**Acceptance criteria:**
- [ ] Monaco editor renders in center panel
- [ ] Clicking file in tree loads content
- [ ] Syntax highlighting works (JS, TS, Python, etc.)
- [ ] Multiple tabs can be open
- [ ] Switching tabs preserves scroll/cursor position
- [ ] Close tab removes it from list

---

### Phase 4: Task Tracker

**Goal:** Show code operation progress with clickable file links

**Files to create:**
1. `src/lib/stores/tasks.ts`
   ```typescript
   interface CodeTask {
     id: string;
     description: string;
     status: 'pending' | 'in_progress' | 'completed';
     tool?: string;
     files?: string[];  // e.g., ['/path/file.js:42']
     duration_ms?: number;
   }
   ```

2. `src/lib/components/ide/TaskTracker.svelte`
   - Progress bar (completed / total)
   - Task cards with status icons
   - File anchors → click to open in editor at line
   - Duration display

**Integration:**
- Parse task breakdown from LLM responses (coordinator phase)
- Update store when tool calls complete

**Acceptance criteria:**
- [ ] Tasks display with status icons
- [ ] Progress bar shows completion percentage
- [ ] Clicking file:line opens file and scrolls to line
- [ ] Duration shows in human-readable format

---

### Phase 5: Terminal Panel

**Goal:** Show bash command output

**Files to create:**
1. `src/lib/stores/terminal.ts`
   ```typescript
   interface TerminalLine {
     text: string;
     type: 'stdout' | 'stderr' | 'info';
     timestamp: number;
   }
   ```

2. `src/lib/components/ide/Terminal.svelte`
   - Collapsible bottom panel
   - Monospace font, dark background
   - Color-coded by type (stdout=white, stderr=red, info=blue)
   - Clear button
   - Auto-scroll to bottom

**Integration:**
- Parse bash tool results from coordinator responses
- Add to terminal store

**Acceptance criteria:**
- [ ] Terminal panel toggles visibility
- [ ] Bash output appears with correct colors
- [ ] Clear button works
- [ ] Auto-scrolls on new output

---

### Phase 6: Polish & Integration

**Goal:** Full feature parity with vanilla JS

**Tasks:**
1. Execution mode selector (interactive/autonomous/full_auto)
2. Read-only toggle based on mode permissions
3. Keyboard shortcuts (Ctrl+S to save, etc.)
4. Panel resize handles (optional - can use CSS resize or library)
5. Persist open tabs to localStorage
6. Error handling for file operations

**Acceptance criteria:**
- [ ] Execution mode affects tool confirmation behavior
- [ ] Editor respects read-only setting
- [ ] State persists across page refresh

---

## Component Hierarchy (Final)

```
+page.svelte
├── <ModeSelector />
├── <ProfileManager />
├── {#if $mode === 'code'}
│   ├── <RepoConfig />
│   └── <IDEWorkspace>
│       ├── <FileTree />           # Left 20%
│       ├── <div class="editor-area">  # Center 50%
│       │   ├── <EditorTabs />
│       │   └── <Editor />
│       ├── <TaskTracker />        # Right 30%
│       └── <Terminal />           # Bottom (collapsible)
│   </IDEWorkspace>
├── {:else}
│   └── <Chat />
├── <ContextStatusBar />
└── <InterventionModal />
```

---

## API Endpoints Used

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/ui/filetree?repo={repo}` | GET | Fetch project file tree |
| `/tool/execute` | POST | Execute file.read, file.write, bash |
| `/v1/thinking/{traceId}` | SSE | Real-time phase updates |
| `/jobs/start` | POST | Start long-running request |
| `/jobs/{id}` | GET | Poll job status |

---

## File Tree Data Format

Server returns jsTree-compatible format:
```json
[
  {
    "id": "1",
    "text": "src",
    "type": "folder",
    "children": [
      {
        "id": "2",
        "text": "app.ts",
        "type": "file",
        "path": "/home/user/project/src/app.ts"
      }
    ]
  }
]
```

---

## Dependencies to Add

```bash
# Monaco editor
npm install monaco-editor @monaco-editor/loader

# Optional: Tree component (if not building custom)
npm install svelte-tree-view
```

---

## Estimated Effort

| Phase | Complexity | Dependencies |
|-------|------------|--------------|
| 1. Layout | Low | None |
| 2. File Tree | Medium | API endpoint |
| 3. Monaco Editor | High | monaco-editor package |
| 4. Task Tracker | Medium | Response parsing |
| 5. Terminal | Low | Response parsing |
| 6. Polish | Medium | All above |

**Recommended order:** 1 → 2 → 3 → 4 → 5 → 6

---

## Reference Files

**Vanilla JS (copy logic from):**
- `static/app_v2.js` lines 2351-2531 (Monaco editor)
- `static/app_v2.js` lines 2573-2668 (File tree)
- `static/app_v2.js` lines 2671-2838 (Task tracker)
- `static/app_v2.js` lines 2841-2932 (Terminal)
- `static/index.html` lines 121-154 (HTML structure)

**Svelte UI (extend from):**
- `src/routes/+page.svelte` (add IDE conditional)
- `src/lib/stores/mode.ts` (mode store exists)
- `src/lib/api/client.ts` (API patterns)
