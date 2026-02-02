# Error Handling Architecture

**Status:** SPECIFICATION
**Version:** 1.1
**Created:** 2025-12-29
**Updated:** 2026-01-05
**Mode:** Development (Fail-Fast)

---

## Philosophy: Fail Fast, Fix Fast

**We are in DEVELOPMENT MODE.**

Every error is a bug that needs to be fixed. Silent fallbacks and graceful degradation HIDE bugs and create compounding problems.

**Wrong approach (production mindset):**
> "If the tool fails, fall back to keyword search"
> Result: Silent failures, hidden bugs, bad data, confused debugging

**Correct approach (development mindset):**
> "If the tool fails, STOP and notify human for investigation"
> Result: Every failure is a learning opportunity, bugs get fixed

---

## Core Principle: Human Intervention

When something fails, the system:
1. **Logs the full error context** (for debugging)
2. **Creates an intervention request** (for human review)
3. **STOPS processing** (don't make things worse)
4. **Returns partial results if available** (don't waste what worked)

```
┌─────────────────────────────────────────────────────────────────┐
│                    FAIL-FAST HIERARCHY                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ERROR OCCURS                                                    │
│       │                                                          │
│       ▼                                                          │
│  Log full context (phase, tool, error, stack trace)             │
│       │                                                          │
│       ▼                                                          │
│  Create intervention request                                     │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ {                                                            ││
│  │   "type": "error",                                           ││
│  │   "phase": "coordinator",                                    ││
│  │   "tool": "internet.research",                               ││
│  │   "error": "HTTPStatusError: 403 Forbidden",                 ││
│  │   "context": "Accessing bestbuy.com/product/123",            ││
│  │   "session_id": "abc123",                                    ││
│  │   "turn_id": 1234,                                           ││
│  │   "timestamp": "2026-01-04T10:30:00Z"                        ││
│  │ }                                                            ││
│  └─────────────────────────────────────────────────────────────┘│
│       │                                                          │
│       ▼                                                          │
│  HALT processing for this turn                                   │
│       │                                                          │
│       ▼                                                          │
│  Return error response to user                                   │
│  "I encountered an error and need assistance. A developer       │
│   has been notified. Error: [brief description]"                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Error Categories

### Category A: Halt and Notify (ALL errors during development)

During development, ALL errors halt processing and create intervention requests.

| Error Type | Action | Intervention Type |
|------------|--------|-------------------|
| `httpx.TimeoutException` | HALT | `tool_timeout` |
| `httpx.HTTPStatusError` | HALT | `http_error` |
| `json.JSONDecodeError` | HALT | `parse_error` |
| `LLM call failure` | HALT | `llm_error` |
| `Tool not found` | HALT | `config_error` |
| `Recipe missing` | HALT | `config_error` |
| `Permission denied` | HALT | `permission_error` |
| `Any unexpected Exception` | HALT | `unknown_error` |

### Category B: Continue with Logging (Future Production Mode)

*Reserved for production mode. During development, all errors are Category A.*

---

## Intervention Request System

All errors create intervention requests that are:
1. Written to `shared_state/intervention_queue.json`
2. Displayed in the research monitor UI
3. Logged to `logs/errors/YYYY-MM-DD.jsonl`

```python
@dataclass
class InterventionRequest:
    """Request for human intervention."""
    id: str                      # Unique ID
    type: str                    # error | captcha | permission | schema_failure
    severity: str                # critical | high | medium
    phase: str                   # Which phase failed
    tool: Optional[str]          # Which tool failed (if applicable)
    error_type: str              # Exception class name
    error_message: str           # Exception message
    context: Dict[str, Any]      # Additional context
    session_id: str              # Session this affects
    turn_id: int                 # Turn this affects
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolution: Optional[str] = None  # How it was resolved
```

---

## Phase-Specific Error Handling

### Phase 0: Query Analyzer

```python
async def _phase0_query_analyzer(...):
    try:
        # ... query analysis logic
    except Exception as e:
        logger.exception(f"[Phase0] Query analysis failed: {e}")
        create_intervention_request(
            type="error",
            severity="critical",  # Phase 0 is the entry point
            phase="query_analyzer",
            error_type=type(e).__name__,
            error_message=str(e),
            context={"query": user_query}
        )
        raise QueryAnalyzerError(f"Phase 0 failed: {e}") from e
```

**DO NOT:**
- Fall back to using raw query without analysis
- Skip coreference resolution silently
- Default to any query type without proper analysis

### Phase 1: Reflection

```python
async def _phase1_reflection(...):
    try:
        # ... reflection logic
    except Exception as e:
        logger.exception(f"[Phase1] Reflection failed: {e}")
        create_intervention_request(
            type="error",
            severity="high",
            phase="reflection",
            error_type=type(e).__name__,
            error_message=str(e)
        )
        raise ReflectionError(f"Phase 1 failed: {e}") from e
```

**DO NOT:**
- Default to PROCEED
- Skip reflection and move to context gathering

### Phase 2: Context Gatherer

```python
async def _phase2_context_gatherer(...):
    try:
        # ... context gathering logic
    except Exception as e:
        logger.exception(f"[Phase2] Context gathering failed: {e}")
        create_intervention_request(
            type="error",
            severity="high",
            phase="context_gatherer",
            error_type=type(e).__name__,
            error_message=str(e),
            context={"query": user_query}
        )
        raise ContextGathererError(f"Phase 2 failed: {e}") from e
```

**DO NOT:**
- Fall back to empty context
- Use keyword-based search as fallback
- Silently continue with partial data

### Phase 3: Planner

```python
async def _phase3_planner(...):
    try:
        # ... planning logic
    except Exception as e:
        logger.exception(f"[Phase3] Planning failed: {e}")
        create_intervention_request(
            type="error",
            severity="critical",  # Planner is critical
            phase="planner",
            error_type=type(e).__name__,
            error_message=str(e)
        )
        raise PlannerError(f"Phase 3 failed: {e}") from e
```

**DO NOT:**
- Use keyword-based tool selection as fallback
- Default to any particular tool

### Phase 4: Coordinator

```python
async def _phase4_coordinator(...):
    for tool in tools:
        try:
            result = await execute_tool(tool)
            append_to_section4(result)
        except Exception as e:
            logger.exception(f"[Phase4] Tool {tool['tool']} failed: {e}")
            create_intervention_request(
                type="error",
                severity="high",
                phase="coordinator",
                tool=tool["tool"],
                error_type=type(e).__name__,
                error_message=str(e),
                context={"tool_args": tool.get("args", {})}
            )
            raise CoordinatorError(f"Tool {tool['tool']} failed: {e}") from e
```

**DO NOT:**
- Continue to next tool after failure
- Return partial results without intervention
- Silently skip failed tools

### Phase 5: Synthesis

```python
async def _phase5_synthesis(...):
    try:
        # ... synthesis logic
    except Exception as e:
        logger.exception(f"[Phase5] Synthesis failed: {e}")
        create_intervention_request(
            type="error",
            severity="high",
            phase="synthesis",
            error_type=type(e).__name__,
            error_message=str(e)
        )
        raise SynthesisError(f"Phase 5 failed: {e}") from e
```

**DO NOT:**
- Format raw claims as fallback response
- Return generic "couldn't find" messages

### Phase 6: Validation

```python
async def _phase6_validation(...):
    try:
        # ... validation logic
    except Exception as e:
        logger.exception(f"[Phase6] Validation failed: {e}")
        create_intervention_request(
            type="error",
            severity="medium",  # Validation can be skipped in emergency
            phase="validation",
            error_type=type(e).__name__,
            error_message=str(e)
        )
        raise ValidationError(f"Phase 6 failed: {e}") from e
```

**DO NOT:**
- Default to APPROVE
- Skip validation entirely

### Phase 7: Save

```python
async def _phase7_save(...):
    try:
        # ... save logic
    except Exception as e:
        logger.exception(f"[Phase7] Save failed: {e}")
        create_intervention_request(
            type="error",
            severity="medium",  # Non-fatal but needs investigation
            phase="save",
            error_type=type(e).__name__,
            error_message=str(e)
        )
        # Save failures DON'T halt user response, but create intervention
        # User gets their response, but data may not be persisted
```

---

## Top-Level Error Handler

```python
async def process_request(session_id: str, message: str) -> dict:
    """
    Main request handler with fail-fast error handling.
    """
    try:
        result = await unified_flow.process(session_id, message)
        return result

    except (QueryAnalyzerError, ContextGathererError, ReflectionError,
            PlannerError, CoordinatorError, SynthesisError,
            ValidationError) as e:
        # Phase-level error already logged and intervention created
        return {
            "response": f"I encountered an error during processing. "
                       f"A developer has been notified.\n\n"
                       f"Error: {e}",
            "error": True,
            "error_type": type(e).__name__,
            "phase": getattr(e, 'phase', 'unknown')
        }

    except Exception as e:
        # Unexpected error - definitely needs intervention
        logger.exception(f"[UnifiedFlow] Unexpected error: {e}")
        create_intervention_request(
            type="error",
            severity="critical",
            phase="unknown",
            error_type=type(e).__name__,
            error_message=str(e)
        )
        return {
            "response": f"I encountered an unexpected error. "
                       f"A developer has been notified.\n\n"
                       f"Error: {type(e).__name__}: {e}",
            "error": True,
            "error_type": type(e).__name__
        }
```

---

## Intervention Queue

Interventions are stored in a shared queue for monitoring:

```python
# shared_state/intervention_queue.json
{
    "interventions": [
        {
            "id": "int_20260104_103000_abc123",
            "type": "error",
            "severity": "critical",
            "phase": "coordinator",
            "tool": "internet.research",
            "error_type": "HTTPStatusError",
            "error_message": "403 Forbidden",
            "context": {
                "url": "https://bestbuy.com/product/123",
                "session_id": "session_abc",
                "turn_id": 1234
            },
            "created_at": "2026-01-04T10:30:00Z",
            "resolved_at": null,
            "resolution": null
        }
    ]
}
```

---

## Resolution Workflow

When an intervention is created:

1. **Monitor displays it** - Human sees the error in research monitor UI
2. **Human investigates** - Check logs, reproduce issue, understand root cause
3. **Human fixes** - Update code, config, or environment
4. **Human marks resolved** - Update intervention with resolution notes
5. **Retry if appropriate** - User can retry their query

```python
def resolve_intervention(intervention_id: str, resolution: str):
    """Mark an intervention as resolved."""
    intervention = get_intervention(intervention_id)
    intervention.resolved_at = datetime.now()
    intervention.resolution = resolution
    save_intervention(intervention)

    logger.info(f"Intervention {intervention_id} resolved: {resolution}")
```

---

## Validation Loop Limits

Even with fail-fast, we need limits to prevent infinite loops:

| Mechanism | Limit | On Limit Reached |
|-----------|-------|------------------|
| Planner-Coordinator loop | 5 iterations | Create intervention, HALT |
| RETRY (Validation -> Planner) | 1 | Create intervention, HALT |
| REVISE (Validation -> Synthesis) | 2 | Create intervention, HALT |
| LLM calls per turn | 25 | Create intervention, HALT |

**When limits are reached:**
```python
if iteration >= MAX_ITERATIONS:
    create_intervention_request(
        type="limit_exceeded",
        severity="high",
        phase="planning_loop",
        context={"iterations": iteration, "limit": MAX_ITERATIONS}
    )
    raise LoopLimitError(f"Planning loop exceeded {MAX_ITERATIONS} iterations")
```

---

## Logging Standards

All errors follow consistent logging:

```python
# Full exception with traceback
logger.exception(f"[{component}] Error in {operation}: {e}")

# Structured log for analysis
logger.error(
    f"[{component}] {error_type}",
    extra={
        "component": component,
        "operation": operation,
        "error_type": type(e).__name__,
        "error_message": str(e),
        "session_id": session_id,
        "turn_id": turn_id
    }
)
```

---

## Future: Production Mode

When moving to production, we can introduce graduated error handling:

1. **Recoverable errors** - Retry with backoff, then fallback
2. **Transient errors** - Retry automatically (network timeouts)
3. **Permanent errors** - Fail immediately

But for now: **ALL ERRORS -> HALT + INTERVENTION**

---

## Intervention Queue Backpressure

The intervention queue has limits to prevent unbounded growth:

### Queue Limits

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **Max queue size** | 50 | Beyond this, system health is questionable |
| **Max per session** | 5 | Prevent one broken session from flooding queue |
| **Max per error type** | 10 | Prevent repeated same-error flooding |

### Priority Levels

Interventions are processed by priority (highest first):

| Priority | Type | Examples |
|----------|------|----------|
| **P1 (Critical)** | System health | LLM service down, database corruption |
| **P2 (High)** | User-blocking | CAPTCHA, permission denied, critical failure |
| **P3 (Medium)** | Quality issues | Schema failure, extraction error |
| **P4 (Low)** | Informational | Limit exceeded, validation failure |

### Backpressure Behavior

When queue limits are reached:

```python
def create_intervention_request(intervention: InterventionRequest) -> bool:
    """
    Create an intervention request with backpressure.
    Returns True if accepted, False if rejected.
    """
    queue = load_intervention_queue()

    # Check queue limits
    if len(queue.interventions) >= MAX_QUEUE_SIZE:
        logger.critical(f"INTERVENTION QUEUE FULL ({MAX_QUEUE_SIZE}). Dropping: {intervention.type}")
        # Write to emergency log instead
        write_to_emergency_log(intervention)
        return False

    # Check per-session limit
    session_count = sum(1 for i in queue.interventions
                        if i.session_id == intervention.session_id and not i.resolved_at)
    if session_count >= MAX_PER_SESSION:
        logger.warning(f"Session {intervention.session_id} hit intervention limit ({MAX_PER_SESSION})")
        # Merge with existing intervention of same type
        merge_with_existing(queue, intervention)
        return True

    # Check per-error-type limit
    type_count = sum(1 for i in queue.interventions
                     if i.error_type == intervention.error_type and not i.resolved_at)
    if type_count >= MAX_PER_ERROR_TYPE:
        logger.warning(f"Error type {intervention.error_type} hit limit ({MAX_PER_ERROR_TYPE})")
        # Increment existing intervention count instead
        increment_occurrence_count(queue, intervention.error_type)
        return True

    # Accept the intervention
    queue.interventions.append(intervention)
    save_intervention_queue(queue)
    return True
```

### Queue Health Monitoring

```python
def check_queue_health() -> dict:
    """Check intervention queue health for observability."""
    queue = load_intervention_queue()
    unresolved = [i for i in queue.interventions if not i.resolved_at]

    return {
        "total": len(queue.interventions),
        "unresolved": len(unresolved),
        "by_priority": {
            "critical": len([i for i in unresolved if i.severity == "critical"]),
            "high": len([i for i in unresolved if i.severity == "high"]),
            "medium": len([i for i in unresolved if i.severity == "medium"]),
        },
        "oldest_unresolved_age_hours": calculate_oldest_age(unresolved),
        "queue_health": "healthy" if len(unresolved) < 10 else
                        "warning" if len(unresolved) < 30 else "critical"
    }
```

### Emergency Log

When the queue is full, interventions are written to an emergency log:

```
logs/errors/emergency_YYYY-MM-DD.jsonl
```

This ensures no intervention is completely lost, even under backpressure.

---

## Design Principles (Development Mode)

1. **No silent failures** - Every error creates intervention
2. **No fallbacks** - Fallbacks hide bugs
3. **Full context** - Log everything needed to debug
4. **Human in the loop** - Developer reviews and fixes
5. **Learn from failures** - Each error teaches us something
6. **Fix the root cause** - Don't patch symptoms

---

## Related Documents

- `architecture/LLM-ROLES/llm-roles-reference.md` - LLM layer assignments and phase specifications
- `architecture/main-system-patterns/phase0-query-analyzer.md` - Phase 0 details
- `architecture/main-system-patterns/phase1-reflection.md` - Phase 1 details
- `architecture/main-system-patterns/phase2-context-gathering.md` - Phase 2 details
- `architecture/main-system-patterns/phase3-planner.md` - Phase 3 details
- `architecture/main-system-patterns/phase4-coordinator.md` - Phase 4 details
- `architecture/main-system-patterns/phase5-synthesis.md` - Phase 5 details
- `architecture/main-system-patterns/phase6-validation.md` - Phase 6 details
- `architecture/main-system-patterns/phase7-save.md` - Phase 7 details

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-29 | Initial specification |
| 1.1 | 2026-01-05 | Adapted for PandaAI v2: Added Phase 0, updated phase paths |

---

**Last Updated:** 2026-01-05
