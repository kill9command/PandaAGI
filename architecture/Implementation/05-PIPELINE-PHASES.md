# Phase 7-11: Pipeline Phases Implementation

**Dependencies:** Phases 4-6 (Services)
**Priority:** High
**Estimated Effort:** 4-5 days

---

## Overview

This document covers implementing the 8 pipeline phases:

| Phase | Name | Role | Key Output |
|-------|------|------|------------|
| 0 | Query Analyzer | REFLEX (temp=0.3) | query_analysis.json, §0 |
| 1 | Reflection | REFLEX (temp=0.3) | §1 (PROCEED/CLARIFY) |
| 2 | Context Gatherer | MIND (temp=0.5) | §2 (gathered context) |
| 3 | Planner | MIND (temp=0.5) | §3, ticket.md |
| 4 | Coordinator | MIND (temp=0.5) + EYES | §4, toolresults.md |
| 5 | Synthesis | VOICE (temp=0.7) | §5, response.md |
| 6 | Validation | MIND (temp=0.5) | §6 (APPROVE/REVISE/RETRY/FAIL) |
| 7 | Save | None | Persistence |

**Note:** All text roles use MIND model (Qwen3-Coder-30B-AWQ) with different temperatures. EYES (Qwen3-VL-2B) swaps for vision tasks (~60-90s swap overhead). SERVER (Qwen3-Coder-30B, remote) available for heavy coding tasks.

---

## 1. Phase 0: Query Analyzer

### 1.1 Implementation

```python
# apps/phases/phase0_query_analyzer.py
"""Phase 0: Query Analyzer - Resolves references and classifies queries."""

from typing import Any

from libs.core.models import QueryAnalysis, QueryType, ContentReference
from libs.llm.router import get_model_router, ModelLayer
from libs.llm.recipes import get_recipe_loader
from libs.document_io.context_manager import ContextManager


class QueryAnalyzer:
    """
    Phase 0: Analyze and resolve user queries.

    Role: REFLEX (MIND model @ temp=0.3)

    Uses shared MIND model with low temperature for fast, deterministic classification.

    Responsibilities:
    - Resolve pronouns/references ("the thread" -> specific content)
    - Classify query type (specific_content, general_question, followup)
    - Detect content references to prior turns
    """

    def __init__(self):
        self.router = get_model_router()
        self.recipe_loader = get_recipe_loader()

    async def analyze(
        self,
        query: str,
        recent_turns: list[dict],
        context: ContextManager,
    ) -> QueryAnalysis:
        """
        Analyze user query.

        Args:
            query: Raw user query
            recent_turns: Recent turn summaries for reference resolution
            context: Context manager for this turn

        Returns:
            QueryAnalysis with resolved query and classification
        """
        recipe = self.recipe_loader.load("query_analyzer")

        # Build prompt
        system_prompt = self._build_system_prompt(recipe)
        user_prompt = self._build_user_prompt(query, recent_turns)

        # Call REFLEX
        response = await self.router.complete(
            layer=ModelLayer.REFLEX,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=recipe.temperature,
            max_tokens=recipe.max_tokens,
        )

        # Parse response
        analysis = self._parse_response(query, response.content)

        # Write to context.md §0
        context.write_section_0(analysis)

        return analysis

    def _build_system_prompt(self, recipe) -> str:
        """Build system prompt from recipe."""
        return """You are a query analyzer. Your job is to:
1. Resolve references (pronouns, "the thread", "that product") to specific content
2. Classify the query type
3. Identify any content references to prior turns

Output JSON:
{
  "resolved_query": "the query with references resolved",
  "was_resolved": true/false,
  "query_type": "specific_content|general_question|followup|new_topic",
  "content_reference": {
    "title": "...",
    "content_type": "thread|article|product|...",
    "site": "...",
    "source_turn": 123
  } or null,
  "reasoning": "why you resolved/classified this way"
}"""

    def _build_user_prompt(self, query: str, recent_turns: list[dict]) -> str:
        """Build user prompt with context."""
        turns_text = ""
        for turn in recent_turns:
            turns_text += f"\nTurn {turn['turn_number']}: {turn['topic'] or 'Unknown topic'}"
            turns_text += f"\n  Preview: {turn['query_preview'][:100]}..."

        return f"""Recent turns:
{turns_text}

Current query: {query}

Analyze this query and resolve any references."""

    def _parse_response(self, original_query: str, response: str) -> QueryAnalysis:
        """Parse LLM response into QueryAnalysis."""
        import json

        try:
            # Extract JSON from response
            data = json.loads(response)

            content_ref = None
            if data.get("content_reference"):
                ref = data["content_reference"]
                content_ref = ContentReference(
                    title=ref.get("title", ""),
                    content_type=ref.get("content_type", ""),
                    site=ref.get("site", ""),
                    source_turn=ref.get("source_turn", 0),
                )

            return QueryAnalysis(
                original_query=original_query,
                resolved_query=data.get("resolved_query", original_query),
                was_resolved=data.get("was_resolved", False),
                query_type=QueryType(data.get("query_type", "general_question")),
                content_reference=content_ref,
                reasoning=data.get("reasoning", ""),
            )

        except (json.JSONDecodeError, KeyError, ValueError):
            # Fallback if parsing fails
            return QueryAnalysis(
                original_query=original_query,
                resolved_query=original_query,
                was_resolved=False,
                query_type=QueryType.GENERAL_QUESTION,
                reasoning="Failed to parse LLM response",
            )
```

