"""
orchestrator/computer_agent_mcp.py

Computer Agent MCP Tool - Vision-guided desktop automation

Exposes computer.* functions for LLM-driven desktop control:
- computer.click(goal) - Click UI element matching description
- computer.type(text, into=None) - Type text (optionally click field first)
- computer.press_key(key) - Press keyboard key
- computer.scroll(clicks) - Scroll mouse wheel
- computer.screenshot() - Capture screen
- computer.plan_and_execute(task) - Multi-step task with LLM planning

Architecture:
    User Request → Guide Role → Computer Agent Role (LLM plans)
                                        ↓
                                computer.plan_and_execute(task)
                                        ↓
                                ComputerAgent (vision + actuation)
                                        ↓
                                        Success/Failure

The Computer Agent Role (defined in apps/prompts/computer_agent/core.md) receives
a high-level task and breaks it down into atomic computer.* operations.
"""
from __future__ import annotations
import asyncio
import logging
import json
import os
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict

from apps.services.tool_server.computer_agent import ComputerAgent, ActionResult

logger = logging.getLogger(__name__)

# Global agent instance (lazy-initialized)
_agent: Optional[ComputerAgent] = None


def get_agent() -> ComputerAgent:
    """Get or create the global ComputerAgent instance."""
    global _agent
    if _agent is None:
        # Default config: OCR + shapes enabled, human timing
        _agent = ComputerAgent(
            enable_ocr=True,
            enable_shapes=True,
            enable_windows=False,  # Platform-specific, disabled by default
            human_timing=True
        )
        logger.info("[ComputerAgentMCP] Initialized global ComputerAgent")
    return _agent


# ============================================================================
# Atomic Actions (directly exposed to LLM)
# ============================================================================


async def click(
    goal: str,
    max_attempts: int = 3,
    timeout: float = 30.0
) -> Dict[str, Any]:
    """
    Click a UI element matching the goal description.

    Args:
        goal: Description of what to click (e.g., "OK button", "search icon", "Next")
        max_attempts: Max number of candidates to try
        timeout: Max time to spend (seconds)

    Returns:
        {
            "success": bool,
            "candidate": {...} or null,
            "verification_method": str,
            "metadata": {...},
            "message": str
        }

    Examples:
        computer.click("Start menu")
        computer.click("Google Chrome icon")
        computer.click("Search button")
        computer.click("Next page")
    """
    try:
        agent = get_agent()
        result = await agent.click(goal, max_attempts=max_attempts, timeout=timeout)

        return {
            "success": result.success,
            "candidate": {
                "text": result.candidate.text,
                "bbox": {
                    "x": result.candidate.bbox.x,
                    "y": result.candidate.bbox.y,
                    "width": result.candidate.bbox.width,
                    "height": result.candidate.bbox.height
                },
                "confidence": result.candidate.confidence,
                "source": result.candidate.source.value
            } if result.candidate else None,
            "verification_method": result.verification_method,
            "metadata": result.metadata,
            "message": _format_result_message(result)
        }

    except Exception as e:
        logger.error(f"[ComputerAgentMCP] click failed: {e}")
        return {
            "success": False,
            "candidate": None,
            "verification_method": "error",
            "metadata": {"error": str(e)},
            "message": f"Failed to click '{goal}': {e}"
        }


async def type_text(
    text: str,
    into: Optional[str] = None,
    interval: float = 0.05
) -> Dict[str, Any]:
    """
    Type text on the keyboard.

    Args:
        text: Text to type
        into: Optional description of field to click first (e.g., "search box", "username field")
        interval: Interval between keystrokes (seconds)

    Returns:
        {
            "success": bool,
            "verification_method": str,
            "metadata": {...},
            "message": str
        }

    Examples:
        computer.type_text("hello world")
        computer.type_text("search query", into="search box")
        computer.type_text("admin@example.com", into="email field")
    """
    try:
        agent = get_agent()
        result = await agent.type_text(text, into=into, interval=interval)

        return {
            "success": result.success,
            "verification_method": result.verification_method,
            "metadata": result.metadata,
            "message": _format_result_message(result)
        }

    except Exception as e:
        logger.error(f"[ComputerAgentMCP] type_text failed: {e}")
        return {
            "success": False,
            "verification_method": "error",
            "metadata": {"error": str(e)},
            "message": f"Failed to type text: {e}"
        }


async def press_key(
    key: str,
    presses: int = 1
) -> Dict[str, Any]:
    """
    Press a keyboard key.

    Args:
        key: Key name (e.g., "enter", "tab", "esc", "space", "backspace", "delete")
        presses: Number of times to press

    Returns:
        {
            "success": bool,
            "verification_method": str,
            "metadata": {...},
            "message": str
        }

    Examples:
        computer.press_key("enter")
        computer.press_key("tab", presses=3)
        computer.press_key("esc")
    """
    try:
        agent = get_agent()
        result = await agent.press_key(key, presses=presses)

        return {
            "success": result.success,
            "verification_method": result.verification_method,
            "metadata": result.metadata,
            "message": f"Pressed '{key}' {presses} time(s)"
        }

    except Exception as e:
        logger.error(f"[ComputerAgentMCP] press_key failed: {e}")
        return {
            "success": False,
            "verification_method": "error",
            "metadata": {"error": str(e)},
            "message": f"Failed to press key '{key}': {e}"
        }


