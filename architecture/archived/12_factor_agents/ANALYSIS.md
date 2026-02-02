# 12-Factor Agents Analysis

## Source
https://github.com/humanlayer/12-factor-agents

## Overview

12-Factor Agents is a set of design principles for building reliable LLM-powered applications, inspired by the classic [12 Factor Apps](https://12factor.net/) methodology. Created by Dex from HumanLayer, it argues that the fastest path to production-quality AI software is adopting modular concepts rather than committing entirely to frameworks.

**Key Insight**: "The fastest way I've seen for builders to get good AI software in the hands of customers is to take small, modular concepts from agent building, and incorporate them into their existing product."

## The 12 Factors

| # | Factor | Summary |
|---|--------|---------|
| 1 | Natural Language to Tool Calls | Convert user intent into structured function calls |
| 2 | Own Your Prompts | Direct control over prompt engineering, not framework defaults |
| 3 | Own Your Context Window | Deliberately architect what information the LLM receives |
| 4 | Tools Are Structured Outputs | Treat tools as schemas, not special framework constructs |
| 5 | Unify Execution and Business State | One source of truth - infer execution state from context |
| 6 | Launch/Pause/Resume | Simple APIs for agent lifecycle management |
| 7 | Contact Humans with Tool Calls | Use same mechanism to route work to humans |
| 8 | Own Your Control Flow | Explicit decision logic, not framework-determined paths |
| 9 | Compact Errors into Context | Distill failures into concise LLM-processable messages |
| 10 | Small, Focused Agents | Specialized agents for narrow problems |
| 11 | Trigger from Anywhere | Enable invocation from webhooks, crons, user actions |
| 12 | Stateless Reducer | Agents as pure functions: input state → output state |

## Comparison to Pandora

### What Pandora Already Does Well

| Factor | Pandora Implementation | Status |
|--------|----------------------|--------|
| **1. NL to Tool Calls** | Phase 3 Planner outputs structured PLANNER_DECISION | ✅ Strong |
| **2. Own Your Prompts** | All prompts in `apps/prompts/`, full control | ✅ Strong |
| **3. Own Your Context Window** | context.md sections §0-§6, custom format | ✅ Strong |
| **4. Tools as Structured Outputs** | MCP tools with JSON schemas | ✅ Strong |
| **8. Own Your Control Flow** | 8-phase pipeline with explicit routing | ✅ Strong |
| **9. Compact Errors** | ValidationResult with structured issues | ✅ Partial |
| **10. Small Focused Agents** | Role-based phases (REFLEX, NERVES, MIND, VOICE) | ✅ Strong |

### Gaps and Opportunities

| Factor | Pandora Gap | Recommendation |
|--------|-------------|----------------|
| **5. Unify State** | Execution state (phase, iteration) separate from context.md | Consider embedding |
| **6. Pause/Resume** | No mid-flow pause between tool selection and execution | Implement intervention points |
| **7. Human Contact as Tool** | CAPTCHA intervention exists but not general-purpose | Generalize pattern |
| **11. Trigger Anywhere** | HTTP only, no webhooks/crons | Low priority for current use |
| **12. Stateless Reducer** | UnifiedFlow has instance state | Architectural consideration |

## Detailed Analysis

### Factor 3: Own Your Context Window (Most Relevant)

This is essentially what Pandora's context.md pattern does. The 12-factor approach recommends:

```xml
<slack_message>From: @alex...</slack_message>
<list_git_tags>intent: "list_git_tags"</list_git_tags>
<list_git_tags_result>tags: [...]</list_git_tags_result>
```

**Pandora's approach** (context.md sections):
```markdown
## §0: User Query
What's the cheapest gaming laptop?

## §4: Tool Execution
| Tool | Result |
|------|--------|
| internet.research | Found 5 products... |
```

**Comparison**: Pandora's markdown sections are more human-readable but potentially less token-efficient than XML tags. The 12-factor approach explicitly tracks tool calls and results as separate events, which provides better auditability.

**Recommendation**: Our section-based approach is good. We could improve by:
1. Adding explicit tool call events before results (not just results)
2. Tracking more granular events within §4

### Factor 5: Unify Execution and Business State

The guide recommends inferring execution state from context rather than maintaining separate tracking:

> "You can engineer your application so that you can infer all execution state from the context window."

**Pandora's current approach**:
- `revision_count`, `loop_count` tracked separately in UnifiedFlow
- Phase state tracked in code, not in context.md
- Iteration history stored but not always in context

**Recommendation**: We could embed execution state in context.md:

```markdown
## §meta: Execution State
- Phase: 6 (Validation)
- Iteration: 2
- Previous decisions: [EXECUTE, EXECUTE, COMPLETE, REVISE]
- Error count: 0
```

This would enable:
- Easier debugging (state visible in turn documents)
- Potential for resuming from saved state
- Forking conversations at any point

### Factor 6: Launch/Pause/Resume

The guide emphasizes pausing **between tool selection and execution**:

> "The number one feature request I have for every AI framework is we need to be able to interrupt a working agent and resume later, ESPECIALLY between the moment of tool **selection** and the moment of tool **invocation**."

**Pandora's current approach**:
- CAPTCHA/permission intervention system exists
- But it's reactive (triggered by external event), not proactive (pause before execution)

**Recommendation**: Add an intervention point in PandoraLoop:

```python
async def execute_tool(self, tool_call):
    # NEW: Check if this tool requires approval
    if self.requires_approval(tool_call):
        await self.pause_for_approval(tool_call)
        # Resume when webhook arrives

    result = await self.actually_execute(tool_call)
    return result
```

This would enable:
- Human approval before high-stakes actions
- Rate limiting for expensive tools
- Audit logging before execution

### Factor 7: Contact Humans with Tool Calls

The pattern: treat human interaction as just another tool call.

```python
class RequestHumanInput:
    intent: "request_human_input"
    question: str
    context: str
    options: Options  # urgency, format (yes_no, multiple_choice)
```

**Pandora's current approach**:
- CAPTCHA intervention: reactive, specific to anti-bot
- Permission prompts: exist but ad-hoc

**Recommendation**: Generalize to a `request_human_input` tool that:
1. Can be called by Planner when uncertain
2. Stores state and pauses execution
3. Resumes when human responds via webhook

This aligns with our existing intervention system but makes it proactive and LLM-controlled.

### Factor 9: Compact Errors into Context

The guide recommends:
1. Format errors for LLM consumption (not raw stack traces)
2. Track consecutive error count
3. Escalate to human after N failures

**Pandora's current approach**:
- ValidationResult has `issues` list
- RETRY/REVISE decisions exist
- But error compaction could be improved

**Recommendation**: Add error summarization:

```python
def format_error_for_context(error: Exception, tool_call: dict) -> str:
    """Compact error into LLM-friendly format."""
    return f"""
<error>
  tool: {tool_call['name']}
  type: {type(error).__name__}
  message: {str(error)[:200]}
  suggestion: {self.get_recovery_suggestion(error)}
</error>
"""
```

And track consecutive failures:
```python
if consecutive_errors >= 3:
    # Escalate to human or fail gracefully
    return self.request_human_help(context)
```

## Techniques to Adopt

### Priority 1: Execution State in Context (Low Effort, High Value)

Add a `§meta` section to context.md that tracks:
- Current phase
- Iteration count
- Decision history
- Error count

This makes debugging easier and enables future pause/resume.

### Priority 2: Pre-Execution Approval Points (Medium Effort, High Value)

Add intervention hooks in PandoraLoop before executing tools marked as "high-stakes":
- Money-spending operations
- Data modification
- External API calls with side effects

Use existing CAPTCHA intervention infrastructure but make it general-purpose.

### Priority 3: Error Compaction (Low Effort, Medium Value)

Improve error formatting in tool execution:
- Summarize stack traces
- Add recovery suggestions
- Track consecutive failures
- Escalate gracefully

### Not Recommended for Pandora

1. **Factor 12: Stateless Reducer** - Pandora's phase-based architecture benefits from instance state for efficiency. Full statelessness would add complexity without clear benefit.

2. **Factor 11: Trigger from Anywhere** - Current HTTP-based interface is sufficient. Adding webhook/cron triggers adds complexity for limited use case benefit.

## Summary

12-Factor Agents validates many of Pandora's architectural choices:
- **Context.md sections** = Factor 3 (Own Your Context Window)
- **Phase-based pipeline** = Factor 8 (Own Your Control Flow)
- **Role-based LLM calls** = Factor 10 (Small, Focused Agents)
- **MCP tools** = Factor 4 (Tools as Structured Outputs)

The main gaps are:
1. **Execution state visibility** - embed in context.md for debugging/resumability
2. **Pre-execution approval** - generalize CAPTCHA intervention to any tool
3. **Error compaction** - better formatting of failures for LLM recovery

These are evolutionary improvements, not architectural changes. Pandora's foundation is solid according to these principles.
