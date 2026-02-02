# Pandora Loop (Multi-Task Autonomous Loop)

**Status:** SPECIFICATION
**Version:** 1.1
**Created:** 2026-01-23
**Updated:** 2026-01-23
**Layer:** Orchestrator (wraps existing Planner-Coordinator Loop)

---

## 1. Overview

The Pandora Loop is an **outer loop** that wraps the existing Planner-Coordinator Loop to handle complex multi-task requests. It iterates through a task list, executing each task using the standard phase pipeline until all tasks are complete.

**Relationship to Existing Loops:**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PANDORA LOOP (NEW - Outer)                           │
│                         Max iterations: 10 tasks                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  For each TASK in tasks.json:                                                │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │              PLANNER-COORDINATOR LOOP (Existing - Inner)                │ │
│  │              Max iterations: 5 per task                                 │ │
│  ├────────────────────────────────────────────────────────────────────────┤ │
│  │                                                                         │ │
│  │  Phase 3: Planner ──► EXECUTE or COMPLETE                              │ │
│  │      │                                                                  │ │
│  │      ▼                                                                  │ │
│  │  Phase 4: Coordinator ──► Tool execution                               │ │
│  │      │                                                                  │ │
│  │      └── Results → §4 → Loop back to Planner                           │ │
│  │                                                                         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│      │                                                                       │
│      ▼                                                                       │
│  Phase 5: Synthesis ──► Phase 6: Validation                                 │
│      │                                                                       │
│      ├── APPROVE → Mark task PASSED, next task                              │
│      ├── RETRY → Re-run Planner-Coordinator for this task                   │
│      └── FAIL → Mark task FAILED, next task                                 │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Inspired by:** [Ralph](https://github.com/snarktank/ralph) - autonomous AI agent loop pattern

---

## 2. Loop Hierarchy (Updated)

The Pandora Loop adds a new level to the existing hierarchy:

```
Level 0: Pandora Loop (NEW - multi-task)
    └── For each task:
        └── Level 1: Planner-Coordinator Loop (existing - max 5 iterations)
                └── Level 2: Tool Execution Loops (tool-specific)
                        └── internet.research: max 3 passes
                        └── browser.navigate: max 10 page loads
                        └── code.execute: max 3 retries
```

### Loop Ownership

| Loop Level | Owner | Max Iterations | Purpose |
|------------|-------|----------------|---------|
| Level 0: Pandora Loop | Orchestrator | 10 tasks | Multi-task completion |
| Level 1: Planner-Coordinator | Orchestrator | 5 per task | Single task execution |
| Level 2: Tool Internal | MCP Tool | Tool-specific | Tool operation |

---

## 3. When Pandora Loop Activates

The Planner (Phase 3) activates the Pandora Loop when it detects a **multi-task request** that exceeds what the Planner-Coordinator Loop handles (multiple goals within one turn).

### Pandora Loop vs Multi-Goal Handling

| Scenario | Mechanism | Example |
|----------|-----------|---------|
| 2-3 related goals in one turn | Multi-Goal (existing §3) | "Find laptop AND keyboard" |
| Complex feature with 4+ steps | Pandora Loop (new) | "Implement auth with OAuth, password reset, sessions" |
| Sequential dependencies | Pandora Loop (new) | "Create database, then API, then frontend" |
| System-level scope | Pandora Loop (new) | "Build complete checkout flow" |

### Detection Criteria

Pandora Loop activates when Planner detects:

1. **Task count:** >3 distinct implementation steps
2. **Explicit sequencing:** "first... then... finally..."
3. **Scope keywords:** "implement", "build complete", "add full"
4. **Feature complexity:** Would require multiple Planner-Coordinator cycles with context resets

**Key Difference:** Multi-Goal (existing) accumulates all results in one §4. Pandora Loop resets context per task to prevent context overflow.

---

## 4. Task List Format

When Pandora Loop activates, Planner creates `turns/turn_{N}/tasks.json`:

```json
{
  "_type": "PANDORA_LOOP",
  "version": "1.0",
  "created": "2026-01-23T10:00:00Z",
  "original_query": "Implement user authentication with OAuth, password reset, and session management",
  "max_iterations": 10,

  "tasks": [
    {
      "id": "TASK-001",
      "title": "Set up OAuth provider integration",
      "description": "Configure OAuth2 with Google provider, add callback routes, store tokens",
      "acceptance_criteria": [
        "OAuth config in .env.example",
        "Callback route at /auth/callback",
        "Token storage in session",
        "Tests pass"
      ],
      "priority": 1,
      "status": "pending",
      "depends_on": [],
      "notes": ""
    },
    {
      "id": "TASK-002",
      "title": "Implement password reset flow",
      "description": "Email-based password reset with secure tokens",
      "acceptance_criteria": [
        "POST /auth/forgot-password sends email",
        "Reset token expires in 1 hour",
        "POST /auth/reset-password validates token",
        "Tests pass"
      ],
      "priority": 2,
      "status": "pending",
      "depends_on": [],
      "notes": ""
    },
    {
      "id": "TASK-003",
      "title": "Add session management",
      "description": "Session creation, validation, and cleanup",
      "acceptance_criteria": [
        "Sessions stored in database",
        "Auto-expire after 24 hours",
        "Logout clears session",
        "Tests pass"
      ],
      "priority": 3,
      "status": "pending",
      "depends_on": ["TASK-001"],
      "notes": ""
    }
  ],

  "progress": {
    "completed": 0,
    "total": 3,
    "current_iteration": 0
  }
}
```

### Task Status Values

| Status | Meaning |
|--------|---------|
| `pending` | Not yet attempted |
| `in_progress` | Currently being executed |
| `passed` | Validation APPROVED |
| `failed` | Validation FAIL after max retries |
| `blocked` | Waiting on dependency |

---

## 5. Iteration Flow

### 5.1 Pandora Loop Iteration (Outer)

```python
class PandoraLoop:
    """Outer loop that iterates through tasks."""

    async def run(self) -> LoopResult:
        for iteration in range(self.max_iterations):
            # 1. Select next task
            task = self.select_next_task()
            if not task:
                return LoopResult(status="complete", tasks=self.tasks)

            # 2. Mark in progress
            task["status"] = "in_progress"
            self.save_tasks()

            # 3. Execute task using existing pipeline
            result = await self.execute_task(task)

            # 4. Update status based on validation
            if result.validation == "APPROVE":
                task["status"] = "passed"
                await self.save_learnings(task, result)
            else:
                task["status"] = "failed"
                task["notes"] = result.failure_reason

            self.save_tasks()

        return LoopResult(status="max_iterations", tasks=self.tasks)
```

### 5.2 Task Execution (Uses Existing Pipeline)

Each task execution runs the standard Planner-Coordinator Loop:

```python
async def execute_task(self, task: Task) -> TaskResult:
    """Run existing pipeline for one task."""

    # 1. Create fresh context.md with task injected into §0
    context_md = self.create_task_context(task)

    # 2. Run existing Planner-Coordinator Loop
    #    (Phase 3 ↔ Phase 4, max 5 iterations)
    coordinator_result = await self.orchestrator.run_planner_coordinator_loop(
        context_md=context_md,
        max_iterations=5
    )

    # 3. Run Synthesis (Phase 5)
    synthesis_result = await self.orchestrator.run_synthesis(coordinator_result)

    # 4. Run Validation (Phase 6) - this determines pass/fail
    validation_result = await self.orchestrator.run_validation(synthesis_result)

    return TaskResult(
        validation=validation_result.decision,  # APPROVE, RETRY, FAIL
        failure_reason=validation_result.reason if validation_result.decision != "APPROVE" else None,
        learnings=self.extract_learnings(coordinator_result)
    )
```

### 5.3 Context Injection

Each task gets injected into §0 of a fresh context.md:

```markdown
## 0. User Query

**Original Request:** Implement user authentication with OAuth, password reset, and session management

---

**PANDORA LOOP - Task 2 of 3**

| Field | Value |
|-------|-------|
| Task ID | TASK-002 |
| Title | Implement password reset flow |
| Description | Email-based password reset with secure tokens |
| Priority | 2 |
| Dependencies | None |

**Acceptance Criteria:**
1. POST /auth/forgot-password sends email
2. Reset token expires in 1 hour
3. POST /auth/reset-password validates token
4. Tests pass

**Prior Task Learnings:**
- [TASK-001] OAuth uses passport.js with Google strategy
- [TASK-001] Auth routes in apps/auth/routes.py

---

**Intent:** edit
**Mode:** code
```

---

## 6. Task Selection

### 6.1 Selection Algorithm

```python
def select_next_task(self) -> Task | None:
    """Select highest-priority task with satisfied dependencies."""

    # Get completed task IDs
    completed_ids = {t["id"] for t in self.tasks if t["status"] == "passed"}

    # Find eligible tasks
    eligible = []
    for task in self.tasks:
        if task["status"] != "pending":
            continue

        # Check dependencies satisfied
        deps = task.get("depends_on", [])
        if all(dep in completed_ids for dep in deps):
            eligible.append(task)
        else:
            # Mark as blocked if dependencies not met
            task["status"] = "blocked"

    if not eligible:
        return None

    # Return highest priority (lowest number)
    return min(eligible, key=lambda t: t.get("priority", 99))
```

### 6.2 Dependency Handling

Tasks can declare dependencies:

```json
{
  "id": "TASK-003",
  "title": "Add session management",
  "depends_on": ["TASK-001"],  // Must complete OAuth first
  "status": "blocked"          // Auto-set when TASK-001 pending
}
```

When TASK-001 passes, TASK-003 becomes eligible.

---

## 7. Validation as Quality Gate

The existing Validation phase (Phase 6) determines task pass/fail:

| Validation Result | Task Status | Action |
|-------------------|-------------|--------|
| APPROVE | `passed` | Save learnings, next task |
| RETRY (1st) | stays `in_progress` | Re-run Planner-Coordinator |
| RETRY (2nd) | `failed` | Log failure, next task |
| FAIL | `failed` | Log failure, next task |

### Acceptance Criteria Checking

Validation checks acceptance criteria from the task:

```markdown
## 6. Validation

### Task: TASK-002 (Password reset flow)

**Acceptance Criteria Check:**
| Criteria | Status | Evidence |
|----------|--------|----------|
| POST /auth/forgot-password sends email | ✓ | Route added in §4, test passes |
| Reset token expires in 1 hour | ✓ | Token model has expires_at field |
| POST /auth/reset-password validates token | ✓ | Route added, validates in handler |
| Tests pass | ✓ | 4/4 tests pass in §4 |

**Result:** APPROVE
```

---

## 8. Learning Persistence

After each successful task, learnings are saved to obsidian_memory:

```python
async def save_learnings(self, task: Task, result: TaskResult):
    """Save patterns learned during task execution."""

    if not result.learnings:
        return

    await write_memory(
        artifact_type="research",
        topic=f"pandora-loop-learnings-{task['id']}",
        content={
            "summary": f"Patterns learned from: {task['title']}",
            "findings": result.learnings
        },
        tags=["pandora-loop", "code-patterns", task["id"]],
        source="pandora_loop",
        confidence=0.9
    )
```

Learnings are injected into subsequent task contexts (see §0 injection above).

---

## 9. Termination Conditions

| Condition | Result | Action |
|-----------|--------|--------|
| All tasks `passed` | `complete` | Return success summary |
| All remaining tasks `blocked` | `blocked` | Return blocked summary |
| Max iterations reached | `incomplete` | Return partial summary |
| Critical failure | `failed` | Return failure summary |

### Completion Signal

```markdown
## Pandora Loop Complete

**Status:** SUCCESS
**Tasks:** 3/3 passed

| Task | Title | Status |
|------|-------|--------|
| TASK-001 | OAuth integration | ✓ passed |
| TASK-002 | Password reset | ✓ passed |
| TASK-003 | Session management | ✓ passed |

**Learnings Saved:** 3 patterns to obsidian_memory
```

---

## 10. Planner Output Format

When Planner detects a Pandora Loop scenario:

```markdown
## 3. Task Plan

**Decision:** PANDORA_LOOP
**Reasoning:** Complex multi-step feature with 3+ tasks and dependencies

### Task Breakdown

| ID | Title | Priority | Depends On |
|----|-------|----------|------------|
| TASK-001 | OAuth integration | 1 | - |
| TASK-002 | Password reset | 2 | - |
| TASK-003 | Session management | 3 | TASK-001 |

### Acceptance Criteria

**TASK-001:**
- OAuth config in .env.example
- Callback route at /auth/callback
- Tests pass

**TASK-002:**
- Forgot password endpoint works
- Reset token expires correctly
- Tests pass

**TASK-003:**
- Sessions stored in database
- Auto-expire works
- Tests pass

**Route To:** pandora_loop
```

---

## 11. Integration Points

### 11.1 Orchestrator Changes

```python
# In unified_flow.py

async def run_turn(self, query: str, context: dict) -> TurnResult:
    # ... existing phases 0-2 ...

    # Phase 3: Planner
    planner_result = await self.run_planner(context_md)

    # NEW: Check for Pandora Loop activation
    if planner_result.decision == "PANDORA_LOOP":
        loop = PandoraLoop(
            tasks=planner_result.tasks,
            turn_dir=self.turn_dir,
            orchestrator=self
        )
        return await loop.run()

    # Existing: Planner-Coordinator Loop for single tasks
    elif planner_result.decision == "EXECUTE":
        # ... existing coordinator loop ...
```

### 11.2 Files to Create/Modify

| File | Change |
|------|--------|
| `libs/gateway/pandora_loop.py` | **NEW** - PandoraLoop class |
| `libs/gateway/unified_flow.py` | Add Pandora Loop routing |
| `apps/prompts/planner/strategic.md` | Add loop detection section |
| `apps/prompts/planner/code_strategic.md` | Add loop detection section |

---

## 12. Example Execution

```
User: "Implement user authentication with OAuth, password reset, and sessions"

[Phase 0-2: Query analysis, context gathering]

[Phase 3: Planner]
Decision: PANDORA_LOOP
Tasks: 3 identified

[Pandora Loop Starts]

=== Iteration 1: TASK-001 (OAuth) ===
  [Planner-Coordinator Loop - 3 iterations]
    - Read existing auth code
    - Add OAuth routes
    - Run tests
  [Synthesis] → [Validation: APPROVE]
  Status: TASK-001 PASSED
  Learnings saved: "Uses passport.js, routes in apps/auth/"

=== Iteration 2: TASK-002 (Password Reset) ===
  [Planner-Coordinator Loop - 2 iterations]
    - Add reset routes
    - Run tests
  [Synthesis] → [Validation: APPROVE]
  Status: TASK-002 PASSED
  Learnings saved: "Token model uses expires_at field"

=== Iteration 3: TASK-003 (Sessions) ===
  [Planner-Coordinator Loop - 3 iterations]
    - Add session model
    - Add middleware
    - Run tests
  [Synthesis] → [Validation: APPROVE]
  Status: TASK-003 PASSED

[Pandora Loop Complete]
Status: SUCCESS (3/3 tasks passed)
```

---

## 13. Related Documents

- `PLANNER_COORDINATOR_LOOP.md` - Inner loop specification (Phase 3 ↔ Phase 4)
- `phase3-planner.md` - Planner phase specification
- `phase6-validation.md` - Validation as quality gate
- `architecture/services/OBSIDIAN_MEMORY.md` - Learning persistence
- `architecture/references/ralph_loop/README.md` - Ralph pattern reference

---

## 14. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-23 | Initial specification |
| 1.1 | 2026-01-23 | Integrated with PLANNER_COORDINATOR_LOOP.md, clarified loop hierarchy |

---

**Last Updated:** 2026-01-23
