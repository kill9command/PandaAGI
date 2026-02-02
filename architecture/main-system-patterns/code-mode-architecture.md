# Code Mode Architecture

**Version:** 2.1
**Created:** 2026-01-04
**Updated:** 2026-01-06
**Architecture:** PandaAI v2 (Multirole System)

---

## Core Principle

**Code Mode = Chat Mode + Write Tools**

The 8-phase pipeline is IDENTICAL for both modes. The only differences:
1. Which tools are available (code mode unlocks write operations)
2. Mode-specific prompts at 3 phases (Planner, Coordinator, Synthesizer)
3. Repository scope validation (saved repo vs external)

---

## Model Allocation

Code mode uses the same multirole system as chat mode. All text roles use the shared MIND model (Qwen3-Coder-30B-AWQ) with different temperatures:

| Phase | Role | Temp | Function |
|-------|------|------|----------|
| Phase 0 | REFLEX | 0.3 | Query analysis, intent detection |
| Phase 1 | REFLEX | 0.3 | Reflection gate (PROCEED/CLARIFY) |
| Phase 2 | MIND | 0.5 | Context gathering |
| Phase 3 | MIND | 0.5 | Task planning (mode-specific recipes) |
| Phase 4 | MIND + EYES | 0.5 | Coordination + vision when needed |
| Phase 5 | VOICE | 0.7 | Response synthesis (mode-specific) |
| Phase 6 | MIND | 0.5 | Validation |
| Phase 7 | (None) | - | Save and indexing |

**Model Notes:**
- All text roles use MIND model (Qwen3-Coder-30B-AWQ on vLLM port 8000)
- REFLEX role (temp=0.3) for fast classification/gating in Phases 0 and 1
- MIND role (temp=0.5) for reasoning, planning, and validation
- VOICE role (temp=0.7) for user-facing synthesis
-  swaps with MIND for vision tasks (~60-90s overhead)

See: `architecture/LLM-ROLES/llm-roles-reference.md` for full model specifications.

---

## Pipeline Overview

```
User Query + mode = "chat" | "code"
    |
    v
+------------------------------------------------------------------+
| PHASE 0: Query Analyzer                     [UNIFIED]  [REFLEX]  |
+------------------------------------------------------------------+
    |
    v
+------------------------------------------------------------------+
| PHASE 1: Reflection Gate                    [UNIFIED]  [REFLEX]  |
+------------------------------------------------------------------+
    |
    v (PROCEED)
+------------------------------------------------------------------+
| PHASE 2: Context Gatherer                   [UNIFIED]  [MIND]    |
+------------------------------------------------------------------+
    |
    v
+------------------------------------------------------------------+
| PHASE 3: Planner                       [MODE-SPECIFIC]  [MIND]   |
| chat -> planner_chat.yaml (research, memory, docs)               |
| code -> planner_code.yaml (+ file ops, git, bash, tests)         |
+------------------------------------------------------------------+
    |
    v
+------------------------------------------------------------------+
| PHASE 4: Coordinator                   [MODE-SPECIFIC]  [MIND]   |
| chat -> coordinator_chat.yaml (read-only tools)                  |
| code -> coordinator_code.yaml (+ write tools)                    |
|                                                                  |
| +--------------------------------------------------------------+ |
| | PERMISSION VALIDATION (code mode only)                       | |
| | * Mode gate: Is tool allowed in current mode?                | |
| | * Repo scope: Is path under SAVED_REPO?                      | |
| | * If external: Wait for user approval (180s timeout)         | |
| +--------------------------------------------------------------+ |
|                                                                  |
| Vision sub-tasks (when needed): cold-load      |
+------------------------------------------------------------------+
    |
    v
+------------------------------------------------------------------+
| PHASE 5: Synthesis                     [MODE-SPECIFIC]  [VOICE]  |
| chat -> synthesizer_chat.yaml (conversational)                   |
| code -> synthesizer_code.yaml (file refs, status symbols)        |
+------------------------------------------------------------------+
    |
    v
+------------------------------------------------------------------+
| PHASE 6: Validation                         [UNIFIED]  [MIND]    |
+------------------------------------------------------------------+
    |
    v
+------------------------------------------------------------------+
| PHASE 7: Save                               [UNIFIED]  (No LLM)  |
+------------------------------------------------------------------+
    |
    v
Response to User
```