### 1.2 Recipe

```yaml
# apps/recipes/query_analyzer.yaml
name: query_analyzer
model: reflex

token_budget:
  total: 1500
  prompt: 500
  input: 700
  output: 300

temperature: 0.3
max_tokens: 300

output_schema:
  resolved_query: string
  was_resolved: boolean
  query_type: enum
  content_reference: object|null
  reasoning: string
```

---

## 2. Phase 1: Reflection

### 2.1 Implementation

```python
# apps/phases/phase1_reflection.py
"""Phase 1: Reflection - PROCEED/CLARIFY gate."""

from libs.core.models import ReflectionResult, ReflectionDecision
from libs.llm.router import get_model_router, ModelLayer
from libs.llm.recipes import get_recipe_loader
from libs.document_io.context_manager import ContextManager


class Reflection:
    """
    Phase 1: Decide if query is clear enough to proceed.

    Role: REFLEX (MIND model @ temp=0.3)

    Responsibilities:
    - Binary gate: PROCEED or CLARIFY
    - Fast decision based on query clarity alone
    - Does NOT assess research feasibility (that's Phase 3)
    """

    def __init__(self):
        self.router = get_model_router()
        self.recipe_loader = get_recipe_loader()

    async def reflect(self, context: ContextManager) -> ReflectionResult:
        """
        Decide if we should proceed or ask for clarification.

        Args:
            context: Context manager with §0 populated

        Returns:
            ReflectionResult with PROCEED or CLARIFY decision
        """
        recipe = self.recipe_loader.load("reflection")

        # Read §0
        section_0 = context.read_section(0)

        # Build prompt
        system_prompt = """You are a query clarity checker. Decide:
- PROCEED: Query is clear enough to work on
- CLARIFY: Query is too vague or ambiguous

Be generous - if you can reasonably interpret the query, PROCEED.
Only CLARIFY for truly unclear queries.

Output JSON:
{
  "decision": "PROCEED|CLARIFY",
  "confidence": 0.0-1.0,
  "query_type": "informational|transactional|navigational",
  "is_followup": true/false,
  "reasoning": "why this decision"
}"""

        user_prompt = f"""Evaluate this query for clarity:

{section_0}

Should I PROCEED or CLARIFY?"""

        # Call REFLEX
        response = await self.router.complete(
            layer=ModelLayer.REFLEX,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=recipe.temperature,
            max_tokens=recipe.max_tokens,
        )

        # Parse response
        result = self._parse_response(response.content)

        # Write to §1
        context.write_section_1(result)

        return result

    def _parse_response(self, response: str) -> ReflectionResult:
        """Parse LLM response."""
        import json

        try:
            data = json.loads(response)
            return ReflectionResult(
                decision=ReflectionDecision(data.get("decision", "PROCEED")),
                confidence=float(data.get("confidence", 0.8)),
                query_type=data.get("query_type"),
                is_followup=data.get("is_followup", False),
                reasoning=data.get("reasoning", ""),
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            # Default to PROCEED on parse failure
            return ReflectionResult(
                decision=ReflectionDecision.PROCEED,
                confidence=0.5,
                reasoning="Failed to parse, defaulting to PROCEED",
            )
```

---

## 3. Phase 2: Context Gatherer

### 3.1 Implementation

