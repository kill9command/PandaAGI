# Implementation Plan: Document-Based IO Fix

**Status:** PLAN
**Created:** 2026-01-25
**Issue:** LLM roles bypass context.md and pass intent/metadata via in-memory variables

---

## Problem Summary

Phase 0 (QueryAnalyzer) stores its output in `self.current_query_analysis` (a Python instance variable). All downstream phases read from this variable instead of context.md §0, violating the document-based IO architecture.

**Impact:**
- Intent/metadata not visible in context.md (no audit trail)
- If pipeline restarts mid-turn, intent is lost
- Downstream LLMs can't see Phase 0's classification
- Hardcoded intent conditionals instead of LLM decisions

---

## Architecture Reference

From `architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md`:

> **§3.2 Section 0: User Query**
> Contains:
> - `original_query`: Raw user input
> - `resolved_query`: Query with references made explicit
> - `query_type`: Classification from Phase 0
> - `content_reference`: Details about referenced prior content

> **§3.10 Context Discipline**
> "Pass the original query (§0) to every LLM that makes decisions."

---

## Implementation Tasks

### Task 1: Extend §0 Format in ContextDocument

**File:** `libs/gateway/context_document.py`

**Current:** §0 only stores raw query string (`self.query`)

**Change:** Store structured QueryAnalysis data in §0

```python
# Add new field to ContextDocument.__init__
self.query_analysis: Optional[Dict[str, Any]] = None  # Full Phase 0 output

# Add method to set §0 with structured data
def set_section_0(self, query_analysis: Dict[str, Any]):
    """
    Set §0 with full query analysis from Phase 0.

    Args:
        query_analysis: Dict containing:
            - original_query: str
            - resolved_query: str
            - query_type: str
            - intent: str
            - intent_metadata: dict
            - content_type: str
            - content_reference: dict or None
            - reasoning: str
    """
    self.query = query_analysis.get("original_query", "")
    self.query_analysis = query_analysis

    # Also set the convenience fields for backward compatibility
    self.research_intent = query_analysis.get("intent", "informational")
    self.research_metadata = query_analysis.get("intent_metadata", {})

# Add helper methods to extract structured data
def get_intent(self) -> str:
    """Get intent from §0."""
    if self.query_analysis:
        return self.query_analysis.get("intent", "informational")
    return "informational"

def get_intent_metadata(self) -> Dict[str, Any]:
    """Get intent metadata from §0."""
    if self.query_analysis:
        return self.query_analysis.get("intent_metadata", {})
    return {}

def get_content_type(self) -> str:
    """Get content type from §0."""
    if self.query_analysis:
        return self.query_analysis.get("content_type", "general")
    return "general"

def get_resolved_query(self) -> str:
    """Get resolved query from §0."""
    if self.query_analysis:
        return self.query_analysis.get("resolved_query", self.query)
    return self.query
```

**Update `to_markdown()` method to include full §0:**

```python
def _format_section_0(self) -> str:
    """Format §0 with full query analysis."""
    if not self.query_analysis:
        # Fallback for legacy
        return f"""## 0. User Query

**Original:** {self.query}
"""

    qa = self.query_analysis
    content = f"""## 0. User Query

**Original:** {qa.get('original_query', self.query)}
**Resolved:** {qa.get('resolved_query', self.query)}
**Query Type:** {qa.get('query_type', 'general_question')}
**Intent:** {qa.get('intent', 'informational')}
"""

    # Add intent metadata if present
    metadata = qa.get('intent_metadata', {})
    if metadata:
        if metadata.get('target_url'):
            content += f"**Target URL:** {metadata['target_url']}\n"
        if metadata.get('site_name'):
            content += f"**Site:** {metadata['site_name']}\n"
        if metadata.get('search_term'):
            content += f"**Search Term:** {metadata['search_term']}\n"
        if metadata.get('goal'):
            content += f"**Goal:** {metadata['goal']}\n"

    content += f"**Content Type:** {qa.get('content_type', 'general')}\n"

    # Add content reference if present
    ref = qa.get('content_reference')
    if ref:
        content += f"""
**Content Reference:**
- Title: {ref.get('title', 'N/A')}
- Type: {ref.get('content_type', 'N/A')}
- Site: {ref.get('site', 'N/A')}
- Source Turn: {ref.get('source_turn', 'N/A')}
"""

    content += f"\n**Reasoning:** {qa.get('reasoning', 'N/A')}\n"

    return content
```