---

## Mode Selection

### Frontend Toggle

**File:** `static/index.html`
```html
<div id="mode-bar">
  <label><input type="radio" name="mode" value="chat" checked> Chat</label>
  <label><input type="radio" name="mode" value="code"> Code</label>
</div>
```

**File:** `static/app_v2.js`
- Mode persisted to localStorage (`pandora.mode`)
- UI updates visibility of repo input field (code mode shows repo selector)
- Auto-switches to code mode for spreadsheet/BOM requests

### API Flow

1. Frontend includes `mode` in request payload
2. Gateway receives mode in `process_request(mode="chat"|"code")`
3. Mode stored on `context_doc.mode` and `turn_dir.mode`
4. Mode passed through all phases

### Recipe Selection

**File:** `lib/gateway/recipe_loader.py` -> `select_recipe(role, mode)`

**Mode-Specific Recipes** (have `_chat` and `_code` variants):
```
recipes/planner_chat.yaml      recipes/planner_code.yaml
recipes/coordinator_chat.yaml  recipes/coordinator_code.yaml
recipes/synthesizer_chat.yaml  recipes/synthesizer_code.yaml
```

**Unified Recipes** (no mode suffix - same for both modes):
```
recipes/query_analyzer.yaml
recipes/context_gatherer_retrieval.yaml
recipes/context_gatherer_synthesis.yaml
recipes/reflection.yaml
recipes/validator.yaml
recipes/summarizer.yaml
recipes/researcher.yaml
```

**Selection Logic:**
```python
# Mode-specific roles get suffix appended
if role in ["planner", "coordinator", "synthesizer"]:
    recipe_name = f"{role}_{mode}"  # e.g., "planner_code"
else:
    recipe_name = role  # e.g., "validator"
```

### Mode-Specific Prompts

Each mode-specific recipe loads different prompt fragments:

| Recipe | Chat Mode Prompt | Code Mode Prompt |
|--------|------------------|------------------|
| Planner | `apps/prompts/planner/strategic.md` | `apps/prompts/planner/code_strategic.md` |
| Coordinator | `apps/prompts/coordinator/core.md` | `apps/prompts/coordinator/code_operations_enhanced.md` |
| Synthesizer | `apps/prompts/synthesizer/synthesis.md` | `apps/prompts/synthesizer/code_synthesis.md` |

---

## Tool Classification

### Chat Mode Tools (Always Available)

Read-only operations safe in any context:

```
Research & Search:
  internet.research    # Web research
  doc.search           # Search documentation
  code.search          # Search codebase
  wiki.search          # Search wiki

Memory:
  memory.create        # Create memory entries
  memory.query         # Query memory
  memory.update        # Update memory

File Reading:
  file.read            # Read files
  file.glob            # Find files by pattern
  file.grep            # Search file contents
  fs.read              # Read filesystem metadata

Git Reading:
  git.status           # Repository status
  git.diff             # View changes
  git.log              # Commit history

Other:
  repo.describe        # Describe repository
  ocr.read             # OCR image content
  bom.build            # Build bill of materials
  commerce.search_offers
  purchasing.lookup
```

### Code Mode Tools (Code Mode Only)

Write operations that modify files or execute commands:

```
File Writing:
  file.write           # Write file content
  file.create          # Create new files
  file.edit            # Edit existing files
  file.delete          # Delete files
  code.apply_patch     # Apply code patches

Git Writing:
  git.add              # Stage changes
  git.commit           # Create commits
  git.commit_safe      # Safe commit with checks
  git.push             # Push to remote
  git.pull             # Pull from remote
  git.branch           # Manage branches
  git.create_pr        # Create pull requests
  git.reset            # Reset repository state

Execution:
  bash.execute         # Execute shell commands
  bash.kill            # Kill processes
  test.run             # Run tests

Documents:
  docs.write_spreadsheet
```

