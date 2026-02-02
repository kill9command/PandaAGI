# Injection System

**Status:** SPECIFICATION
**Version:** 1.1
**Created:** 2025-12-29
**Updated:** 2026-01-05

---

## Overview

The Injection System allows users to send messages while a turn is processing. This enables:
- **Cancellation**: Stop processing and return partial results
- **Guidance**: Adjust behavior mid-operation (e.g., "focus on X")
- **Redirection**: Change what the system is doing

This works at the **Gateway level**, affecting all phases - not just research.

---

## Core Concept

```
┌─────────────────────────────────────────────────────────────────┐
│                         NORMAL FLOW                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  User Message → New Turn → Process → Response → Done             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      FLOW WITH INJECTION                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  User Message → New Turn → Processing...                         │
│                                 │                                │
│                                 │◄── User sends another message  │
│                                 │    (while turn is active)      │
│                                 │                                │
│                                 ├── Is it "cancel"?              │
│                                 │   └── Yes → Abort, return partial│
│                                 │                                │
│                                 └── No → Inject as guidance      │
│                                         → Adjust behavior        │
│                                         → Continue processing    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Architecture

### Injection Manager

Gateway maintains injection state per session:

```python
class InjectionManager:
    """Manages injections for active turns."""

    def __init__(self):
        self.active_turns: Dict[str, TurnInjectionState] = {}

    def start_turn(self, session_id: str, turn_id: int):
        """Called when a new turn begins processing."""
        self.active_turns[session_id] = TurnInjectionState(
            turn_id=turn_id,
            phase="starting",
            started_at=datetime.now(),
            injections=[],
            cancelled=False
        )

    def end_turn(self, session_id: str):
        """Called when turn completes (success, cancel, or error)."""
        if session_id in self.active_turns:
            del self.active_turns[session_id]

    def inject(self, session_id: str, message: str) -> InjectionResult:
        """Inject a message into an active turn."""
        if session_id not in self.active_turns:
            return InjectionResult(success=False, reason="no_active_turn")

        turn = self.active_turns[session_id]

        if is_cancellation(message):
            turn.cancelled = True
            return InjectionResult(success=True, action="cancelled")
        else:
            turn.injections.append(Injection(
                time=datetime.now(),
                content=message,
                consumed=False
            ))
            return InjectionResult(success=True, action="injected")

    def check(self, session_id: str) -> InjectionCheck:
        """Check for cancellation or pending injections."""
        turn = self.active_turns.get(session_id)
        if not turn:
            return InjectionCheck(cancelled=False, messages=[])

        # Get unconsumed messages
        messages = [i.content for i in turn.injections if not i.consumed]

        # Mark as consumed
        for i in turn.injections:
            i.consumed = True

        return InjectionCheck(
            cancelled=turn.cancelled,
            messages=messages
        )


@dataclass
class TurnInjectionState:
    turn_id: int
    phase: str                    # Current phase for status display
    started_at: datetime
    injections: List[Injection]
    cancelled: bool


@dataclass
class Injection:
    time: datetime
    content: str
    consumed: bool = False
```

### Chat Endpoint Logic

```python
@app.post("/chat")
async def chat(session_id: str, message: str):
    """
    Handle incoming chat message.

    If session has active turn → Injection
    If session has no active turn → New turn
    """
    # Check for active turn
    if injection_manager.has_active_turn(session_id):
        # This message is an injection
        result = injection_manager.inject(session_id, message)

        if result.action == "cancelled":
            return {
                "status": "cancelling",
                "message": "Cancelling current operation..."
            }
        else:
            return {
                "status": "injected",
                "message": "Got it - adjusting..."
            }

    else:
        # No active turn - process as new turn
        injection_manager.start_turn(session_id, generate_turn_id())

        try:
            result = await unified_flow.process(session_id, message)
            return result
        finally:
            injection_manager.end_turn(session_id)
