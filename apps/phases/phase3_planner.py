"""Phase 3: Planner - Creates task plans.

Architecture Reference:
    architecture/main-system-patterns/phase3-planner.md

Role: MIND (MIND model @ temp=0.6)
Token Budget: ~5,750 total

Question: "What needs to be done and how?"

The Planner is the strategic decision-maker that determines:
    - EXECUTE: Need external data or tool execution (go to Phase 4)
    - COMPLETE: Can answer from current context (go to Phase 5)
    - CLARIFY: Query ambiguous, return to user (rare after Phase 1)

Also responsible for:
    - Classifying query intent (commerce, query, recall, etc.)
    - Detecting multi-goal queries and breaking them down
    - Generating ticket.md for Coordinator
    - Handling RETRY loops with failure context from Validation
    - Detecting memory patterns ("remember that...", "forget that...")
"""

from pathlib import Path
from typing import Optional

from libs.core.models import (
    TaskPlan,
    PlannerAction,
    PlannerRoute,
    Goal,
    GoalStatus,
    ToolRequest,
)
from libs.core.exceptions import PhaseError
from libs.document_io.context_manager import ContextManager

from apps.phases.base_phase import BasePhase


class Planner(BasePhase[TaskPlan]):
    """
    Phase 3: Create task plan.

    Uses MIND role (MIND model with temp=0.6) for reasoning
    about what needs to be done.

    Key Principle: LLM-driven routing based on context sufficiency,
    not hardcoded rules.
    """

    PHASE_NUMBER = 3
    PHASE_NAME = "planner"

    SYSTEM_PROMPT = """You are a task planner. Analyze the query and context to create a strategic plan.

Given sections 0-2, decide:
- EXECUTE: Need to call tools (internet.research, memory.*, file.*, etc.)
- COMPLETE: Can answer from current context (section 2 has enough info)

AVAILABLE TOOLS (chat mode):
- internet.research: Web search for products/information
- memory.search: Search persistent user memory
- memory.save: Store new user preference/fact
- memory.delete: Remove user preference/fact
- file.read: Read local files (read-only)
- file.glob: Find files by pattern (read-only)

ADDITIONAL TOOLS (code mode):
- file.write, file.edit, file.create: File modifications
- git.add, git.commit, git.push: Version control
- bash.execute: Shell commands
- test.run: Run test suite

INTENT CLASSIFICATION:
- commerce: Shopping/purchase ("find me...", "cheapest...", "buy...")
- query: Informational ("what is...", "how does...", "explain...")
- recall: Memory lookup ("what did you find...", "remember when...")
- preference: User stating preference ("I like...", "my budget is...")
- navigation: Go to specific site ("go to X.com")
- greeting: Small talk ("hello", "thanks")
- edit/create/git/test: Code operations (code mode)

MEMORY PATTERNS - ALWAYS create memory.save tool calls for these:
- "remember that..." -> memory.save (content: what to remember)
- "my favorite X is Y" -> memory.save (content: "favorite X is Y", type: preference)
- "I like X" / "I prefer X" -> memory.save (content: the preference, type: preference)
- "my budget is X" -> memory.save (content: "budget is X", type: preference)
- "I am X" / "I live in X" -> memory.save (content: the fact, type: fact)

CRITICAL: When user states a preference (intent=preference), you MUST:
1. Create a memory.save tool request to store it
2. Then optionally provide information about the topic
Do NOT skip the memory.save - the user is telling you something to remember!

Memory lookup patterns:
- "what's my favorite..." -> memory.search
- "do you know my..." -> memory.search
- "forget that..." -> memory.delete

MULTI-GOAL QUERIES:
- Detect multiple distinct goals in a single query
- List each goal with dependencies
- Research executes sequentially (one goal at a time)

=== OUTPUT FORMAT (Choose ONE) ===

IF you need tools (commerce, query, recall, preference), use EXECUTE format:
{
  "decision": "EXECUTE",
  "route": "coordinator",
  "intent": "commerce | query | recall | preference",
  "goals": [{"id": "GOAL_1", "description": "...", "status": "pending"}],
  "tool_requests": [
    {"tool": "internet.research", "args": {"query": "search terms"}, "goal_id": "GOAL_1"}
  ],
  "current_focus": "what we're working on",
  "reasoning": "why"
}

IF you can answer from context (greeting, simple facts), use COMPLETE format:
{
  "decision": "COMPLETE",
  "route": "synthesis",
  "intent": "greeting | navigation",
  "goals": [],
  "tool_requests": [],
  "reasoning": "why"
}

=== TOOL SELECTION (for EXECUTE) ===
Use ONLY these exact arg formats - no extra parameters:
- commerce/query → {"tool": "internet.research", "args": {"query": "search terms"}}
- preference → {"tool": "memory.save", "args": {"content": "...", "type": "preference"}}
- recall → {"tool": "memory.search", "args": {"query": "..."}}

=== EXAMPLES ===

User: "find me syrian hamsters for sale"
{
  "decision": "EXECUTE",
  "route": "coordinator",
  "intent": "commerce",
  "goals": [{"id": "GOAL_1", "description": "Find syrian hamsters for sale", "status": "pending"}],
  "tool_requests": [{"tool": "internet.research", "args": {"query": "syrian hamsters for sale"}, "goal_id": "GOAL_1"}],
  "reasoning": "Commerce query requires internet research"
}

User: "what is the best laptop for gaming"
{
  "decision": "EXECUTE",
  "route": "coordinator",
  "intent": "query",
  "goals": [{"id": "GOAL_1", "description": "Research best gaming laptops", "status": "pending"}],
  "tool_requests": [{"tool": "internet.research", "args": {"query": "best laptop for gaming"}, "goal_id": "GOAL_1"}],
  "reasoning": "Query requires internet research"
}

User: "my favorite color is blue"
{
  "decision": "EXECUTE",
  "route": "coordinator",
  "intent": "preference",
  "goals": [{"id": "GOAL_1", "description": "Save preference", "status": "pending"}],
  "tool_requests": [{"tool": "memory.save", "args": {"content": "favorite color is blue", "type": "preference"}, "goal_id": "GOAL_1"}],
  "reasoning": "Preference needs to be saved to memory"
}

User: "hello"
{
  "decision": "COMPLETE",
  "route": "synthesis",
  "intent": "greeting",
  "goals": [],
  "tool_requests": [],
  "reasoning": "Greeting - no tools needed"
}"""

    RETRY_PROMPT_ADDITION = """
IMPORTANT: This is a RETRY attempt. Previous attempt failed.

Read section 6 carefully to understand WHY it failed.
Read section 4 to see WHAT was already tried.
Create a NEW plan that avoids previous failures.

Common retry fixes:
- Different search terms
- Different vendors/sources
- More specific tool parameters
- Avoid sources that returned errors"""

    async def execute(
        self,
        context: ContextManager,
        attempt: int = 1,
        failure_context: Optional[str] = None,
    ) -> TaskPlan:
        """
        Create task plan.

        Args:
            context: Context manager with sections 0-2 (and 4-6 if retry)
            attempt: Attempt number (for RETRY)
            failure_context: Why previous attempt failed (for RETRY)

        Returns:
            TaskPlan with routing decision and tool requests
        """
        # Build context based on attempt
        if attempt == 1:
            # Initial attempt: read sections 0-2
            sections_content = context.get_sections(0, 1, 2)
        else:
            # Retry: read full context including previous results and failure
            sections_content = context.get_sections(0, 1, 2, 3, 4, 5, 6)

        # Build system prompt
        system_prompt = self.SYSTEM_PROMPT
        if attempt > 1:
            system_prompt += self.RETRY_PROMPT_ADDITION
            if failure_context:
                system_prompt += f"\n\nPrevious failure reason: {failure_context}"

        # Build user prompt
        user_prompt = f"""Context:
{sections_content}

Mode: {self.mode}
Attempt: {attempt}

Create a task plan. Decide:
- EXECUTE: Need to call tools
- COMPLETE: Have enough information to synthesize answer

If EXECUTE, specify which tools to call."""

        # Call LLM
        response = await self.call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=1500,
        )

        # Parse response
        plan = self._parse_response(response)

        # Write to context.md section 3
        context.write_section_3(plan, attempt)

        # Generate ticket.md if executing
        if plan.decision == PlannerAction.EXECUTE and plan.tool_requests:
            self._write_ticket(context.turn_dir, plan)

        return plan

    def _parse_response(self, response: str) -> TaskPlan:
        """Parse LLM response into TaskPlan."""
        try:
            data = self.parse_json_response(response)

            # Parse decision
            decision_str = data.get("decision", "COMPLETE").upper()
            try:
                decision = PlannerAction(decision_str)
            except ValueError:
                decision = PlannerAction.COMPLETE

            # Parse route
            route = None
            route_str = data.get("route", "synthesis")
            try:
                route = PlannerRoute(route_str)
            except ValueError:
                # Infer route from decision
                if decision == PlannerAction.EXECUTE:
                    route = PlannerRoute.COORDINATOR
                else:
                    route = PlannerRoute.SYNTHESIS

            # Parse goals
            goals = []
            for g in data.get("goals", []):
                goals.append(
                    Goal(
                        id=g.get("id", f"GOAL_{len(goals) + 1}"),
                        description=g.get("description", ""),
                        status=GoalStatus(g.get("status", "pending")),
                        dependencies=g.get("dependencies", []),
                    )
                )

            # If no goals specified but we have tool requests, create default goal
            if not goals and data.get("tool_requests"):
                goals.append(
                    Goal(
                        id="GOAL_1",
                        description="Execute requested tools",
                        status=GoalStatus.PENDING,
                    )
                )

            # Parse tool requests
            tool_requests = []
            for t in data.get("tool_requests", []):
                tool_requests.append(
                    ToolRequest(
                        tool=t.get("tool", ""),
                        args=t.get("args", {}),
                        goal_id=t.get("goal_id"),
                    )
                )

            return TaskPlan(
                decision=decision,
                route=route,
                goals=goals,
                current_focus=data.get("current_focus"),
                tool_requests=tool_requests,
                reasoning=data.get("reasoning", ""),
            )

        except PhaseError:
            raise
        except Exception as e:
            # Return minimal plan on parse failure
            return TaskPlan(
                decision=PlannerAction.COMPLETE,
                route=PlannerRoute.SYNTHESIS,
                reasoning=f"Parse error: {e}",
            )

    def _write_ticket(self, turn_dir: Path, plan: TaskPlan) -> None:
        """Write ticket.md for Coordinator."""
        ticket_path = turn_dir / "ticket.md"

        # Build markdown content
        content = f"""# Task Ticket

**Route To:** {plan.route.value if plan.route else 'coordinator'}
**Decision:** {plan.decision.value}
**Reasoning:** {plan.reasoning}

"""
        # Goals section
        if plan.goals:
            content += "## Goals\n\n"
            content += "| ID | Description | Status | Dependencies |\n"
            content += "|----|-------------|--------|---------------|\n"
            for goal in plan.goals:
                deps = ", ".join(goal.dependencies) if goal.dependencies else "-"
                content += f"| {goal.id} | {goal.description} | {goal.status.value} | {deps} |\n"
            content += "\n"

        # Current focus
        if plan.current_focus:
            content += f"## Current Focus\n\n{plan.current_focus}\n\n"

        # Tool requests
        if plan.tool_requests:
            content += "## Tool Requests\n\n"
            for req in plan.tool_requests:
                content += f"### {req.tool}\n\n"
                import json
                content += f"**Args:** {json.dumps(req.args)}\n"
                if req.goal_id:
                    content += f"**Goal:** {req.goal_id}\n"
                content += "\n"

        ticket_path.write_text(content)


# Factory function for convenience
def create_planner(mode: str = "chat") -> Planner:
    """Create a Planner instance."""
    return Planner(mode=mode)