---

## Full Process Flow: Code Mode Request

### Example Query
```
User sends: "Add error handling to the login function in auth.py"
Mode: code
Session: sess_abc123
```

---

### PHASE 0: Query Analyzer [UNIFIED] [REFLEX]

**Layer:** REFLEX role (MIND model @ temp=0.3)
**File:** `lib/gateway/unified_flow.py` -> `_phase0_query_analyzer()`

**What Happens:**
1. Load recipe: `recipes/query_analyzer.yaml`
2. Resolve references: Expand "this", "that", "it" with prior turn context
3. Classify query type: `specific_content`, `general_question`, `followup`, `new_topic`
4. Detect content references from prior turns

**LLM Output:**
```json
{
  "resolved_query": "Add error handling to the login function in auth.py",
  "was_resolved": false,
  "query_type": "new_topic",
  "content_reference": null,
  "reasoning": "Direct file modification request, no prior context needed"
}
```

**Token Budget:** ~1,500 total

---

### PHASE 1: Reflection Gate [UNIFIED] [REFLEX]

**Layer:** REFLEX role (MIND model @ temp=0.3)
**File:** `lib/gateway/unified_flow.py` -> `_phase1_reflection()`

**What Happens:**
1. Load recipe: `recipes/reflection.yaml`
2. Load prompt: `apps/prompts/reflection/unified.md`
3. LLM Call: Analyze query clarity (before context gathering)
4. Decision: PROCEED or CLARIFY

**Why Reflection Runs First:**
Reflection acts as a fast gate before expensive context gathering. If the query is ambiguous, we ask for clarification immediately rather than wasting ~10,500 tokens on context gathering.

**Token Budget:** ~1,500 total

---

### PHASE 2: Context Gatherer [UNIFIED] [MIND]

**Layer:** MIND role (MIND model @ temp=0.5)
**File:** `lib/gateway/unified_flow.py` -> `_phase2_context_gatherer()`

**Entry Point:**
```python
context_doc = ContextDocument(
    turn_number=turn_number,
    session_id=session_id,
    query=clean_query
)
context_doc.mode = mode  # <- Store "code" on context_doc

# Phase 1 Reflection already ran and decided PROCEED
context_doc = await self._phase2_context_gatherer(context_doc)
```

**What Happens:**
1. Load recipes: `context_gatherer_retrieval.yaml` + `context_gatherer_synthesis.yaml`
2. Search prior turns: Query turn index for relevant prior conversations
3. Load turn contexts: Read `context.md` files from matching turns
4. Build section 2: Compile gathered context into context.md section 2

**Output:** `context.md` with:
```markdown
# Section 0: Query
Add error handling to the login function in auth.py

# Section 1: Reflection Decision
**Decision:** PROCEED
**Reasoning:** Query is clear and actionable

# Section 2: Gathered Context
## Prior Context
- Turn 15: User was working on auth module
- Turn 14: Discussed login flow refactoring
## Memory
- User prefers explicit error messages
- Project uses custom exception classes
```

**Token Budget:** ~10,500 total (across 2 LLM calls)

---

### PHASE 3: Planner [MODE-SPECIFIC] [MIND]

**Layer:** MIND role (MIND model @ temp=0.5)
**File:** `lib/gateway/unified_flow.py` -> `_phase3_planner()`

**MODE DIVERGENCE:**
```python
if mode == "code":
    recipe_path = "recipes/planner_code.yaml"
    prompt_path = "apps/prompts/planner/code_strategic.md"
else:
    recipe_path = "recipes/planner_chat.yaml"
    prompt_path = "apps/prompts/planner/strategic.md"
```

**What Happens:**
1. Load recipe: `recipes/planner_code.yaml` (because mode="code")
2. Load prompt: `apps/prompts/planner/code_strategic.md`
3. LLM Call: Create task plan with code operations
4. Route Decision: "coordinator" (needs tools) or "synthesis" (direct answer)