```

---

## Checkpoints

Every phase checks for injections at key points.

### Checkpoint Locations

| Phase | Checkpoint Locations |
|-------|---------------------|
| Phase 0: Query Analyzer | Before classification LLM call |
| Phase 1: Reflection | Before LLM call |
| Phase 2: Context Gatherer | Before LLM call |
| Phase 3: Planner | Before LLM call |
| Phase 4: Coordinator | Before each tool execution |
| Phase 5: Synthesis | Before LLM call |
| Phase 6: Validation | Before LLM call, before URL checks |
| Research (within Phase 4) | Before research Phase 1, after research Phase 1, before each vendor |

### Checkpoint Implementation

```python
class UnifiedFlow:
    def __init__(self, injection_manager: InjectionManager):
        self.injection_manager = injection_manager

    async def checkpoint(self, phase: str) -> CheckpointResult:
        """
        Check for injections. Called at key points in each phase.

        Returns:
            CheckpointResult with action to take
        """
        # Update current phase for status display
        self.injection_manager.update_phase(self.session_id, phase)

        # Check for injections
        check = self.injection_manager.check(self.session_id)

        if check.cancelled:
            return CheckpointResult(
                action="abort",
                reason="user_cancelled"
            )

        if check.messages:
            # Process guidance messages
            adjustments = []
            for msg in check.messages:
                adjustment = self.process_guidance(msg, phase)
                if adjustment:
                    adjustments.append(adjustment)

            return CheckpointResult(
                action="continue",
                adjustments=adjustments
            )

        return CheckpointResult(action="continue")

    def process_guidance(self, message: str, phase: str) -> Optional[Adjustment]:
        """
        Convert user guidance into actionable adjustment.
        """
        message_lower = message.lower()

        # Skip vendor
        if message_lower.startswith("skip "):
            vendor = message[5:].strip()
            return Adjustment(type="skip_vendor", value=vendor)

        # Focus search
        if "focus on" in message_lower:
            focus = message.split("focus on", 1)[1].strip()
            return Adjustment(type="focus_query", value=focus)

        # Add vendor
        if message_lower.startswith("also check "):
            vendor = message[11:].strip()
            return Adjustment(type="add_vendor", value=vendor)

        # Generic guidance - pass to current phase
        return Adjustment(type="guidance", value=message)
```

### Phase-Specific Checkpoint Usage

```python
async def _phase3_planner(self, context_doc: ContextDocument):
    """Phase 3: Planner with injection checkpoint."""

    # CHECKPOINT before planning
    result = await self.checkpoint("planner")
    if result.action == "abort":
        return self.create_abort_response("Cancelled during planning")

    # Apply any adjustments to planning
    for adj in result.adjustments:
        if adj.type == "focus_query":
            context_doc.add_constraint(f"Focus on: {adj.value}")
        elif adj.type == "guidance":
            context_doc.add_user_guidance(adj.value)

    # Continue with planning...
    ticket = await self.call_planner(context_doc)
    return ticket


async def _phase4_coordinator(self, context_doc: ContextDocument, ticket: dict):
    """Phase 4: Coordinator with injection checkpoints."""

    tools = ticket.get("tools", [])
    results = []

    for tool in tools:
        # CHECKPOINT before each tool
        result = await self.checkpoint(f"coordinator:{tool['tool']}")
        if result.action == "abort":
            return self.create_partial_response(results, "Cancelled during execution")

        # Apply adjustments
        for adj in result.adjustments:
            if adj.type == "skip_vendor" and tool["tool"] == "internet.research":
                tool["args"]["skip_vendors"] = tool["args"].get("skip_vendors", [])
                tool["args"]["skip_vendors"].append(adj.value)

        # Execute tool
        tool_result = await self.execute_tool(tool)
        results.append(tool_result)

    return results
```

---

## Cancellation Handling

### What Counts as Cancellation

```python
def is_cancellation(message: str) -> bool:
    """Check if message is a cancellation request."""
    cancellation_phrases = [
        "cancel",
        "stop",
        "nevermind",
        "never mind",
        "abort",
        "forget it",
        "don't worry",
        "actually no",
    ]
    return message.lower().strip() in cancellation_phrases
```

### Abort Response

When cancelled, return what we have:

```python
def create_abort_response(self, results: list, phase: str) -> dict:
    """Create response when user cancels mid-turn."""

    # Determine what we can return
    if phase in ["query_analyzer", "context_gatherer", "reflection", "planner"]:
        # Early phases - nothing useful to return
        return {
            "response": "Cancelled. What would you like to do instead?",
            "status": "cancelled",
            "phase_reached": phase
        }

    elif phase == "coordinator":
        # May have partial results
        if results:
            return {
                "response": self.format_partial_results(results),
                "status": "cancelled_with_partial",
                "phase_reached": phase,
                "partial_results": results
            }
        else:
            return {
                "response": "Cancelled before any results. What would you like to do?",
                "status": "cancelled",
                "phase_reached": phase
            }

    elif phase == "synthesis":
        # Have results, cancelled during response generation
        return {
            "response": self.format_partial_results(results),
            "status": "cancelled_during_synthesis",
            "phase_reached": phase,
            "note": "Results found but response generation was cancelled"
        }