async def scroll(
    clicks: int
) -> Dict[str, Any]:
    """
    Scroll mouse wheel.

    Args:
        clicks: Number of scroll clicks (positive=up/forward, negative=down/backward)

    Returns:
        {
            "success": bool,
            "verification_method": str,
            "metadata": {...},
            "message": str
        }

    Examples:
        computer.scroll(5)    # Scroll up
        computer.scroll(-3)   # Scroll down
    """
    try:
        agent = get_agent()
        result = await agent.scroll(clicks)

        direction = "up" if clicks > 0 else "down"
        return {
            "success": result.success,
            "verification_method": result.verification_method,
            "metadata": result.metadata,
            "message": f"Scrolled {direction} {abs(clicks)} clicks"
        }

    except Exception as e:
        logger.error(f"[ComputerAgentMCP] scroll failed: {e}")
        return {
            "success": False,
            "verification_method": "error",
            "metadata": {"error": str(e)},
            "message": f"Failed to scroll: {e}"
        }


async def screenshot(
    save_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Capture screenshot of current screen.

    Args:
        save_path: Optional path to save screenshot (default: temp file)

    Returns:
        {
            "success": bool,
            "screenshot_path": str or null,
            "screen_size": {"width": int, "height": int},
            "message": str
        }

    Examples:
        computer.screenshot()
        computer.screenshot(save_path="/tmp/screen.png")
    """
    try:
        agent = get_agent()

        # Get screen size
        width, height = await agent.actuator.get_screen_size()

        # Take screenshot
        if not save_path:
            import tempfile
            save_path = tempfile.mktemp(suffix=".png", prefix="computer_agent_screenshot_")

        success, error, path = await agent.actuator.screenshot(save_path)

        if not success:
            return {
                "success": False,
                "screenshot_path": None,
                "screen_size": {"width": width, "height": height},
                "message": f"Screenshot failed: {error}"
            }

        return {
            "success": True,
            "screenshot_path": path,
            "screen_size": {"width": width, "height": height},
            "message": f"Screenshot saved: {path}"
        }

    except Exception as e:
        logger.error(f"[ComputerAgentMCP] screenshot failed: {e}")
        return {
            "success": False,
            "screenshot_path": None,
            "screen_size": None,
            "message": f"Failed to capture screenshot: {e}"
        }


# ============================================================================
# Multi-Step Planning (LLM-driven)
# ============================================================================


async def plan_and_execute(
    task: str,
    session_id: str = "default",
    user_id: str = "user"
) -> Dict[str, Any]:
    """
    Execute a multi-step desktop task with LLM planning.

    The Computer Agent Role (LLM) receives the task, breaks it down into steps,
    and executes each step using the atomic computer.* operations.

    Args:
        task: High-level task description (e.g., "Open Chrome and search for hamsters")
        session_id: Session identifier for context
        user_id: User identifier

    Returns:
        {
            "success": bool,
            "plan": List[str],  # List of planned steps
            "results": List[Dict],  # Results of each step
            "message": str
        }

    Examples:
        computer.plan_and_execute("Open Chrome and search for hamsters")
        computer.plan_and_execute("Find and open the file manager")
        computer.plan_and_execute("Copy text from notepad and paste into browser")

    Note:
        This function delegates to the Computer Agent LLM role, which uses
        the atomic computer.* operations to accomplish the task.
    """
    try:
        # This will be implemented after creating the LLM prompt
        # For now, return a placeholder indicating LLM integration needed

        logger.info(f"[ComputerAgentMCP] plan_and_execute: {task}")

        # TODO: Integrate with LLM role (apps/prompts/computer_agent/core.md)
        # The LLM should:
        # 1. Parse the task
        # 2. Break it into atomic steps
        # 3. Execute each step using computer.click/type/press_key/scroll
        # 4. Verify completion

        return {
            "success": False,
            "plan": [],
            "results": [],
            "message": (
                "plan_and_execute not yet implemented - requires LLM role integration. "
                "Use atomic operations (computer.click, computer.type, etc.) directly for now."
            )
        }

    except Exception as e:
        logger.error(f"[ComputerAgentMCP] plan_and_execute failed: {e}")
        return {
            "success": False,
            "plan": [],
            "results": [],
            "message": f"Failed to execute task: {e}"
        }


# ============================================================================
# Utilities
# ============================================================================


def _format_result_message(result: ActionResult) -> str:
    """Format ActionResult into human-readable message."""
    if result.success:
        if result.candidate:
            return (
                f"Successfully clicked '{result.candidate.text}' "
                f"(confidence={result.candidate.confidence:.2f}, "
                f"verified via {result.verification_method})"
            )
        else:
            return f"Action completed (verified via {result.verification_method})"
    else:
        if result.verification_method == "no_candidates":
            return "No UI elements found matching the goal"
        elif result.verification_method == "max_attempts_exceeded":
            attempts = result.metadata.get("attempts", "unknown")
            return f"Failed after {attempts} attempts - no successful verification"
        elif result.verification_method == "click_failed":
            return "Failed to click the target field before typing"
        else:
            return f"Action failed ({result.verification_method})"


async def get_status() -> Dict[str, Any]:
    """
    Get Computer Agent status and configuration.

    Returns:
        {
            "initialized": bool,
            "config": {...},
            "screen_size": {"width": int, "height": int},
            "mouse_position": {"x": int, "y": int}
        }
    """
    try:
        global _agent
        if _agent is None:
            return {
                "initialized": False,
                "config": {},
                "screen_size": None,
                "mouse_position": None
            }

        width, height = await _agent.actuator.get_screen_size()
        mouse_x, mouse_y = await _agent.actuator.get_mouse_position()

        return {
            "initialized": True,
            "config": {
                "enable_ocr": _agent.perception.enable_ocr,
                "enable_shapes": _agent.perception.enable_shapes,
                "enable_windows": _agent.perception.enable_windows,
                "human_timing": _agent.actuator.human_timing
            },
            "screen_size": {"width": width, "height": height},
            "mouse_position": {"x": mouse_x, "y": mouse_y}
        }

    except Exception as e:
        logger.error(f"[ComputerAgentMCP] get_status failed: {e}")
        return {
            "initialized": False,
            "config": {},
            "screen_size": None,
            "mouse_position": None,
            "error": str(e)
        }


async def get_screen_state(
    max_elements: int = 20,
    max_text_len: int = 20
) -> Dict[str, Any]:
    """
    Get current screen state as ultra-compact text description.

    Returns UI candidates visible on screen formatted as compact text
    for vision-in-the-loop LLM prompts (<280 tokens).

    Args:
        max_elements: Maximum UI elements to return (default: 20)
        max_text_len: Maximum text length per element (default: 20)

    Returns:
        {
            "success": bool,
            "screen_state": str,
            "element_count": int,
            "estimated_tokens": int,
            "screen_size": {"width": int, "height": int},
            "message": str
        }
    """
    screenshot_path = None  # Track for cleanup

    try:
        agent = get_agent()

        # Get screen size first
        width, height = await agent.actuator.get_screen_size()

        # Take screenshot (temp file)
        import tempfile
        screenshot_path = tempfile.mktemp(suffix=".png", prefix="screen_state_")

        success, error, path = await agent.actuator.screenshot(screenshot_path)

        if not success:
            logger.error(f"[ComputerAgentMCP] Screenshot failed: {error}")
            return {
                "success": False,
                "screen_state": "",
                "element_count": 0,
                "estimated_tokens": 0,
                "screen_size": {"width": width, "height": height},
                "message": f"Screenshot failed: {error}"
            }

        # Extract UI candidates
        candidates = await agent.perception.extract_candidates(path, width, height)

        # Clean up screenshot file immediately
        import os
        try:
            if os.path.exists(screenshot_path):
                os.unlink(screenshot_path)
                logger.debug(f"[ComputerAgentMCP] Cleaned up screenshot: {screenshot_path}")
        except Exception as cleanup_error:
            logger.warning(f"[ComputerAgentMCP] Cleanup failed: {cleanup_error}")

        # Sort by confidence and limit
        sorted_candidates = sorted(
            candidates,
            key=lambda c: c.confidence,
            reverse=True
        )[:max_elements]

        # Format ultra-compact text
        source_abbrev = {
            "screen_ocr": "OCR",
            "screen_shape": "Shp",
            "window_api": "Win"
        }

        lines = [f"{len(sorted_candidates)} elements found:"]
        for i, cand in enumerate(sorted_candidates, 1):
            text_preview = cand.text[:max_text_len] if cand.text else "(no text)"
            x = int(cand.bbox.x)
            y = int(cand.bbox.y)
            conf = int(cand.confidence * 100)
            src = source_abbrev.get(cand.source.value, "?")

            lines.append(f"{i}. [{src}] '{text_preview}' @({x},{y}) {conf}%")

        screen_state = "\n".join(lines)
        estimated_tokens = len(screen_state) // 4

        logger.info(
            f"[ComputerAgentMCP] Screen state: {len(sorted_candidates)} elements, "
            f"~{estimated_tokens} tokens"
        )

        return {
            "success": True,
            "screen_state": screen_state,
            "element_count": len(sorted_candidates),
            "estimated_tokens": estimated_tokens,
            "screen_size": {"width": width, "height": height},
            "message": f"Screen state captured: {len(sorted_candidates)} elements, ~{estimated_tokens} tokens"
        }

    except Exception as e:
        logger.error(f"[ComputerAgentMCP] get_screen_state failed: {e}")

        # Cleanup on error
        if screenshot_path:
            try:
                import os
                if os.path.exists(screenshot_path):
                    os.unlink(screenshot_path)
            except:
                pass

        return {
            "success": False,
            "screen_state": "",
            "element_count": 0,
            "estimated_tokens": 0,
            "screen_size": None,
            "message": f"Error: {e}"
        }