```python
# apps/phases/phase2_context_gatherer.py
"""Phase 2: Context Gatherer - Retrieves relevant context."""

from typing import Optional

from libs.core.models import GatheredContext, ContextSource
from libs.llm.router import get_model_router, ModelLayer
from libs.llm.recipes import get_recipe_loader
from libs.document_io.context_manager import ContextManager


class ContextGatherer:
    """
    Phase 2: Gather relevant context for the query.

    Role: MIND (MIND model @ temp=0.5)

    Two-phase process:
    1. RETRIEVAL: Identify relevant turns, research, memory
    2. SYNTHESIS: Follow links, extract details, compile §2
    """

    def __init__(self):
        self.router = get_model_router()
        self.recipe_loader = get_recipe_loader()

    async def gather(self, context: ContextManager, session_id: str) -> GatheredContext:
        """
        Gather context for the current query.

        Args:
            context: Context manager with §0-§1
            session_id: User session for preferences/memory

        Returns:
            GatheredContext with relevant information
        """
        # Phase 1: Retrieval
        retrieval = await self._retrieval_phase(context, session_id)

        # Phase 2: Synthesis
        gathered = await self._synthesis_phase(context, retrieval)

        # Write to §2
        context.write_section_2(gathered)

        return gathered

    async def _retrieval_phase(self, context: ContextManager, session_id: str) -> dict:
        """
        Identify what context to gather.

        Returns list of sources to retrieve.
        """
        recipe = self.recipe_loader.load("context_gatherer_retrieval")

        section_0 = context.read_section(0)
        section_1 = context.read_section(1)

        system_prompt = """You identify relevant context sources.

Given a query, determine:
1. Session preferences to load
2. Prior turns that might be relevant
3. Cached research to check
4. Memory items to search

Output JSON:
{
  "load_preferences": ["key1", "key2"],
  "search_turns": {"keywords": [".."], "max_results": 5},
  "check_research": {"topic": "..", "max_age_hours": 24},
  "search_memory": {"query": ".."}
}"""

        user_prompt = f"""Query context:
{section_0}

Reflection:
{section_1}

What context should I gather?"""

        response = await self.router.complete(
            layer=ModelLayer.MIND,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=recipe.temperature,
            max_tokens=recipe.max_tokens,
        )

        import json
        try:
            return json.loads(response.content)
        except json.JSONDecodeError:
            return {"load_preferences": [], "search_turns": {}, "check_research": {}}

    async def _synthesis_phase(self, context: ContextManager, retrieval: dict) -> GatheredContext:
        """
        Synthesize gathered context into §2.

        Follows links, extracts relevant sections, compiles summary.
        """
        recipe = self.recipe_loader.load("context_gatherer_synthesis")

        # TODO: Actually retrieve from indexes and follow links
        # For now, return placeholder

        return GatheredContext(
            session_preferences={},
            relevant_turns=[],
            cached_research=None,
            source_references=[],
            sufficiency_assessment="No prior context found. Will need fresh research.",
        )
```

---

## 4. Phase 3: Planner

### 4.1 Implementation