```

---

## Guidance Messages

### Supported Guidance Types

| Pattern | Effect | Applicable Phases |
|---------|--------|-------------------|
| `focus on [X]` | Adjust query/search to prioritize X | Planner, Coordinator, Research |
| `skip [vendor]` | Don't visit this vendor | Coordinator, Research |
| `also check [site]` | Add vendor to search list | Coordinator, Research |
| `ignore [criteria]` | Remove a filter/constraint | Planner, Research |
| `prefer [X]` | Weight results toward X | Planner, Synthesis |
| Free-form text | Passed as guidance to current phase | All |

### Guidance Flow

```
User injects: "focus on RTX 4080"
    │
    ▼
InjectionManager stores message
    │
    ▼
Next checkpoint reads it
    │
    ▼
process_guidance() parses it
    │
    ├── Returns: Adjustment(type="focus_query", value="RTX 4080")
    │
    ▼
Phase applies adjustment
    │
    ├── Planner: Adds to constraints
    ├── Coordinator: Passes to research tool
    └── Research: Modifies search queries
```

---

## UI Integration

### Status Updates

While processing, UI shows current phase:

```
┌─────────────────────────────────────────────────────────────────┐
│  Pandora: [Processing...]                                        │
│           Phase: Researching vendors                             │
│           ├── Visited: newegg.com (3 products)                  │
│           ├── Visiting: bestbuy.com...                          │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ Type a message to adjust or "cancel" to stop            │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### Injection Feedback

When user injects, show acknowledgment:

```
┌─────────────────────────────────────────────────────────────────┐
│  You: focus on ones with good battery life                       │
│                                                                  │
│  Pandora: [Adjusting - focusing on battery life]                │
│           ├── Visiting: amazon.com (filtering for battery)...   │
└─────────────────────────────────────────────────────────────────┘
```

### Cancellation Feedback

```
┌─────────────────────────────────────────────────────────────────┐
│  You: cancel                                                     │
│                                                                  │
│  Pandora: [Stopping...]                                         │
│                                                                  │
│  Pandora: Here's what I found before you cancelled:             │
│           * ASUS ROG Strix - $1,899 (newegg.com)               │
│           * MSI Raider - $2,199 (newegg.com)                   │
│                                                                  │
│           [2 vendors visited, 3 skipped]                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Integration with Research

Research has **additional internal checkpoints** that use the same injection system:

```
Gateway checkpoint (Phase 4 start)
    │
    ▼
Coordinator calls internet.research(injection_manager=self.injection_manager)
    │
    ├── Research checkpoint (before Phase 1 intel)
    │       └── Checks same injection queue
    │
    ├── Research checkpoint (after Phase 1)
    │       └── Checks same injection queue
    │
    ├── Research checkpoint (before vendor 1)
    │       └── Checks same injection queue
    │
    └── ... more granular checkpoints
```

Research receives the `injection_manager` reference and calls `checkpoint()` internally:

```python
class ResearchRole:
    def __init__(self, injection_manager: InjectionManager, session_id: str):
        self.injection_manager = injection_manager
        self.session_id = session_id

    async def checkpoint(self, location: str) -> bool:
        """Returns True if should continue, False if cancelled."""
        check = self.injection_manager.check(self.session_id)

        if check.cancelled:
            return False

        # Apply any guidance
        for msg in check.messages:
            self.apply_guidance(msg)

        return True

    async def research_phase2(self, vendors: list):
        for vendor in vendors:
            if not await self.checkpoint(f"before_vendor:{vendor}"):
                return self.partial_results("user_cancelled")

            # ... extract from vendor
