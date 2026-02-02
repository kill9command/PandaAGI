"""
Pandora Loop - Multi-Task Autonomous Execution Loop

Implements the outer loop that wraps handle_request() to execute multiple tasks
sequentially. Each task runs through the full phase pipeline (0-7) with its own
validation and retry logic.

Architecture Reference:
    architecture/main-system-patterns/RALPH_LOOP.md

Loop Hierarchy:
    Level 0: Pandora Loop (this) - max 10 tasks
        └── For each task:
            └── handle_request() - runs full pipeline
                └── Level 1: Planner-Coordinator Loop - max 5 iterations
                    └── Level 2: Tool Execution Loops

Inspired by: https://github.com/snarktank/ralph
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any, TYPE_CHECKING
import json
import logging
import time

if TYPE_CHECKING:
    from libs.gateway.unified_flow import UnifiedFlow

logger = logging.getLogger(__name__)


@dataclass
class LoopResult:
    """Result of Pandora Loop execution."""
    status: str  # "complete", "max_iterations", "blocked"
    tasks: list[dict]
    passed: int = 0
    failed: int = 0
    blocked: int = 0
    summary: str = ""
    duration_seconds: float = 0.0


@dataclass
class TaskResult:
    """Result of single task execution."""
    validation: str  # "APPROVE" or "FAIL"
    failure_reason: Optional[str] = None
    learnings: list[str] = field(default_factory=list)
    response: str = ""


class PandoraLoop:
    """
    Outer loop for multi-task execution.

    Wraps handle_request() to execute multiple tasks sequentially,
    using validation results to determine pass/fail.

    Usage:
        loop = PandoraLoop(
            tasks=[
                {"id": "TASK-001", "title": "...", "status": "pending", ...},
                {"id": "TASK-002", "title": "...", "status": "pending", ...},
            ],
            original_query="Implement auth with OAuth and sessions",
            session_id="session_123",
            mode="code",
            unified_flow=unified_flow_instance,
        )
        result = await loop.run()
    """

    MAX_ITERATIONS = 10

    def __init__(
        self,
        tasks: list[dict],
        original_query: str,
        session_id: str,
        mode: str,
        unified_flow: "UnifiedFlow",
        base_turn: int = 1,
        trace_id: str = "",
    ):
        """
        Initialize Pandora Loop.

        Args:
            tasks: List of task dicts with id, title, description, status, etc.
            original_query: The user's original multi-task request
            session_id: Session identifier
            mode: "chat" or "code"
            unified_flow: UnifiedFlow instance to call handle_request()
            base_turn: Starting turn number (tasks increment from here)
            trace_id: Trace identifier for logging
        """
        self.tasks = tasks
        self.original_query = original_query
        self.session_id = session_id
        self.mode = mode
        self.unified_flow = unified_flow
        self.base_turn = base_turn
        self.trace_id = trace_id
        self.learnings: list[dict] = []  # Accumulated learnings across tasks
        self.start_time: float = 0.0

        # Ensure all tasks have required fields
        for task in self.tasks:
            if "status" not in task:
                task["status"] = "pending"
            if "id" not in task:
                task["id"] = f"TASK-{self.tasks.index(task) + 1:03d}"

    async def run(self) -> LoopResult:
        """
        Execute all tasks in sequence.

        Returns:
            LoopResult with status, task outcomes, and summary
        """
        self.start_time = time.time()
        logger.info(f"[PandoraLoop] Starting with {len(self.tasks)} tasks (trace={self.trace_id})")

        # Log task overview
        for task in self.tasks:
            deps = task.get("depends_on", [])
            logger.info(f"[PandoraLoop]   {task['id']}: {task['title']} (deps: {deps or 'none'})")

        iteration = 0
        while iteration < self.MAX_ITERATIONS:
            # Select next eligible task
            task = self._select_next_task()
            if not task:
                # All tasks complete or blocked
                return self._build_result("complete")

            iteration += 1
            task_num = next(i + 1 for i, t in enumerate(self.tasks) if t["id"] == task["id"])
            logger.info(f"[PandoraLoop] === Iteration {iteration}: Task {task_num}/{len(self.tasks)} ===")
            logger.info(f"[PandoraLoop] {task['id']}: {task['title']}")

            # Mark in progress
            task["status"] = "in_progress"

            # Execute task
            result = await self._execute_task(task, iteration - 1)

            # Update status based on validation
            if result.validation == "APPROVE":
                task["status"] = "passed"
                logger.info(f"[PandoraLoop] {task['id']} -> PASSED")

                # Save learnings if any
                if result.learnings:
                    await self._save_learnings(task, result.learnings)
            else:
                task["status"] = "failed"
                task["notes"] = result.failure_reason or "Validation failed"
                logger.warning(f"[PandoraLoop] {task['id']} -> FAILED: {task['notes']}")

        return self._build_result("max_iterations")

    def _select_next_task(self) -> Optional[dict]:
        """
        Select highest-priority task with satisfied dependencies.

        Returns:
            Next eligible task, or None if all complete/blocked
        """
        completed_ids = {t["id"] for t in self.tasks if t["status"] == "passed"}
        failed_ids = {t["id"] for t in self.tasks if t["status"] == "failed"}

        eligible = []
        for task in self.tasks:
            if task["status"] != "pending":
                continue

            # Check dependencies
            deps = task.get("depends_on", [])
            unmet_deps = [d for d in deps if d not in completed_ids]

            if not unmet_deps:
                # All dependencies satisfied
                eligible.append(task)
            elif any(d in failed_ids for d in deps):
                # A dependency failed - this task is blocked
                task["status"] = "blocked"
                task["notes"] = f"Blocked by failed dependency: {[d for d in deps if d in failed_ids]}"
                logger.warning(f"[PandoraLoop] {task['id']} blocked by failed dependencies")
            # else: still waiting on pending dependencies

        if not eligible:
            # Check if we're deadlocked (remaining tasks have unmet deps)
            pending = [t for t in self.tasks if t["status"] == "pending"]
            if pending:
                logger.warning(f"[PandoraLoop] {len(pending)} tasks still pending but not eligible")
            return None

        # Return highest priority (lowest number)
        return min(eligible, key=lambda t: t.get("priority", 99))

    async def _execute_task(self, task: dict, task_index: int) -> TaskResult:
        """
        Execute single task via handle_request().

        Args:
            task: Task dict with id, title, description, etc.
            task_index: Zero-based index for turn numbering

        Returns:
            TaskResult with validation outcome
        """
        # Build augmented query with task context
        augmented_query = self._build_task_query(task)

        # Calculate turn number for this task
        turn_number = self.base_turn + task_index

        try:
            # Call existing handle_request - includes all phases + retry
            result = await self.unified_flow.handle_request(
                user_query=augmented_query,
                session_id=self.session_id,
                mode=self.mode,
                turn_number=turn_number,
                trace_id=f"{self.trace_id}-{task['id']}" if self.trace_id else task['id'],
            )

            # Extract validation outcome
            # handle_request returns validation result in the response dict
            # If it needed clarification or failed validation, it indicates retry needed
            needs_clarification = result.get("needs_clarification", False)
            needs_retry = result.get("needs_retry", False)

            if needs_clarification:
                return TaskResult(
                    validation="FAIL",
                    failure_reason="Task requires clarification",
                    response=result.get("response", ""),
                )

            if needs_retry:
                return TaskResult(
                    validation="FAIL",
                    failure_reason=result.get("failure_reason", "Validation failed after retries"),
                    response=result.get("response", ""),
                )

            # Success - extract any learnings from the response
            learnings = self._extract_learnings(result)

            return TaskResult(
                validation="APPROVE",
                learnings=learnings,
                response=result.get("response", ""),
            )

        except Exception as e:
            logger.error(f"[PandoraLoop] Task {task['id']} exception: {e}", exc_info=True)
            return TaskResult(
                validation="FAIL",
                failure_reason=f"Exception: {str(e)}",
            )

    def _build_task_query(self, task: dict) -> str:
        """
        Build query with task context injected.

        The task context is prepended to the query so the pipeline
        understands this is a specific task within a larger request.
        """
        task_index = next(i for i, t in enumerate(self.tasks) if t["id"] == task["id"])

        # Include prior learnings from completed tasks
        learnings_text = ""
        if self.learnings:
            learnings_text = "\n**Prior Task Learnings:**\n"
            for learning in self.learnings[-5:]:  # Last 5 learnings
                learnings_text += f"- [{learning['task_id']}] {learning['text']}\n"

        # Format acceptance criteria
        criteria = task.get("acceptance_criteria", [])
        criteria_text = self._format_criteria(criteria)

        # Build the augmented query
        return f"""**PANDORA LOOP - Task {task_index + 1} of {len(self.tasks)}**

