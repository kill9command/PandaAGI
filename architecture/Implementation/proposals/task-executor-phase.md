# Task Executor Phase - Implementation Plan

## Problem Statement

The current Planner operates at too high a level - it decides WHAT tools to call but doesn't understand HOW to execute multi-step tasks. This causes issues like:

- Planner calling `internet.research` 5 times instead of transitioning to `skill.generator`
- Planner routing to synthesis when a tool call is actually required
- No understanding of task-specific patterns (research→generate, read→modify→test)

## Proposed Architecture

```
Phase 3: Planner (Strategic)
    ↓ EXECUTE decision with task_type
Phase 4a: Task Executor (Tactical)  ← NEW
    ↓ tool calls with state tracking
Phase 4b: Coordinator (Operational)
    ↓ raw tool execution
Phase 4a: Task Executor (evaluate results)
    ↓ CONTINUE or DONE
Phase 3: Planner (if CONTINUE with new goals)
```

## Task Types

| Task Type | Pattern | Tools Involved |
|-----------|---------|----------------|
| `skill_build` | research → synthesize → generate | internet.research, skill.generator |
| `code_modify` | read → understand → edit → verify | file.read, file.edit, test.run |
| `code_create` | design → write → test | file.write, test.run |
| `research` | search → visit → extract → synthesize | internet.research |
| `memory_op` | query → update | memory.search, memory.save |

## Implementation

### 1. Task Executor Prompt (`apps/prompts/executor/task_executor.md`)

```markdown
# Task Executor

You execute multi-step tasks by following task-specific patterns.

## Input
- §3: Task Plan from Planner (task_type, goals)
- §4: Current tool results (if any)
- Task State: { step, completed_steps, pending_steps }

## Task Patterns

### skill_build
1. CHECK: Is there research context in §4 or §1?
   - NO → CALL internet.research
   - YES → GO TO step 2
2. CALL skill.generator with {name, description, source}
3. VERIFY: skill created successfully?
   - YES → DONE
   - NO → RETRY with adjusted args

### code_modify
1. CALL file.read to understand current code
2. CALL file.edit with changes
3. CALL test.run to verify
4. CHECK: tests pass?
   - YES → DONE
   - NO → ANALYZE errors, GO TO step 2

## Output
{
  "_type": "EXECUTOR_DECISION",
  "action": "CALL_TOOL" | "DONE" | "ESCALATE",
  "tool": { "name": "...", "args": {...} },
  "state": { "step": 2, "completed": ["research"], "pending": ["generate"] },
  "reasoning": "..."
}
```

### 2. Task State Dataclass (`libs/gateway/task_state.py`)

```python
@dataclass
class TaskState:
    """Tracks multi-step task execution."""
    task_type: str  # skill_build, code_modify, etc.
    current_step: int = 1
    max_steps: int = 5
    completed_steps: List[str] = field(default_factory=list)
    pending_steps: List[str] = field(default_factory=list)
    step_results: Dict[str, Any] = field(default_factory=dict)

    def advance(self, step_name: str, result: Any):
        """Mark step complete and advance."""
        self.completed_steps.append(step_name)
        self.step_results[step_name] = result
        if step_name in self.pending_steps:
            self.pending_steps.remove(step_name)
        self.current_step += 1

    def is_complete(self) -> bool:
        """Check if all required steps done."""
        return len(self.pending_steps) == 0
```

### 3. Executor Integration in UnifiedFlow

```python
# In _phase3_4_planning_loop():

async def _phase4a_task_executor(
    self,
    context_doc: ContextDocument,
    task_plan: Dict[str, Any],
    task_state: TaskState
) -> Tuple[str, Dict[str, Any]]:
    """
    Phase 4a: Task Executor - tactical execution of multi-step tasks.

    Returns:
        Tuple of (action, tool_spec) where action is CALL_TOOL, DONE, or ESCALATE
    """
    # Load executor prompt
    recipe = load_recipe("task_executor")

    # Build context with task state
    executor_context = {
        "task_plan": task_plan,
        "task_state": asdict(task_state),
        "section_4": context_doc.get_section(4) or ""
    }

    # Call executor LLM
    pack = await self.doc_pack_builder.build_async(recipe, turn_dir)
    response = await self.llm_client.call(
        prompt=pack.as_prompt(),
        role="executor",
        max_tokens=500,
        temperature=0.3  # Low temp for deterministic execution
    )

    decision = self._parse_executor_decision(response)
    return decision["action"], decision.get("tool")
```