```

---

## Injection During Planning Loop

The Planner-Coordinator Loop (see `phase3-planner.md` and `phase4-coordinator.md`) runs multiple iterations. User injections interact with this loop specially:

### CANCEL During Loop

- Immediately halt current iteration
- Section 4 accumulated so far is PRESERVED
- Skip to Phase 5 (Synthesis) with flag `termination_reason: "user_cancelled"`
- Synthesis generates response from partial Section 4
- Validation skipped, response marked as `partial`

### REDIRECT During Loop

- Complete current tool execution (don't interrupt mid-tool)
- Inject user message into next Planner iteration as priority context
- Planner sees: `[USER INJECTION] {message}` prepended to input
- Planner adjusts strategy based on new direction
- Iteration count does NOT reset (still within max 5)

### ADD_CONTEXT During Loop

- Append to Section 2 as `[USER ADDED] {context}`
- Continue current iteration
- New context available to subsequent iterations

### Preservation Rules

| Injection Type | Section 4 Preserved | Loop Continues | Iteration Reset |
|----------------|---------------------|----------------|-----------------|
| CANCEL         | Yes                 | No             | N/A             |
| REDIRECT       | Yes                 | Yes            | No              |
| ADD_CONTEXT    | Yes                 | Yes            | No              |

### User Visibility

- Frontend shows "Processing... (iteration 2/5)"
- Injection button available throughout
- Cancel confirmation: "Stop and get partial results?"

### Example: Redirect Mid-Planning

```
User query: "Find laptops under $1000"
    │
    ▼
Planning Loop (iteration 1):
    ├── Planner: EXECUTE internet.research for laptops
    ├── Coordinator: Researching...
    │
    │   ◄── User injects: "actually make it gaming laptops"
    │
    ├── Coordinator: Completes current extraction
    └── Appends results to Section 4
    │
    ▼
Planning Loop (iteration 2):
    ├── Planner sees: [USER INJECTION] actually make it gaming laptops
    ├── Planner: EXECUTE internet.research for "gaming laptops"
    └── Adjusts remaining plan accordingly
```

---

## Edge Cases

### Rapid Multiple Injections

User sends multiple messages quickly:

```python
# All get queued
injections = [
    "focus on gaming",
    "skip amazon",
    "also check microcenter"
]

# Next checkpoint processes all at once
check = injection_manager.check(session_id)
# check.messages = ["focus on gaming", "skip amazon", "also check microcenter"]
```

### Injection After Completion

User sends message right as turn completes:

```python
@app.post("/chat")
async def chat(session_id: str, message: str):
    if injection_manager.has_active_turn(session_id):
        # Race condition: turn might complete between check and inject
        result = injection_manager.inject(session_id, message)

        if not result.success and result.reason == "no_active_turn":
            # Turn completed - treat as new turn
            return await process_new_turn(session_id, message)
```

### Cancel During CAPTCHA Wait

If system is waiting for human CAPTCHA resolution:

```python
async def wait_for_captcha(self):
    while not captcha_resolved():
        # Check for cancellation every 5 seconds
        if not await self.checkpoint("captcha_wait"):
            # User cancelled - abort without solving
            return CaptchaResult(resolved=False, reason="user_cancelled")

        await asyncio.sleep(5)
```

---

## Implementation Notes

### Thread Safety

InjectionManager must be thread-safe since:
- Main request handler writes (inject)
- Processing task reads (checkpoint)

Use locks or thread-safe data structures.

### Memory Cleanup

Ensure `end_turn()` is always called:

```python
try:
    injection_manager.start_turn(session_id, turn_id)
    result = await process_turn(...)
except Exception as e:
    logger.error(f"Turn failed: {e}")
    raise
finally:
    injection_manager.end_turn(session_id)  # Always cleanup
```

### Logging

Log all injections for debugging:

```python
def inject(self, session_id: str, message: str):
    logger.info(f"[Injection] session={session_id} message={message[:50]}")
    # ... rest of inject logic
```

---

## Related Documents

- `architecture/LLM-ROLES/llm-roles-reference.md` - Model assignments and phase overview
- `architecture/main-system-patterns/phase3-planner.md` - Planner checkpoint integration
- `architecture/main-system-patterns/phase4-coordinator.md` - Coordinator checkpoint integration
- `architecture/main-system-patterns/PLANNER_COORDINATOR_LOOP.md` - Loop behavior with injections
- `architecture/mcp-tool-patterns/internet-research-mcp/` - Research-specific checkpoints

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-29 | Initial specification |
| 1.1 | 2026-01-05 | Added Related Documents and Changelog sections |

---

**Last Updated:** 2026-01-05