**LLM Plan Output:**
```json
{
  "_type": "PLAN",
  "route": "coordinator",
  "task_plan": [
    {"step": 1, "action": "file.read", "args": {"file_path": "auth.py"}},
    {"step": 2, "action": "file.edit", "args": {"file_path": "auth.py", "changes": "..."}},
    {"step": 3, "action": "test.run", "args": {"test_file": "test_auth.py"}}
  ]
}
```

**Output:**
- `context.md` with section 3 appended
- `ticket.md` with task plan for Coordinator

**Token Budget:** ~5,750 total

**Mode Impact:**
- **Chat mode:** Plans with read-only tools (doc.search, memory.query, internet.research)
- **Code mode:** Plans with write tools (file.edit, git.commit, bash.execute, test.run)

---

### PHASE 4: Coordinator [MODE-SPECIFIC + AGENT LOOP + PERMISSIONS] [MIND + EYES]

**Layer:** MIND role (MIND model @ temp=0.5), with  cold-loaded for vision tasks
**File:** `lib/gateway/unified_flow.py` -> `_phase4_coordinator()`

**Pattern:** Agent Loop (like Claude Code - iterative step-by-step execution)

#### Agent Loop Pattern

```
+-----------------------------------------------------------+
|                     AGENT LOOP                            |
|                                                           |
|  1. Write context.md (with accumulated section 4)         |
|                    |                                      |
|                    v                                      |
|  2. LLM reads context -> outputs AGENT_DECISION           |
|     {action: TOOL_CALL | DONE | BLOCKED}                  |
|                    |                                      |
|                    v                                      |
|  3. Execute tools -> append results to section 4          |
|                    |                                      |
|            Loop until DONE or BLOCKED                     |
+-----------------------------------------------------------+
```

**MODE DIVERGENCE:**
```python
if mode == "code":
    recipe_path = "recipes/coordinator_code.yaml"
    prompt_fragments = [
        "apps/prompts/coordinator/core.md",
        "apps/prompts/coordinator/tools/intent_mapping.md",
        "apps/prompts/coordinator/code_operations_enhanced.md",  # <- Code-specific
        "apps/prompts/coordinator/agent_loop.md"  # <- Agent loop instructions
    ]
else:
    recipe_path = "recipes/coordinator_chat.yaml"
```

**Agent Loop Configuration** (from recipe):
```yaml
agent_loop:
  enabled: true
  max_steps: 10        # Safety limit
  tools_per_step: 3    # Max tools per iteration
output_schema: AGENT_DECISION
```

**What Happens:**
1. Load recipe: `recipes/coordinator_code.yaml`
2. Initialize section 4 in context.md
3. **AGENT LOOP:**
   - Write context.md (LLM sees accumulated results)
   - LLM decides next action: `TOOL_CALL`, `DONE`, or `BLOCKED`
   - If `TOOL_CALL`: Execute tools with **Permission Check**, append to section 4
   - Loop until `DONE`/`BLOCKED` or max_steps reached

#### AGENT_DECISION Output Schema

```json
{
  "action": "TOOL_CALL",
  "tools": [
    {"tool": "file.read", "args": {"file_path": "auth.py"}, "purpose": "Understand code"}
  ],
  "reasoning": "Need to read file first",
  "progress_summary": "Just started",
  "remaining_work": "Read, edit, test"
}
```

Actions:
- **TOOL_CALL**: Execute 1-3 tools for the next step
- **DONE**: Task complete, exit loop
- **BLOCKED**: Cannot proceed, exit loop

#### Vision Tasks (Cold-Load EYES)

When coordination requires vision analysis,  is cold-loaded:
- Screenshot analysis for debugging UI issues
- CAPTCHA detection during web navigation
- UI element identification in automated testing
- Code screenshot OCR

**Token Budget:** ~8,000-12,000 total

#### Permission Validation (Code Mode)

**File:** `lib/gateway/unified_flow.py` -> `_execute_single_tool()`

```python
from lib.gateway.permission_validator import get_validator, PermissionDecision

validator = get_validator()
validation = validator.validate(tool_name, config, mode, session_id)

if validation.decision == PermissionDecision.DENIED:
    return {"tool": tool_name, "status": "denied", "reason": validation.reason}

if validation.decision == PermissionDecision.NEEDS_APPROVAL:
    approved = await validator.wait_for_approval(validation.approval_request_id)
    if not approved:
        return {"tool": tool_name, "status": "approval_denied"}
```