---

### Task 2: Update Phase 0 to Write Full Analysis to §0

**File:** `libs/gateway/unified_flow.py`

**Current (line ~928):**
```python
self.current_query_analysis = query_analysis
```

**Change:** Write to context_doc instead of instance variable

```python
# After query_analyzer.analyze() returns:

# Convert QueryAnalysis dataclass to dict for storage
analysis_dict = {
    "original_query": original_query,
    "resolved_query": query_analysis.resolved_query,
    "query_type": query_analysis.query_type,
    "intent": query_analysis.intent,
    "intent_metadata": query_analysis.intent_metadata or {},
    "content_type": query_analysis.content_type,
    "content_reference": query_analysis.content_reference.to_dict() if query_analysis.content_reference else None,
    "reasoning": query_analysis.reasoning,
    "mode": query_analysis.mode,
}

# Store in context_doc (THE SOURCE OF TRUTH)
context_doc.set_section_0(analysis_dict)

# Remove or deprecate the instance variable
# self.current_query_analysis = query_analysis  # REMOVE THIS
```

---

### Task 3: Update Phase 3 (Planner) to Read from context_doc

**File:** `libs/gateway/unified_flow.py`

**Current (lines 1498-1506):**
```python
if hasattr(self, 'current_query_analysis') and self.current_query_analysis and self.current_query_analysis.intent:
    research_intent = self.current_query_analysis.intent
    research_metadata = self.current_query_analysis.intent_metadata or {}
```

**Change:**
```python
# Read intent from context_doc (set in Phase 0)
research_intent = context_doc.get_intent()
research_metadata = context_doc.get_intent_metadata()
logger.info(f"[UnifiedFlow] Phase 3 using intent from §0: {research_intent}")
```

**Same change needed at lines 1639-1650** (Phase 3-4 loop setup)

---

### Task 4: Update Phase 4 (Executor/Coordinator) to Read from context_doc

**File:** `libs/gateway/unified_flow.py`

**Current (lines 2336-2340):**
```python
content_type = None
if hasattr(self, 'current_query_analysis') and self.current_query_analysis:
    if self.current_query_analysis.intent == "commerce":
        content_type = self.current_query_analysis.content_type
```

**Change:**
```python
# Read from context_doc
content_type = None
if context_doc.get_intent() == "commerce":
    content_type = context_doc.get_content_type()
```

---

### Task 5: Update `_execute_internet_research` to Read from context_doc

**File:** `libs/gateway/unified_flow.py`

**Current (lines 2876-2893):**
```python
query = tool_args.get("query", "")
mode = tool_args.get("mode", "informational")  # WRONG

json={
    "query": query,
    "intent": mode,  # WRONG - uses tool_args
    ...
}
```

**Change:**
```python
query = tool_args.get("query", "")

# Read intent from context_doc (set from Phase 0's QueryAnalysis)
intent = context_doc.get_intent()
intent_metadata = context_doc.get_intent_metadata()

logger.info(f"[UnifiedFlow] internet.research using intent from §0: {intent}")

json={
    "query": query,
    "intent": intent,  # From context_doc
    "intent_metadata": intent_metadata,  # Include target_url, site_name, etc.
    "session_id": context_doc.session_id or "default",
    "human_assist_allowed": True,
}
```

---

### Task 6: Update Phase 5 (Synthesis) to Read from context_doc

**File:** `libs/gateway/unified_flow.py`

**Current (lines 3707-3714):**
```python
content_type = None
if hasattr(self, 'current_query_analysis') and self.current_query_analysis:
    if self.current_query_analysis.intent == "commerce":
        content_type = self.current_query_analysis.content_type
```

**Change:**
```python
# Read from context_doc
content_type = None
if context_doc.get_intent() == "commerce":
    content_type = context_doc.get_content_type()
```