```python
# apps/phases/phase3_planner.py
"""Phase 3: Planner - Creates task plans."""

from libs.core.models import (
    TaskPlan, PlannerAction, PlannerRoute,
    Goal, GoalStatus, ToolRequest,
)
from libs.llm.router import get_model_router, ModelLayer
from libs.llm.recipes import get_recipe_loader
from libs.document_io.context_manager import ContextManager


class Planner:
    """
    Phase 3: Create task plan.

    Role: MIND (MIND model @ temp=0.5)

    Responsibilities:
    - Analyze §0-§2 and create strategic plan
    - Decide: coordinator (need tools) | synthesis (have answer) | clarify
    - Detect multi-goal queries and break them down
    - Generate ticket.md with tool requests
    """

    def __init__(self, mode: str = "chat"):
        self.mode = mode
        self.router = get_model_router()
        self.recipe_loader = get_recipe_loader()

    async def plan(
        self,
        context: ContextManager,
        attempt: int = 1,
        failure_context: Optional[str] = None,
    ) -> TaskPlan:
        """
        Create task plan.

        Args:
            context: Context manager with §0-§2 (and §4 if retry)
            attempt: Attempt number (for RETRY)
            failure_context: Why previous attempt failed (for RETRY)

        Returns:
            TaskPlan with routing decision and tool requests
        """
        recipe = self.recipe_loader.load(f"planner_{self.mode}")

        # Read context
        sections = context.get_sections(0, 1, 2)
        if attempt > 1:
            sections += "\n\n" + context.read_section(4)  # Prior tool results

        system_prompt = self._build_system_prompt(failure_context)

        user_prompt = f"""Context:
{sections}

Create a task plan. Decide:
- EXECUTE: Need to call tools
- COMPLETE: Have enough information to synthesize answer

If EXECUTE, specify which tools to call."""

        response = await self.router.complete(
            layer=ModelLayer.MIND,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=recipe.temperature,
            max_tokens=recipe.max_tokens,
        )

        plan = self._parse_response(response.content)

        # Write to §3
        context.write_section_3(plan, attempt)

        # Generate ticket.md if executing
        if plan.decision == PlannerAction.EXECUTE and plan.tool_requests:
            self._write_ticket(context.turn_dir, plan)

        return plan

    def _build_system_prompt(self, failure_context: Optional[str]) -> str:
        """Build system prompt."""
        base = """You are a task planner. Analyze the query and context.

Available tools:
- internet.research: Web research for products/information
- memory.search: Search user memories
- memory.create: Store new user fact
- file.read: Read local files (code mode)
- git.status: Check repository status (code mode)

Detect multi-goal queries (e.g., "Find laptop AND recommend keyboard").

Output JSON:
{
  "decision": "EXECUTE|COMPLETE",
  "route": "coordinator|synthesis|clarify",
  "goals": [{"id": "GOAL_1", "description": "..", "status": "pending", "dependencies": []}],
  "current_focus": "What we're working on now",
  "tool_requests": [{"tool": "internet.research", "args": {"query": ".."}}],
  "reasoning": "Why this plan"
}"""

        if failure_context:
            base += f"""

IMPORTANT: Previous attempt failed:
{failure_context}

Adjust your plan accordingly."""

        return base

    def _parse_response(self, response: str) -> TaskPlan:
        """Parse LLM response."""
        import json

        try:
            data = json.loads(response)

            goals = [
                Goal(
                    id=g["id"],
                    description=g["description"],
                    status=GoalStatus(g.get("status", "pending")),
                    dependencies=g.get("dependencies", []),
                )
                for g in data.get("goals", [])
            ]

            tool_requests = [
                ToolRequest(
                    tool=t["tool"],
                    args=t.get("args", {}),
                    goal_id=t.get("goal_id"),
                )
                for t in data.get("tool_requests", [])
            ]

            return TaskPlan(
                decision=PlannerAction(data.get("decision", "COMPLETE")),
                route=PlannerRoute(data["route"]) if data.get("route") else None,
                goals=goals,
                current_focus=data.get("current_focus"),
                tool_requests=tool_requests,
                reasoning=data.get("reasoning", ""),
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            return TaskPlan(
                decision=PlannerAction.COMPLETE,
                route=PlannerRoute.SYNTHESIS,
                reasoning=f"Parse error: {e}",
            )

    def _write_ticket(self, turn_dir, plan: TaskPlan) -> None:
        """Write ticket.md for Coordinator."""
        ticket_path = turn_dir / "ticket.md"

        content = f"""# Task Ticket

## Current Focus
{plan.current_focus or 'Execute tool requests'}

## Tool Requests
"""
        for req in plan.tool_requests:
            content += f"\n### {req.tool}\n"
            content += f"**Args:** {req.args}\n"
            if req.goal_id:
                content += f"**Goal:** {req.goal_id}\n"

        ticket_path.write_text(content)
```

---

## 5. Phase 4: Coordinator

### 5.1 Implementation