**Permission Flow Examples:**
```
file.read "auth.py"
  -> ALLOWED (always allowed)

file.edit "auth.py"
  -> Tool check: file.edit in CODE_MODE_TOOLS? YES
  -> Repo check: under SAVED_REPO? YES
  -> Result: ALLOWED

file.edit "/other/project/file.py"
  -> Repo check: under SAVED_REPO? NO
  -> Result: NEEDS_APPROVAL -> Wait for UI response
```

#### Tool Execution

```python
orch_url = os.environ.get("ORCH_URL", "http://127.0.0.1:8090")
tool_endpoint = f"{orch_url}/{tool_name}"

async with httpx.AsyncClient(timeout=timeout) as client:
    response = await client.post(tool_endpoint, json=tool_request)
    tool_result = response.json()
```

**Orchestrator Endpoints** (`apps/orchestrator/app.py`):

| Endpoint | Description |
|----------|-------------|
| `/file.read` | Read file contents |
| `/file.edit` | Edit file with diff |
| `/file.write` | Write entire file |
| `/git.commit` | Create git commit |
| `/bash.execute` | Run shell command |
| `/test.run` | Run test suite |

**Output:** `context.md` section 4 (accumulated step-by-step):
```markdown
## Section 4: Tool Execution

## Execution Log (3 steps)

### Step 1
**Action:** Read file to understand implementation
**Tools:** `file.read`: auth.py (success)

### Step 2
**Action:** Add error handling
**Tools:** `file.edit`: auth.py (success)

### Step 3
**Action:** Verify with tests
**Tools:** `test.run`: test_auth.py (PASSED 5/5)

### Step 4: Complete
**Decision:** DONE
**Reasoning:** Error handling added and tests pass
```

#### Benefits of Agent Loop

1. **Reactive**: Adjusts approach based on tool results
2. **Graceful Failures**: LLM sees errors and decides how to respond
3. **Efficient**: Only executes what's needed
4. **Testable**: Can run tests after edits to verify changes

---

### PHASE 5: Synthesis [MODE-SPECIFIC] [VOICE]

**Layer:** VOICE role (MIND model @ temp=0.7)
**File:** `lib/gateway/unified_flow.py` -> `_phase5_synthesis()`

**MODE DIVERGENCE:**
```python
if mode == "code":
    recipe_path = "recipes/synthesizer_code.yaml"
    prompt_path = "apps/prompts/synthesizer/code_synthesis.md"
else:
    recipe_path = "recipes/synthesizer_chat.yaml"
    prompt_path = "apps/prompts/synthesizer/synthesis.md"
```

**What Happens:**
1. Load recipe: `recipes/synthesizer_code.yaml`
2. Load prompt: `apps/prompts/synthesizer/code_synthesis.md`
3. LLM Call: Generate user response from accumulated context
4. Format: Code-specific formatting (file refs, status symbols)

**Output:**
```markdown
[OK] Added error handling to auth.py

**Changes made:**
- `auth.py:45-67` - Wrapped login logic in try/except
- Added custom `AuthenticationError` exception handling
- Added logging for failed attempts

**Tests:** All 5 tests passing

**Files modified:**
- auth.py (login function)
```

**Token Budget:** ~10,000 total

**Mode Impact:**
- **Chat mode:** Conversational response, natural language
- **Code mode:** Structured with file references, line numbers, status indicators

---

### PHASE 6: Validation [UNIFIED] [MIND]

**Layer:** MIND role (MIND model @ temp=0.5)
**File:** `lib/gateway/unified_flow.py` -> `_phase6_validation()`

**What Happens:**
1. Load recipe: `recipes/validator.yaml` (unified for both modes)
2. LLM Call: Check response quality
3. Decision: APPROVE, REVISE, RETRY, FAIL

**Validation Checks:**
- Does response address the query?
- Are all planned actions completed?
- Are there any errors or warnings?
- Is the response format appropriate?