### 4. Modified Planning Loop

```python
async def _phase3_4_planning_loop(self, ...):
    task_state = None

    while iteration < MAX_ITERATIONS:
        # Phase 3: Planner (strategic)
        planner_decision = await self._call_planner(...)

        if planner_decision["action"] == "COMPLETE":
            break

        if planner_decision["action"] == "EXECUTE":
            task_type = planner_decision.get("task_type", "generic")

            # Initialize task state if new task
            if task_state is None or task_state.task_type != task_type:
                task_state = TaskState(
                    task_type=task_type,
                    pending_steps=self._get_task_steps(task_type)
                )

            # Phase 4a: Task Executor (tactical)
            while not task_state.is_complete():
                action, tool_spec = await self._phase4a_task_executor(
                    context_doc, planner_decision, task_state
                )

                if action == "CALL_TOOL":
                    # Phase 4b: Coordinator (operational)
                    result = await self._execute_single_tool(
                        tool_spec["name"],
                        tool_spec["args"],
                        context_doc
                    )
                    task_state.advance(tool_spec["name"], result)

                elif action == "DONE":
                    break

                elif action == "ESCALATE":
                    # Return to Planner with issue
                    break

            # Update §4 with results
            self._update_section4(context_doc, task_state)
```

### 5. Recipe Configuration (`apps/recipes/recipes/task_executor.yaml`)

```yaml
name: task_executor
role: executor
phase: execution

prompt_fragments:
  - "apps/prompts/executor/task_executor.md (800 tokens)"

input_docs:
  - path: "context.md"
    optional: false
    max_tokens: 1500
    path_type: "turn"

token_budget:
  total: 3500
  prompt: 800
  input_docs: 1500
  output: 500
  buffer: 700

description: |
  Task Executor handles tactical execution of multi-step tasks.
  Follows task-specific patterns (skill_build, code_modify, etc.)
  Returns tool calls one at a time with state tracking.
```

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `apps/prompts/executor/task_executor.md` | CREATE | Executor prompt with task patterns |
| `libs/gateway/task_state.py` | CREATE | TaskState dataclass |
| `apps/recipes/recipes/task_executor.yaml` | CREATE | Executor recipe |
| `libs/gateway/unified_flow.py` | MODIFY | Add _phase4a_task_executor, modify planning loop |
| `architecture/main-system-patterns/phase4-coordinator.md` | MODIFY | Document new Phase 4a |

## Benefits

1. **Separation of Concerns**
   - Planner: WHAT to do (strategic)
   - Executor: HOW to do it (tactical)
   - Coordinator: DO it (operational)

2. **Task-Specific Intelligence**
   - Each task type has its own execution pattern
   - Executor knows when to transition between steps
   - No more "5 research calls without generating skill"

3. **State Tracking**
   - Clear visibility into task progress
   - Can resume interrupted tasks
   - Better debugging/logging

4. **Extensibility**
   - Add new task types by adding patterns to prompt
   - No code changes for new task patterns

## Migration Path

1. **Phase 1**: Implement for `skill_build` task type only
2. **Phase 2**: Add `code_modify` and `code_create`
3. **Phase 3**: Generalize to all task types
4. **Phase 4**: Remove task-specific hacks from Planner prompt

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Extra LLM call per step | Use small/fast model, cache patterns |
| Complexity increase | Clear separation makes debugging easier |
| State management bugs | Comprehensive TaskState tests |

## Success Criteria

- [ ] `skill_build` tasks complete in ≤3 executor iterations
- [ ] No more "research loop without generator" failures
- [ ] Task state visible in context.md for debugging
- [ ] Planner prompt can be simplified (remove task-specific rules)