```python
# apps/phases/phase4_coordinator.py
"""Phase 4: Coordinator - Executes tools."""

import httpx
from pathlib import Path

from libs.core.config import get_settings
from libs.core.models import ToolExecutionResult, ToolResult, Claim
from libs.document_io.context_manager import ContextManager


class Coordinator:
    """
    Phase 4: Execute tools.

    Role: MIND (MIND model @ temp=0.5) - but mostly just executes

    This is a THIN execution layer. It:
    1. Reads ticket.md from Planner
    2. Calls MCP tools via Orchestrator
    3. Appends results to §4
    4. Returns to Orchestrator for loop decision
    """

    def __init__(self, mode: str = "chat"):
        self.mode = mode
        self.settings = get_settings()
        self._client = httpx.AsyncClient(
            base_url=self.settings.orchestrator.base_url,
            timeout=60.0,
        )

    async def execute(
        self,
        context: ContextManager,
        iteration: int,
    ) -> ToolExecutionResult:
        """
        Execute tools from ticket.md.

        Args:
            context: Context manager
            iteration: Current loop iteration

        Returns:
            ToolExecutionResult with results and claims
        """
        # Read ticket
        ticket_path = context.turn_dir / "ticket.md"
        if not ticket_path.exists():
            return ToolExecutionResult(
                iteration=iteration,
                action="DONE",
                reasoning="No ticket found",
            )

        ticket = ticket_path.read_text()
        tool_requests = self._parse_ticket(ticket)

        # Execute tools
        results = []
        claims = []

        for request in tool_requests:
            result = await self._call_tool(request["tool"], request["args"])
            results.append(result)

            # Extract claims from successful results
            if result.success:
                extracted = self._extract_claims(result.result)
                claims.extend(extracted)

        # Build result
        execution = ToolExecutionResult(
            iteration=iteration,
            action="TOOL_CALL" if results else "DONE",
            reasoning=f"Executed {len(results)} tools",
            tool_results=results,
            claims_extracted=claims,
        )

        # Append to §4
        context.append_section_4(execution)

        # Write detailed results to toolresults.md
        self._write_toolresults(context.turn_dir, execution)

        return execution

    async def _call_tool(self, tool: str, args: dict) -> ToolResult:
        """Call a tool via Orchestrator."""
        # Map tool name to endpoint
        endpoint_map = {
            "internet.research": "/research",
            "memory.search": "/memory/query",
            "memory.create": "/memory/create",
            "file.read": "/file/read",
            "file.glob": "/file/glob",
            "git.status": "/git/status",
        }

        endpoint = endpoint_map.get(tool)
        if not endpoint:
            return ToolResult(
                tool=tool,
                success=False,
                result=None,
                error=f"Unknown tool: {tool}",
            )

        try:
            response = await self._client.post(
                endpoint,
                json=args,
                headers={"X-Pandora-Mode": self.mode},
            )

            if response.status_code == 200:
                return ToolResult(
                    tool=tool,
                    success=True,
                    result=response.json(),
                    confidence=1.0,
                )
            else:
                return ToolResult(
                    tool=tool,
                    success=False,
                    result=None,
                    error=f"HTTP {response.status_code}: {response.text}",
                )

        except Exception as e:
            return ToolResult(
                tool=tool,
                success=False,
                result=None,
                error=str(e),
            )

    def _parse_ticket(self, ticket: str) -> list[dict]:
        """Parse ticket.md into tool requests."""
        requests = []
        # Simple parsing - look for ### headers
        import re

        tool_pattern = r'### (\S+)\n\*\*Args:\*\* ({.*?})'
        for match in re.finditer(tool_pattern, ticket, re.DOTALL):
            tool = match.group(1)
            try:
                import json
                args = json.loads(match.group(2))
                requests.append({"tool": tool, "args": args})
            except json.JSONDecodeError:
                pass

        return requests

    def _extract_claims(self, result: dict) -> list[Claim]:
        """Extract claims from tool result."""
        claims = []
        # TODO: Implement claim extraction based on result type
        return claims

    def _write_toolresults(self, turn_dir: Path, execution: ToolExecutionResult) -> None:
        """Write detailed results to toolresults.md."""
        results_path = turn_dir / "toolresults.md"

        # Append to existing file
        content = f"\n## Iteration {execution.iteration}\n\n"
        for result in execution.tool_results:
            content += f"### {result.tool}\n"
            content += f"**Success:** {result.success}\n"
            if result.success:
                content += f"**Result:** {result.result}\n"
            else:
                content += f"**Error:** {result.error}\n"
            content += "\n"

        with open(results_path, "a") as f:
            f.write(content)
```

---

## 6. Phases 5-7: Synthesis, Validation, Save

### 6.1 Phase 5: Synthesis