---

### Task 7: Update Phase 7 (Save) to Read from context_doc

**File:** `libs/gateway/unified_flow.py`

**Current (lines 4568-4612):**
```python
if hasattr(self, 'current_query_analysis') and self.current_query_analysis and self.current_query_analysis.intent:
    intent = self.current_query_analysis.intent
    intent_metadata = self.current_query_analysis.intent_metadata or {}
...
if hasattr(self, 'current_query_analysis') and self.current_query_analysis:
    content_ref = self.current_query_analysis.content_reference
```

**Change:**
```python
# Read from context_doc
intent = context_doc.get_intent()
intent_metadata = context_doc.get_intent_metadata()
...
content_ref = context_doc.query_analysis.get("content_reference") if context_doc.query_analysis else None
```

---

### Task 8: Remove `self.current_query_analysis` Instance Variable

**File:** `libs/gateway/unified_flow.py`

After all phases read from context_doc, remove:
1. The assignment `self.current_query_analysis = query_analysis` (line ~928)
2. All `hasattr(self, 'current_query_analysis')` checks

**Search pattern to find all usages:**
```bash
grep -n "current_query_analysis" libs/gateway/unified_flow.py
```

---

### Task 9: Update Orchestrator to Use intent_metadata

**File:** `apps/services/orchestrator/research_role.py`

The Orchestrator receives `intent` and `intent_metadata` from the Gateway. Ensure it uses `intent_metadata.target_url` for navigation intent.

**Check these areas:**
- `_classify_research_intent` should respect incoming intent
- Navigation intent should trigger direct URL visit, not search

---

## Verification Steps

### Step 1: Check §0 Contains Full Analysis
```python
# After Phase 0, context.md should show:
## 0. User Query

**Original:** visit reef2reef.com and find popular threads
**Resolved:** visit reef2reef.com and find popular threads
**Query Type:** navigation
**Intent:** navigation
**Target URL:** https://reef2reef.com
**Goal:** find popular threads
**Content Type:** general
**Reasoning:** User wants to navigate to specific site
```

### Step 2: Check Intent Flows to Research
```bash
# In orchestrator.log, should see:
[ResearchRole] Intent: navigation, metadata: {'target_url': 'https://reef2reef.com', 'goal': 'find popular threads'}
```

### Step 3: Check Direct Navigation (No Search)
```bash
# Should NOT see:
[QueryBuilder] STRUCTURED_JSON success: 'popular threads site:reef2reef.com'

# Should see:
[Phase1] Navigation intent with target_url - skipping query planning
```

---

## File Change Summary

| File | Changes |
|------|---------|
| `libs/gateway/context_document.py` | Add `set_section_0()`, `get_intent()`, `get_intent_metadata()`, `get_content_type()`, update `_format_section_0()` |
| `libs/gateway/unified_flow.py` | Replace all `self.current_query_analysis` reads with `context_doc.get_*()` calls |
| `apps/services/orchestrator/internet_research_mcp.py` | Ensure `intent_metadata` is passed to research_role |
| `apps/services/orchestrator/research_role.py` | Use `intent_metadata.target_url` for navigation |

---

## Migration Notes

1. **Backward Compatibility:** Keep `context_doc.research_intent` and `context_doc.research_metadata` fields populated for any code that reads them directly

2. **Existing Turns:** Old turns without `query_analysis` in §0 will use fallback behavior (return defaults from helper methods)

3. **Testing:** Use query "visit reef2reef.com and find popular threads today" to verify navigation intent flows correctly

---

## Order of Implementation

1. **Task 1** - Add helper methods to ContextDocument (foundation)
2. **Task 2** - Update Phase 0 to write to context_doc
3. **Tasks 3-7** - Update each phase to read from context_doc
4. **Task 5** - Fix `_execute_internet_research` (critical for navigation bug)
5. **Task 8** - Remove `self.current_query_analysis`
6. **Task 9** - Verify Orchestrator uses intent_metadata

---

**Estimated Complexity:** Medium
**Risk:** Low (additive changes with backward compatibility)
**Testing Required:** Navigation queries, commerce queries, informational queries
