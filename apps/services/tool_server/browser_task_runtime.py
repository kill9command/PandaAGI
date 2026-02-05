"""
Browser Task Runtime - Unified execution loop for browser automation tasks.

This is the "run the whole task" layer that executes a plan from start to finish:
- Navigate, click, type, scroll, extract
- Handle human interventions (auth, CAPTCHA)
- Visual element finding
- Automatic retries
- Progress tracking

Designed to execute tasks like:
- "Find three 600×300 cold plates under $80 on AliExpress"
- "Search for hamster care guides and summarize top 3 results"
- "Add product to cart and get total price"

Architecture:
  User → Task JSON → Runtime Loop → Browser Actions → Results
                          ↓
                   Human Intervention (when needed)

Part of Pandora's human-assisted automation system.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum
from playwright.async_api import Page

logger = logging.getLogger(__name__)


class ActionType(str, Enum):
    """Browser action types"""
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    PRESS_KEY = "press_key"
    SCROLL = "scroll"
    EXTRACT = "extract"
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    HUMAN_INTERVENTION = "human_intervention"


@dataclass
class BrowserAction:
    """
    Single browser action in a task plan.

    Examples:
        BrowserAction(
            type=ActionType.NAVIGATE,
            params={"url": "https://example.com"}
        )

        BrowserAction(
            type=ActionType.CLICK,
            params={"goal": "search button"},
            description="Click the search button"
        )

        BrowserAction(
            type=ActionType.TYPE,
            params={"text": "hamster care", "into": "search box"}
        )
    """
    type: ActionType
    params: Dict[str, Any]
    description: Optional[str] = None
    retry_on_fail: bool = True
    max_retries: int = 2


@dataclass
class TaskResult:
    """Result of executing a browser task"""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    actions_completed: int = 0
    actions_failed: int = 0
    human_interventions: int = 0
    execution_time_seconds: float = 0.0


class BrowserTaskRuntime:
    """
    Executes browser automation tasks with human-like behavior.

    This is the unified runtime that takes a task plan and executes it
    from start to finish, handling all browser interactions and
    human interventions.
    """

    def __init__(
        self,
        page: Page,
        session_id: str,
        enable_interventions: bool = True
    ):
        """
        Initialize runtime.

        Args:
            page: Playwright Page instance
            session_id: Session identifier for tracking
            enable_interventions: Whether to pause for human input when needed
        """
        self.page = page
        self.session_id = session_id
        self.enable_interventions = enable_interventions
        self.actions_completed = 0
        self.actions_failed = 0
        self.human_interventions = 0

    async def execute_task(
        self,
        actions: List[BrowserAction],
        task_description: Optional[str] = None
    ) -> TaskResult:
        """
        Execute a complete browser task from start to finish.

        Args:
            actions: List of browser actions to execute
            task_description: Human-readable task description

        Returns:
            TaskResult with success status and extracted data

        Example:
            actions = [
                BrowserAction(ActionType.NAVIGATE, {"url": "https://google.com"}),
                BrowserAction(ActionType.TYPE, {"text": "hamsters", "into": "search"}),
                BrowserAction(ActionType.PRESS_KEY, {"key": "Enter"}),
                BrowserAction(ActionType.WAIT, {"seconds": 2}),
                BrowserAction(ActionType.EXTRACT, {"goal": "first 3 search results"}),
            ]

            result = await runtime.execute_task(actions, "Search Google for hamsters")
        """
        import time
        start_time = time.time()

        logger.info(
            f"[BrowserTaskRuntime] Starting task: {task_description or 'unnamed'}\n"
            f"  Actions: {len(actions)}\n"
            f"  Session: {self.session_id}"
        )

        self.actions_completed = 0
        self.actions_failed = 0
        self.human_interventions = 0

        extracted_data = {}

        for i, action in enumerate(actions):
            action_num = i + 1
            logger.info(
                f"[BrowserTaskRuntime] Action {action_num}/{len(actions)}: "
                f"{action.type.value} - {action.description or action.params}"
            )

            # Execute action with retries
            success = False
            attempts = 0
            max_attempts = action.max_retries + 1 if action.retry_on_fail else 1

            while attempts < max_attempts and not success:
                attempts += 1

                try:
                    result = await self._execute_action(action)

                    if result.get("success"):
                        success = True
                        self.actions_completed += 1

                        # Store extracted data if this was an extract action
                        if action.type == ActionType.EXTRACT and "data" in result:
                            extracted_data[f"action_{action_num}"] = result["data"]

                        logger.info(f"  ✓ Action completed successfully")
                    else:
                        error_msg = result.get("error", "Unknown error")
                        logger.warning(f"  ✗ Action failed (attempt {attempts}/{max_attempts}): {error_msg}")

                        if attempts < max_attempts:
                            await asyncio.sleep(1)  # Wait before retry

                except Exception as e:
                    logger.error(f"  ✗ Action exception (attempt {attempts}/{max_attempts}): {e}")

                    if attempts < max_attempts:
                        await asyncio.sleep(1)

            if not success:
                self.actions_failed += 1
                logger.error(f"  ✗ Action failed after {attempts} attempts")

                # Decide whether to continue or abort
                if self._should_abort_task(action):
                    execution_time = time.time() - start_time
                    return TaskResult(
                        success=False,
                        error=f"Task aborted at action {action_num}: {action.type.value} failed",
                        actions_completed=self.actions_completed,
                        actions_failed=self.actions_failed,
                        human_interventions=self.human_interventions,
                        execution_time_seconds=execution_time
                    )

        # Task completed
        execution_time = time.time() - start_time

        task_success = self.actions_failed == 0

        logger.info(
            f"[BrowserTaskRuntime] Task completed\n"
            f"  Success: {task_success}\n"
            f"  Completed: {self.actions_completed}/{len(actions)}\n"
            f"  Failed: {self.actions_failed}\n"
            f"  Human interventions: {self.human_interventions}\n"
            f"  Time: {execution_time:.1f}s"
        )

        return TaskResult(
            success=task_success,
            data=extracted_data if extracted_data else None,
            actions_completed=self.actions_completed,
            actions_failed=self.actions_failed,
            human_interventions=self.human_interventions,
            execution_time_seconds=execution_time
        )

    async def _execute_action(self, action: BrowserAction) -> Dict[str, Any]:
        """
        Execute a single browser action.

        Args:
            action: BrowserAction to execute

        Returns:
            Result dictionary with success status
        """
        # Import tools here to avoid circular imports
        from apps.services.tool_server.ui_vision_agent import UIVisionAgent
        from apps.services.tool_server.human_behavior_simulator import HumanBehaviorSimulator

        # Initialize helpers
        vision_agent = UIVisionAgent(page=self.page)
        human_sim = HumanBehaviorSimulator(page=self.page, seed=self.session_id)

        try:
            if action.type == ActionType.NAVIGATE:
                url = action.params["url"]
                wait_for = action.params.get("wait_for", "domcontentloaded")
                await self.page.goto(url, wait_until=wait_for)
                return {"success": True, "url": url}

            elif action.type == ActionType.CLICK:
                goal = action.params["goal"]
                use_human_behavior = action.params.get("human_like", True)

                # Find element using vision
                click_result = await vision_agent.click(goal, max_attempts=3)

                if not click_result.success:
                    return {"success": False, "error": f"Could not find: {goal}"}

                return {"success": True, "clicked": goal}

            elif action.type == ActionType.TYPE:
                text = action.params["text"]
                into = action.params.get("into")

                # Click target field first if specified
                if into:
                    click_result = await vision_agent.click(into, max_attempts=2)
                    if not click_result.success:
                        return {"success": False, "error": f"Could not find field: {into}"}

                # Type with human-like behavior
                await human_sim.type_like_human(text)
                return {"success": True, "typed": text}

            elif action.type == ActionType.PRESS_KEY:
                key = action.params["key"]
                await self.page.keyboard.press(key)
                return {"success": True, "key": key}

            elif action.type == ActionType.SCROLL:
                direction = action.params.get("direction", "down")
                amount = action.params.get("amount", 500)

                if direction == "down":
                    await self.page.evaluate(f"window.scrollBy(0, {amount})")
                elif direction == "up":
                    await self.page.evaluate(f"window.scrollBy(0, -{amount})")

                return {"success": True, "scrolled": direction}

            elif action.type == ActionType.EXTRACT:
                goal = action.params["goal"]

                # Use vision agent to extract text/data
                extract_result = await vision_agent.extract_text(goal)

                if not extract_result.success:
                    return {"success": False, "error": f"Could not extract: {goal}"}

                return {
                    "success": True,
                    "data": extract_result.text,
                    "confidence": extract_result.confidence
                }

            elif action.type == ActionType.WAIT:
                seconds = action.params.get("seconds", 1.0)
                await asyncio.sleep(seconds)
                return {"success": True, "waited": seconds}

            elif action.type == ActionType.SCREENSHOT:
                path = action.params.get("path", f"/tmp/screenshot_{self.session_id}.png")
                await self.page.screenshot(path=path)
                return {"success": True, "screenshot": path}

            elif action.type == ActionType.HUMAN_INTERVENTION:
                reason = action.params.get("reason", "Human input needed")
                await self._request_human_intervention(reason)
                self.human_interventions += 1
                return {"success": True, "intervention": reason}

            else:
                return {"success": False, "error": f"Unknown action type: {action.type}"}

        except Exception as e:
            logger.error(f"[BrowserTaskRuntime] Action execution error: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def _request_human_intervention(self, reason: str):
        """
        Request human intervention and wait for completion.

        This is called when the automation encounters:
        - Login screens
        - CAPTCHAs
        - 2FA prompts
        - Cloudflare challenges

        Args:
            reason: Why human intervention is needed
        """
        if not self.enable_interventions:
            logger.warning(f"[BrowserTaskRuntime] Intervention needed but disabled: {reason}")
            return

        from apps.services.tool_server.intervention_manager import get_intervention_manager

        manager = get_intervention_manager()

        logger.info(f"[BrowserTaskRuntime] Requesting human intervention: {reason}")

        # Create intervention request
        intervention_id = await manager.request_intervention(
            session_id=self.session_id,
            intervention_type="manual_action",
            reason=reason,
            current_url=self.page.url,
            screenshot_path=None  # Could take screenshot here
        )

        # Wait for human to resolve
        await manager.wait_for_resolution(intervention_id, timeout_seconds=300)

        logger.info(f"[BrowserTaskRuntime] Human intervention completed: {intervention_id}")

    def _should_abort_task(self, failed_action: BrowserAction) -> bool:
        """
        Decide whether to abort task after action failure.

        Args:
            failed_action: The action that failed

        Returns:
            True if task should abort, False to continue
        """
        # Critical actions that should abort task
        critical_actions = [ActionType.NAVIGATE]

        if failed_action.type in critical_actions:
            return True

        # Abort if too many failures
        if self.actions_failed >= 3:
            return True

        return False


# Convenience function

async def execute_browser_task(
    page: Page,
    actions: List[BrowserAction],
    session_id: str = "default",
    task_description: Optional[str] = None
) -> TaskResult:
    """
    Quick execute a browser task.

    Args:
        page: Playwright Page instance
        actions: List of actions to execute
        session_id: Session identifier
        task_description: Task description for logging

    Returns:
        TaskResult

    Example:
        from apps.services.tool_server.real_browser_connector import connect_to_user_browser
        from apps.services.tool_server.browser_task_runtime import execute_browser_task, BrowserAction, ActionType

        browser, page = await connect_to_user_browser()

        result = await execute_browser_task(
            page=page,
            actions=[
                BrowserAction(ActionType.NAVIGATE, {"url": "https://google.com"}),
                BrowserAction(ActionType.TYPE, {"text": "hamsters", "into": "search"}),
                BrowserAction(ActionType.PRESS_KEY, {"key": "Enter"}),
            ],
            task_description="Search Google for hamsters"
        )

        print(f"Success: {result.success}")
    """
    runtime = BrowserTaskRuntime(page=page, session_id=session_id)
    return await runtime.execute_task(actions, task_description)