```python
# apps/phases/phase5_synthesis.py
"""Phase 5: Synthesis - Generate user response."""

from libs.core.models import SynthesisResult
from libs.llm.router import get_model_router, ModelLayer
from libs.document_io.context_manager import ContextManager


class Synthesis:
    """
    Phase 5: Generate user-facing response.

    Role: VOICE (MIND model @ temp=0.7)

    Uses only evidence from §2 and §4.
    """

    async def synthesize(
        self,
        context: ContextManager,
        attempt: int = 1,
    ) -> SynthesisResult:
        """Generate response from gathered context and tool results."""
        router = get_model_router()

        # Read all context
        full_context = context.get_sections(0, 1, 2, 3, 4)

        # Read toolresults.md for details
        toolresults_path = context.turn_dir / "toolresults.md"
        toolresults = ""
        if toolresults_path.exists():
            toolresults = toolresults_path.read_text()

        system_prompt = """You are a helpful assistant synthesizing a response.

Use ONLY information from the provided context and tool results.
Include citations when referencing sources.
Be natural and conversational.

If information is missing or uncertain, acknowledge it honestly."""

        user_prompt = f"""Context:
{full_context}

Tool Results:
{toolresults}

Generate a helpful response to the user's query."""

        response = await router.complete(
            layer=ModelLayer.VOICE,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=3000,
        )

        result = SynthesisResult(
            response_preview=response.content[:500],
            full_response=response.content,
            citations=[],  # TODO: Extract citations
        )

        # Write to §5
        context.write_section_5(result, attempt)

        # Write full response
        response_path = context.turn_dir / "response.md"
        response_path.write_text(response.content)

        return result
```

### 6.2 Phase 6: Validation

```python
# apps/phases/phase6_validation.py
"""Phase 6: Validation - Quality gate."""

from libs.core.models import (
    ValidationResult, ValidationDecision,
    ValidationCheck, GoalValidation,
)
from libs.llm.router import get_model_router, ModelLayer
from libs.document_io.context_manager import ContextManager


class Validation:
    """
    Phase 6: Validate response quality.

    Role: MIND (MIND model @ temp=0.5)

    Decisions:
    - APPROVE: Response is good
    - REVISE: Minor issues, back to Synthesis
    - RETRY: Major issues, back to Planner
    - FAIL: Cannot complete
    """

    async def validate(
        self,
        context: ContextManager,
        attempt: int = 1,
    ) -> ValidationResult:
        """Validate the synthesized response."""
        router = get_model_router()

        # Read context
        full_context = context.get_sections(0, 1, 2, 3, 4, 5)

        # Read response
        response_path = context.turn_dir / "response.md"
        response = response_path.read_text() if response_path.exists() else ""

        system_prompt = """You are a quality validator. Check:

1. Does the response address the original query?
2. Are all claims supported by evidence in §4?
3. Is the response complete for all goals?
4. Any hallucinated information?

Output JSON:
{
  "decision": "APPROVE|REVISE|RETRY|FAIL",
  "confidence": 0.0-1.0,
  "checks": [{"name": "query_addressed", "passed": true, "notes": ""}],
  "goal_validations": [{"goal_id": "GOAL_1", "addressed": true, "quality": 0.9}],
  "issues": ["list of issues found"],
  "revision_hints": "suggestions for improvement",
  "overall_quality": 0.0-1.0
}"""

        user_prompt = f"""Context:
{full_context}

Response to validate:
{response}

Validate this response."""

        llm_response = await router.complete(
            layer=ModelLayer.MIND,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=500,
        )

        result = self._parse_response(llm_response.content)

        # Write to §6
        context.write_section_6(result, attempt)

        return result

    def _parse_response(self, response: str) -> ValidationResult:
        """Parse validation response."""
        import json

        try:
            data = json.loads(response)
            return ValidationResult(
                decision=ValidationDecision(data["decision"]),
                confidence=data.get("confidence", 0.8),
                checks=[
                    ValidationCheck(**c) for c in data.get("checks", [])
                ],
                goal_validations=[
                    GoalValidation(**g) for g in data.get("goal_validations", [])
                ],
                issues=data.get("issues", []),
                revision_hints=data.get("revision_hints"),
                overall_quality=data.get("overall_quality"),
            )
        except (json.JSONDecodeError, KeyError) as e:
            return ValidationResult(
                decision=ValidationDecision.APPROVE,
                confidence=0.5,
                reasoning=f"Parse error: {e}",
            )
```

### 6.3 Phase 7: Save

```python
# apps/phases/phase7_save.py
"""Phase 7: Save - Persist turn data."""

from libs.document_io.context_manager import ContextManager
from libs.document_io.turn_manager import TurnManager


class Save:
    """
    Phase 7: Persist turn data.

    No LLM - purely procedural.

    Tasks:
    - Finalize context.md
    - Update turn metadata
    - Index in PostgreSQL
    - Embed in Qdrant
    """

    async def save(
        self,
        context: ContextManager,
        turn_manager: TurnManager,
        turn_number: int,
        topic: str = None,
        quality: float = None,
    ) -> None:
        """Persist turn data."""

        # Finalize turn metadata
        turn_manager.finalize_turn(
            turn_number=turn_number,
            topic=topic,
            quality=quality,
        )

        # TODO: Index in PostgreSQL
        # TODO: Embed in Qdrant

        # context.md is already saved by ContextManager
```