**Decision Options:**
| Decision | Confidence | Action |
|----------|------------|--------|
| **APPROVE** | >= 0.8 | Send to user, proceed to Save |
| **REVISE** | 0.5-0.8 | Loop to Synthesis with hints (max 2) |
| **RETRY** | < 0.5 | Loop to Planner with fixes (max 1) |
| **FAIL** | Unrecoverable | Send error to user |

**Token Budget:** ~6,000 total

---

### PHASE 7: Save [UNIFIED] (No LLM)

**Layer:** None (procedural, no LLM)
**File:** `lib/gateway/unified_flow.py` -> `_phase7_save()`

**What Happens:**
1. Save context.md: Full document to turn directory
2. Index turn: Add to turn index database
3. Extract lessons: Self-learning from successful/failed patterns
4. Update memory: Store relevant facts for future queries

**Storage Locations:**
```
turns/
  turn_000016/
    context.md      # Full accumulated document
    ticket.md       # Task plan
    toolresults.md  # Tool execution details
    response.md     # Final response
    metadata.json   # Turn metadata
turn_index.db       # SQLite index (has session_id column for filtering)
memory/
  preferences.json  # User preferences (keyed by session_id)
  facts.json        # User facts (keyed by session_id)
```

---

## Summary: Mode Impact by Phase

| Phase | Name | Model | Chat Mode | Code Mode | Divergence Type |
|-------|------|-------|-----------|-----------|-----------------|
| 0 | Query Analyzer | REFLEX | Unified | Unified | None |
| 1 | Reflection | REFLEX | Unified | Unified | None |
| 2 | Context Gatherer | MIND | Unified | Unified | None |
| **3** | **Planner** | MIND | `planner_chat.yaml` | `planner_code.yaml` | **Recipe** |
| **4** | **Coordinator** | MIND (+EYES) | `coordinator_chat.yaml` | `coordinator_code.yaml` | **Recipe + Permissions** |
| **5** | **Synthesis** | VOICE | `synthesizer_chat.yaml` | `synthesizer_code.yaml` | **Recipe** |
| 6 | Validation | MIND | Unified | Unified | None |
| 7 | Save | (None) | Unified | Unified | None |

---

## Repository Scope & Permissions

### Saved Repository

The **saved repository** is configured via environment variable:

```bash
SAVED_REPO=/path/to/your/project
```

Operations within this directory are automatically allowed in code mode.

### External Repositories

Any path outside the saved repository requires explicit user approval through an interactive prompt.

### Scope Validation Flow

```
Tool Request (file.write, git.commit, bash.execute, etc.)
    |
    v
+-------------------------------------------+
|  Is mode = "code" or "continue"?          |
|  NO  -> DENIED (mode gate failure)        |
|  YES -> Continue                          |
+-------------------------------------------+
    |
    v
+-------------------------------------------+
|  Is path under SAVED_REPO?                |
|  YES -> ALLOWED (auto-approved)           |
|  NO  -> NEEDS_APPROVAL (prompt user)      |
+-------------------------------------------+
    |
    v (if NEEDS_APPROVAL)
+-------------------------------------------+
|  Show approval prompt in UI               |
|  Wait for user response (180s timeout)    |
|  APPROVED -> Continue with operation      |
|  DENIED/TIMEOUT -> Reject operation       |
+-------------------------------------------+
```

---

## Environment Configuration

```bash
# Primary repository - operations here auto-allowed in code mode
SAVED_REPO=/path/to/your/project

# Enable mode enforcement (default: 1)
ENFORCE_MODE_GATES=1

# Timeout for approval prompts (seconds, default: 180)
EXTERNAL_REPO_TIMEOUT=180
```

---

## Defense-in-Depth: Multi-Layer Mode Enforcement

Mode enforcement happens at multiple layers to prevent accidental or malicious bypass:

### Layer 1: Gateway (Primary Gate)
**File:** `apps/gateway/app.py`
**When:** Request entry
```python
mode = payload.get("mode", "chat")  # Default to safe "chat" mode
```