| Field | Value |
|-------|-------|
| Task ID | {task['id']} |
| Title | {task['title']} |
| Description | {task.get('description', 'N/A')} |
| Priority | {task.get('priority', 'N/A')} |
| Dependencies | {', '.join(task.get('depends_on', [])) or 'None'} |

**Acceptance Criteria:**
{criteria_text}
{learnings_text}
---

**Original Request:** {self.original_query}

---

**Current Task:** {task['title']}

{task.get('description', '')}
"""

    def _format_criteria(self, criteria: list) -> str:
        """Format acceptance criteria as numbered list."""
        if not criteria:
            return "*(No specific criteria - use reasonable defaults)*"
        return "\n".join(f"{i+1}. {c}" for i, c in enumerate(criteria))

    def _extract_learnings(self, result: dict) -> list[str]:
        """
        Extract learnings from task result.

        Looks for patterns, conventions, or important discoveries
        in the response that should inform subsequent tasks.
        """
        learnings = []
        response = result.get("response", "")

        # Look for explicit pattern mentions
        # This is a simplified heuristic - could be enhanced with LLM extraction
        lower_response = response.lower()

        patterns_to_detect = [
            ("uses ", "framework/library usage"),
            ("pattern:", "design pattern"),
            ("convention:", "coding convention"),
            ("located in ", "file location"),
            ("configured in ", "configuration location"),
        ]

        for trigger, category in patterns_to_detect:
            if trigger in lower_response:
                # Find the sentence containing the trigger
                sentences = response.split(". ")
                for sentence in sentences:
                    if trigger in sentence.lower() and len(sentence) < 200:
                        learnings.append(sentence.strip())
                        break

        return learnings[:3]  # Limit to 3 learnings per task

    async def _save_learnings(self, task: dict, learnings: list[str]):
        """
        Save learnings to obsidian_memory for future reference.

        Also adds to in-memory learnings for subsequent tasks in this loop.
        """
        if not learnings:
            return

        # Add to in-memory learnings for subsequent tasks
        for learning in learnings:
            self.learnings.append({
                "task_id": task["id"],
                "text": learning,
            })
            logger.info(f"[PandoraLoop] Learning from {task['id']}: {learning[:80]}...")

        # Try to persist to obsidian_memory
        try:
            from apps.tools.memory import write_memory

            await write_memory(
                artifact_type="research",
                topic=f"pandora-loop-learnings-{task['id']}",
                content={
                    "summary": f"Patterns learned from: {task['title']}",
                    "findings": learnings,
                    "task_id": task["id"],
                    "original_query": self.original_query[:200],
                },
                tags=["pandora-loop", "code-patterns", task["id"]],
                source="pandora_loop",
                confidence=0.9,
            )
        except ImportError:
            logger.debug("[PandoraLoop] obsidian_memory not available, skipping persistence")
        except Exception as e:
            logger.warning(f"[PandoraLoop] Failed to save learnings to memory: {e}")

    def _build_result(self, status: str) -> LoopResult:
        """Build final loop result with summary statistics."""
        passed = len([t for t in self.tasks if t["status"] == "passed"])
        failed = len([t for t in self.tasks if t["status"] == "failed"])
        blocked = len([t for t in self.tasks if t["status"] == "blocked"])
        pending = len([t for t in self.tasks if t["status"] == "pending"])

        duration = time.time() - self.start_time

        # Build summary
        parts = [f"{passed}/{len(self.tasks)} tasks passed"]
        if failed:
            parts.append(f"{failed} failed")
        if blocked:
            parts.append(f"{blocked} blocked")
        if pending:
            parts.append(f"{pending} pending")
        summary = ", ".join(parts)

        logger.info(f"[PandoraLoop] Complete: {summary} in {duration:.1f}s")

        return LoopResult(
            status=status,
            tasks=self.tasks,
            passed=passed,
            failed=failed,
            blocked=blocked,
            summary=summary,
            duration_seconds=duration,
        )


def format_loop_summary(result: LoopResult) -> str:
    """
    Format loop result as user-facing markdown summary.

    Used by UnifiedFlow to generate the final response.
    """
    lines = [
        "## Pandora Loop Complete",
        "",
        f"**Status:** {result.status.upper()}",
        f"**Summary:** {result.summary}",
        f"**Duration:** {result.duration_seconds:.1f} seconds",
        "",
        "### Task Results",
        "",
        "| Task | Title | Status |",
        "|------|-------|--------|",
    ]

    for task in result.tasks:
        status_icon = {
            "passed": "PASSED",
            "failed": "FAILED",
            "blocked": "BLOCKED",
            "pending": "PENDING",
            "in_progress": "IN PROGRESS",
        }.get(task["status"], task["status"])

        title = task.get("title", "Untitled")[:50]
        lines.append(f"| {task['id']} | {title} | {status_icon} |")

    # Add failure notes if any
    failed_tasks = [t for t in result.tasks if t["status"] == "failed"]
    if failed_tasks:
        lines.extend([
            "",
            "### Failure Notes",
            "",
        ])
        for task in failed_tasks:
            notes = task.get("notes", "No details available")
            lines.append(f"- **{task['id']}**: {notes}")

    return "\n".join(lines)