---

## Summary

| Phase | File | Model | Key Function |
|-------|------|-------|--------------|
| 0 | `phase0_query_analyzer.py` | REFLEX | `analyze()` |
| 1 | `phase1_reflection.py` | REFLEX | `reflect()` |
| 2 | `phase2_context_gatherer.py` | MIND | `gather()` |
| 3 | `phase3_planner.py` | MIND | `plan()` |
| 4 | `phase4_coordinator.py` | MIND | `execute()` |
| 5 | `phase5_synthesis.py` | VOICE | `synthesize()` |
| 6 | `phase6_validation.py` | MIND | `validate()` |
| 7 | `phase7_save.py` | None | `save()` |

---

## Architecture Linkages

This section maps each phase implementation to its architecture specification.

### Phase 0: Query Analyzer

**Architecture:** `architecture/main-system-patterns/phase0-query-analyzer.md`

| Design Element | Implementation | Rationale |
|----------------|----------------|-----------|
| REFLEX model | `ModelLayer.REFLEX` routing | Lightweight 0.6B model handles simple classification without engaging heavy models |
| Reference resolution | `resolved_query` + `content_reference` fields | Pronouns like "that thread" resolved before downstream phases |
| Query classification | `QueryType` enum (specific_content, general_question, followup) | Enables mode-appropriate behavior in later phases |
| §0 output | `context.write_section_0()` | Document-centric IO pattern - all phases write to context.md sections |

**Key Quote:** "Phase 0 runs REFLEX to resolve pronouns and classify query type before any expensive processing."

### Phase 1: Reflection

**Architecture:** `architecture/main-system-patterns/phase1-reflection.md`

| Design Element | Implementation | Rationale |
|----------------|----------------|-----------|
| Binary gate | `PROCEED \| CLARIFY` decision | Fast short-circuit for ambiguous queries saves resources |
| REFLEX model | `ModelLayer.REFLEX` | Simple binary decision doesn't need reasoning capability |
| Generous interpretation | "Be generous - if you can reasonably interpret the query, PROCEED" | Reduces unnecessary clarification loops |
| §1 output | `context.write_section_1()` | Reflection result feeds Phase 2 context gathering |

**Key Quote:** "Reflection is a CHEAP binary gate. It does NOT assess research feasibility (that's Planner's job)."

### Phase 2: Context Gatherer

**Architecture:** `architecture/main-system-patterns/phase2-context-gathering.md`

| Design Element | Implementation | Rationale |
|----------------|----------------|-----------|
| MIND model | `ModelLayer.MIND` | Requires reasoning to identify relevant context sources |
| Two-phase process | `_retrieval_phase()` + `_synthesis_phase()` | First identify WHAT to gather, then HOW to compile it |
| Multi-source context | Session preferences, prior turns, cached research, memory | Complete context picture before planning |
| §2 output | `context.write_section_2()` | Gathered context enables informed planning |

**Key Quote:** "Context Gatherer identifies relevant turns, checks research cache, and loads session preferences before Planner creates a strategy."

### Phase 3: Planner

**Architecture:** `architecture/main-system-patterns/phase3-planner.md`

| Design Element | Implementation | Rationale |
|----------------|----------------|-----------|
| MIND model | `ModelLayer.MIND` | Planning requires reasoning about goals and tool selection |
| Route decision | `EXECUTE \| COMPLETE` mapped to `coordinator \| synthesis` | Determines next phase based on information needs |
| Multi-goal detection | `goals` list with dependencies | Complex queries decomposed into trackable units |
| ticket.md output | `_write_ticket()` | Structured handoff to Coordinator phase |
| Retry awareness | `failure_context` parameter | Planner adjusts strategy on RETRY from Validation |

**Key Quote:** "Planner sees §0-§2 and decides: do we have enough information (COMPLETE) or need tools (EXECUTE)?"

### Phase 4: Coordinator

**Architecture:** `architecture/main-system-patterns/phase4-coordinator.md`, `architecture/main-system-patterns/PLANNER_COORDINATOR_LOOP.md`