### Layer 2: Unified Flow
**File:** `lib/gateway/unified_flow.py`
**When:** Throughout pipeline
```python
context_doc.mode = mode  # Stored and passed through all phases
```

### Layer 3: Recipe Selection
**When:** Phases 3, 4, 5
```python
# Phase 4 example
recipe = "coordinator_code.yaml" if mode == "code" else "coordinator_chat.yaml"
```

### Layer 4: Orchestrator Middleware (Defense-in-Depth)
**File:** `apps/orchestrator/app.py:90-124`
**When:** Tool execution
```python
@app.middleware("http")
async def mode_gate_middleware(request, call_next):
    # Check X-Pandora-Mode header for code-only endpoints
    mode = request.headers.get("X-Pandora-Mode", "")
    if is_code_only_endpoint(path) and mode != "code":
        return JSONResponse({"error": "Requires code mode"}, 403)
```

### Code-Only Endpoints Protected
- `/file.write`, `/file.edit`, `/file.create`, `/file.delete`
- `/git.add`, `/git.commit`, `/git.push`, `/git.reset`
- `/bash.execute`, `/bash.kill`
- `/test.run`

### Why Defense-in-Depth?
Even if Gateway is bypassed (e.g., direct API call to Orchestrator), the Orchestrator validates mode independently. A write operation MUST have `X-Pandora-Mode: code` header to succeed.

---

## Implementation Files

| File | Purpose |
|------|---------|
| `lib/gateway/permission_validator.py` | Core validation logic |
| `lib/gateway/unified_flow.py` | 8-phase pipeline orchestration |
| `apps/gateway/app.py` | API endpoints + permission endpoints |
| `apps/orchestrator/app.py` | Tool execution + defense-in-depth middleware |
| `static/permission_prompt.js` | UI for approval prompts |
| `recipes/planner_code.yaml` | Code mode planning recipe |
| `recipes/coordinator_code.yaml` | Code mode coordination recipe |
| `recipes/synthesizer_code.yaml` | Code mode synthesis recipe |
| `apps/prompts/planner/code_strategic.md` | Code planning prompt |
| `apps/prompts/coordinator/code_operations_enhanced.md` | Code operations prompt |
| `apps/prompts/synthesizer/code_synthesis.md` | Code synthesis prompt |

---

## API Endpoints

### Permission Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/permissions/pending` | GET | List pending approval requests |
| `/api/permissions/{id}/resolve` | POST | Approve or deny a request |

### Approval Request Response

When an operation requires approval, the API returns HTTP 202:

```json
{
  "status": "pending_approval",
  "approval_request_id": "uuid-here",
  "reason": "Path '/other/repo' is outside saved repo",
  "details": {
    "tool": "file.write",
    "target_path": "/other/repo/file.txt",
    "saved_repo": "/path/to/your/project"
  }
}
```

---

## Testing

Test script: `scripts/test_permission_system.py`

Test cases:
1. Mode gates: file.write denied in chat mode
2. Mode gates: file.write allowed in code mode
3. Repo scope: Operation in saved repo -> allowed
4. Repo scope: Operation outside saved repo -> needs approval
5. Approval flow: Approve -> operation proceeds
6. Approval flow: Deny -> operation rejected
7. Timeout: No response within 180s -> operation rejected

---

## Related Documents

- `architecture/LLM-ROLES/llm-roles-reference.md` - Full model specifications
- `architecture/main-system-patterns/phase0-query-analyzer.md` - Phase 0 details
- `architecture/main-system-patterns/phase1-reflection.md` - Phase 1 details
- `architecture/main-system-patterns/phase2-context-gathering.md` - Phase 2 details
- `architecture/main-system-patterns/phase3-planner.md` - Phase 3 details
- `architecture/main-system-patterns/phase4-coordinator.md` - Phase 4 details
- `architecture/main-system-patterns/phase5-synthesis.md` - Phase 5 details
- `architecture/main-system-patterns/phase6-validation.md` - Phase 6 details
- `architecture/main-system-patterns/phase7-save.md` - Phase 7 details

---

*Last Updated: 2026-01-04*