| Design Element | Implementation | Rationale |
|----------------|----------------|-----------|
| Thin execution layer | Reads ticket.md, calls tools, writes results | Coordinator is NOT strategic - Planner owns strategy |
| MCP tool routing | `_call_tool()` via Orchestrator endpoints | All tool calls go through Orchestrator for consistent handling |
| Claim extraction | `_extract_claims()` from tool results | Evidence for Synthesis to cite |
| §4 output | `context.append_section_4()` | Cumulative results across loop iterations |
| toolresults.md | `_write_toolresults()` | Detailed results for Synthesis consumption |

**Key Quote:** "Coordinator is a THIN execution layer. It reads tickets from Planner and executes tools. Loop control belongs to Orchestrator."

### Planner-Coordinator Loop

**Architecture:** `architecture/main-system-patterns/PLANNER_COORDINATOR_LOOP.md`

| Design Element | Implementation | Rationale |
|----------------|----------------|-----------|
| Orchestrator owns loop | `PipelineOrchestrator.run_pipeline()` | Single point of loop control prevents infinite loops |
| Max 5 iterations | `max_coordinator_iterations = 5` | Hard limit prevents runaway tool execution |
| Iteration tracking | `iteration` parameter in `execute()` | Enables loop-aware behavior |
| Decision-driven exit | `action: "DONE"` vs `"TOOL_CALL"` | Coordinator signals when it needs more tools or is finished |

**Key Quote:** "The Orchestrator owns the Planner ↔ Coordinator loop. Hard limit of 5 iterations. Coordinator returns to Orchestrator after each tool batch."

### Phase 5: Synthesis

**Architecture:** `architecture/main-system-patterns/phase5-synthesis.md`

| Design Element | Implementation | Rationale |
|----------------|----------------|-----------|
| VOICE model | `ModelLayer.VOICE` | Only user-facing model - optimized for natural dialogue |
| Evidence-only synthesis | "Use ONLY information from the provided context" | Prevents hallucination by grounding in §2/§4 |
| Citation support | `citations` field (TODO) | Traceability to source evidence |
| §5 output | `context.write_section_5()` | Response preview for Validation |
| response.md | Full response file | Complete output for user delivery |
| Attempt tracking | `attempt` parameter | Enables REVISE loops from Validation |

**Key Quote:** "VOICE is the ONLY model that generates user-facing text. All output must be grounded in evidence from §4."

### Phase 6: Validation

**Architecture:** `architecture/main-system-patterns/phase6-validation.md`

| Design Element | Implementation | Rationale |
|----------------|----------------|-----------|
| MIND model | `ModelLayer.MIND` | Quality assessment requires reasoning |
| Four decisions | `APPROVE \| REVISE \| RETRY \| FAIL` | Graduated response to quality issues |
| Multi-check validation | `checks` list (query_addressed, evidence_supported, etc.) | Systematic quality verification |
| Goal-level validation | `goal_validations` list | Multi-goal queries validated per-goal |
| revision_hints | Guidance for Synthesis REVISE | Targeted improvement feedback |
| §6 output | `context.write_section_6()` | Validation result for audit trail |

**Key Quote:** "Validation has four decisions: APPROVE (ship it), REVISE (minor fixes, back to Synthesis max 2x), RETRY (major issues, back to Planner max 1x), FAIL (give up)."

### Phase 7: Save

**Architecture:** `architecture/main-system-patterns/phase7-save.md`

| Design Element | Implementation | Rationale |
|----------------|----------------|-----------|
| No LLM | Purely procedural | Persistence is deterministic, no AI needed |
| Turn finalization | `turn_manager.finalize_turn()` | Metadata update for future retrieval |
| PostgreSQL indexing | TODO | Full-text search capability |
| Qdrant embedding | TODO | Semantic similarity search |
| context.md preserved | Already saved by ContextManager | Complete audit trail of pipeline execution |

**Key Quote:** "Phase 7 is procedural. No LLM. It persists turn data to PostgreSQL and Qdrant for future retrieval."

### Model-to-Phase Summary

| Model | Phases | Role |
|-------|--------|------|
| REFLEX | 0, 1 | Fast gates and classification |
| MIND | 2, 3, 4, 6 | Reasoning, planning, validation |
| VOICE | 5 | User-facing synthesis |
| EYES | 4 (subtask) | Vision when needed (cold load) |

This mapping ensures optimal resource usage: fast models for simple tasks, reasoning models for complex decisions, and dialogue models only for user output.

---

**Previous Phase:** [04-SERVICES-OVERVIEW.md](./04-SERVICES-OVERVIEW.md)
**Next Phase:** [06-RESEARCH-MCP.md](./06-RESEARCH-MCP.md)
