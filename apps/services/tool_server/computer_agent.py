"""
orchestrator/computer_agent.py

Computer Agent - Vision-guided desktop automation

Combines desktop perception (OCR + shapes + windows) with pyautogui actuation
to click, type, and interact with any desktop UI element.

Architecture:
    User → Computer Agent Role (LLM plans) → ComputerAgent (executes)
           ↓
    1. Perception: Screen capture + OCR + shapes
    2. Targeting: Rank candidates by goal
    3. Actuation: Click/type via pyautogui
    4. Verification: Screenshot diff

Similar to UIVisionAgent but for desktop instead of web.
"""
from __future__ import annotations
import asyncio
import logging
import tempfile
import time
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass

from apps.services.tool_server.desktop_perception import (
    DesktopPerceptionEngine,
    CandidateSource,
    UICandidate,
    BoundingBox
)
from apps.services.tool_server.desktop_actuator import DesktopActuator, ScreenRegion

logger = logging.getLogger(__name__)

# Lazy-load OpenCV for screenshot diff
_cv2 = None
_np = None


def _get_cv2():
    global _cv2
    if _cv2 is None:
        try:
            import cv2
            _cv2 = cv2
        except ImportError:
            logger.warning("OpenCV not available for verification")
    return _cv2


def _get_numpy():
    global _np
    if _np is None:
        try:
            import numpy as np
            _np = np
        except ImportError:
            logger.warning("Numpy not available for verification")
    return _np


@dataclass
class ActionResult:
    """Result of a computer agent action."""
    success: bool
    candidate: Optional[UICandidate]
    verification_method: str
    metadata: Dict[str, Any]


class TargetingPolicy:
    """
    Ranks UI candidates by relevance to goal.

    Reuses multi-factor scoring from UIVisionAgent:
    - Text match (0-10 points)
    - Source reliability (0-5 points)
    - Perception confidence (0-5 points)
    - Size appropriateness (0-3 points)
    - Screen position (0-2 points)
    - Proximity to last interaction (0-2 points)

    Total: 27 points max, normalized to 0-1 confidence
    """

    def __init__(self):
        self.last_interaction_pos: Optional[Tuple[int, int]] = None

        # Synonym mapping for better matching
        self.synonyms = {
            "search": ["go", "find", "submit", "query"],
            "close": ["exit", "quit", "cancel", "dismiss"],
            "ok": ["confirm", "accept", "yes", "continue"],
            "cancel": ["no", "back", "abort"],
            "next": ["forward", "continue", "proceed"],
            "previous": ["back", "prev"],
            "menu": ["options", "settings", "more"],
        }

    def rank_candidates(
        self,
        candidates: list[UICandidate],
        goal: str,
        screen_width: int,
        screen_height: int
    ) -> list[UICandidate]:
        """
        Rank candidates by relevance to goal.

        Args:
            candidates: List of UI candidates
            goal: User's goal (e.g., "click OK button")
            screen_width: Screen width for position scoring
            screen_height: Screen height for position scoring

        Returns:
            Sorted list of candidates (highest confidence first)
        """
        goal_lower = goal.lower()

        for candidate in candidates:
            # 1. Text match score (0-10)
            text_score = self._compute_text_match(candidate.text.lower(), goal_lower)

            # 2. Source reliability (0-5)
            source_score = {
                CandidateSource.WINDOW_API: 5,  # Most reliable
                CandidateSource.SCREEN_OCR: 3,   # OCR is good
                CandidateSource.SCREEN_SHAPE: 1  # Shapes are weak
            }.get(candidate.source, 0)

            # 3. Perception confidence (0-5)
            confidence_score = candidate.confidence * 5

            # 4. Size appropriateness (0-3)
            size_score = self._compute_size_score(candidate.bbox)

            # 5. Screen position (0-2)
            position_score = self._compute_position_score(
                candidate.bbox, screen_width, screen_height
            )

            # 6. Proximity to last interaction (0-2)
            proximity_score = 0
            if self.last_interaction_pos:
                proximity_score = self._compute_proximity_score(
                    candidate.bbox, self.last_interaction_pos
                )

            # Total score
            total = (
                text_score +
                source_score +
                confidence_score +
                size_score +
                position_score +
                proximity_score
            )

            # Normalize to 0-1 (max possible is 27)
            candidate.confidence = total / 27.0

        # Sort by confidence
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

    def _compute_text_match(self, text: str, goal: str) -> float:
        """
        Compute text match score (0-10).

        Scoring:
        - Exact match: 10.0
        - Fuzzy match (>80% similar): 8.0
        - Synonym match: 6.0
        - Contains: 4.0
        - Partial: 2.0
        - No match: 0.0
        """
        if text == goal:
            return 10.0

        # Check synonyms
        for key, synonyms in self.synonyms.items():
            if key in goal or goal in key:
                if text in synonyms or any(syn in text for syn in synonyms):
                    return 6.0

        # Contains
        if goal in text or text in goal:
            return 4.0

        # Partial match (any word overlap)
        text_words = set(text.split())
        goal_words = set(goal.split())
        if text_words & goal_words:
            return 2.0

        return 0.0

    def _compute_size_score(self, bbox: BoundingBox) -> float:
        """
        Compute size appropriateness (0-3).

        Buttons/clickable elements are typically 50-300px wide.
        """
        width = bbox.width
        if 50 <= width <= 300:
            return 3.0
        elif 30 <= width < 50 or 300 < width <= 500:
            return 2.0
        elif 20 <= width < 30 or 500 < width <= 700:
            return 1.0
        else:
            return 0.0

    def _compute_position_score(
        self,
        bbox: BoundingBox,
        screen_width: int,
        screen_height: int
    ) -> float:
        """
        Compute position score (0-2).

        Elements in upper-left or center are more likely to be important.
        """
        center_x = bbox.x + bbox.width / 2
        center_y = bbox.y + bbox.height / 2

        # Normalize to 0-1
        norm_x = center_x / screen_width
        norm_y = center_y / screen_height

        # Prefer upper half and left half
        score = 0.0
        if norm_y < 0.5:  # Upper half
            score += 1.0
        if norm_x < 0.5:  # Left half
            score += 1.0

        return score

    def _compute_proximity_score(
        self,
        bbox: BoundingBox,
        last_pos: Tuple[int, int]
    ) -> float:
        """
        Compute proximity to last interaction (0-2).

        Elements near last click are more likely to be next target.
        """
        center_x = bbox.x + bbox.width / 2
        center_y = bbox.y + bbox.height / 2

        distance = ((center_x - last_pos[0]) ** 2 + (center_y - last_pos[1]) ** 2) ** 0.5

        # Closer = higher score
        if distance < 100:
            return 2.0
        elif distance < 300:
            return 1.0
        else:
            return 0.0


class ActionVerifier:
    """
    Verifies that desktop actions succeeded.

    Methods:
    1. Screenshot diff (pixel comparison)
    2. Window state change (title, focus)
    """

    async def verify_action(
        self,
        before_screenshot: str,
        actuator: DesktopActuator,
        timeout: float = 3.0
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Verify action succeeded by comparing screenshots.

        Args:
            before_screenshot: Path to screenshot before action
            actuator: DesktopActuator instance
            timeout: Max time to wait for change

        Returns:
            (success, method, metadata)
        """
        # Wait a bit for UI to update
        await asyncio.sleep(0.5)

        # Take new screenshot
        after_screenshot = before_screenshot.replace(".png", "_after.png")
        success, error, _ = await actuator.screenshot(after_screenshot)

        if not success:
            return (False, "screenshot_failed", {"error": error})

        # Compare screenshots
        diff_score = await self._compute_screenshot_diff(
            before_screenshot,
            after_screenshot
        )

        # If significant change detected, action succeeded
        if diff_score > 0.01:  # >1% pixels changed
            return (
                True,
                "screenshot_diff",
                {
                    "diff_score": diff_score,
                    "before": before_screenshot,
                    "after": after_screenshot
                }
            )

        return (False, "no_change_detected", {"diff_score": diff_score})

    async def _compute_screenshot_diff(
        self,
        img1_path: str,
        img2_path: str
    ) -> float:
        """
        Compute pixel-level difference between screenshots.

        Returns:
            Fraction of pixels that changed (0.0-1.0)
        """
        try:
            cv2 = _get_cv2()
            np = _get_numpy()
            if cv2 is None or np is None:
                logger.warning("[ActionVerifier] OpenCV not available, assuming change")
                return 0.5  # Assume success if can't verify

            # Load images
            img1 = await asyncio.to_thread(cv2.imread, img1_path)
            img2 = await asyncio.to_thread(cv2.imread, img2_path)

            if img1 is None or img2 is None:
                logger.error("[ActionVerifier] Failed to load screenshots")
                return 0.0

            # Convert to grayscale
            gray1 = await asyncio.to_thread(cv2.cvtColor, img1, cv2.COLOR_BGR2GRAY)
            gray2 = await asyncio.to_thread(cv2.cvtColor, img2, cv2.COLOR_BGR2GRAY)

            # Compute difference
            diff = await asyncio.to_thread(cv2.absdiff, gray1, gray2)

            # Threshold (ignore small changes)
            _, thresh = await asyncio.to_thread(cv2.threshold, diff, 30, 255, cv2.THRESH_BINARY)

            # Count changed pixels
            changed_pixels = np.sum(thresh > 0)
            total_pixels = thresh.shape[0] * thresh.shape[1]

            diff_score = changed_pixels / total_pixels

            logger.debug(
                f"[ActionVerifier] Screenshot diff: {diff_score:.4f} "
                f"({changed_pixels}/{total_pixels} pixels)"
            )

            return diff_score

        except Exception as e:
            logger.error(f"[ActionVerifier] Screenshot diff failed: {e}")
            return 0.0


class ComputerAgent:
    """
    Vision-guided desktop automation agent.

    Combines:
    - DesktopPerceptionEngine: Screen capture + OCR + shapes
    - TargetingPolicy: Rank candidates by goal
    - DesktopActuator: Mouse/keyboard actions
    - ActionVerifier: Screenshot diff verification

    Usage:
        agent = ComputerAgent(enable_ocr=True, enable_shapes=True)
        result = await agent.click("OK button")
        result = await agent.type_text("hello world", into="search box")
    """

    def __init__(
        self,
        enable_ocr: bool = True,
        enable_shapes: bool = True,
        enable_windows: bool = False,
        human_timing: bool = True
    ):
        """
        Initialize Computer Agent.

        Args:
            enable_ocr: Enable PaddleOCR text detection
            enable_shapes: Enable OpenCV shape detection
            enable_windows: Enable platform-specific window detection
            human_timing: Add human-like delays and movements
        """
        self.perception = DesktopPerceptionEngine(
            enable_ocr=enable_ocr,
            enable_shapes=enable_shapes,
            enable_windows=enable_windows
        )
        self.targeting = TargetingPolicy()
        self.actuator = DesktopActuator(human_timing=human_timing)
        self.verifier = ActionVerifier()

        logger.info(
            f"[ComputerAgent] Initialized (OCR={enable_ocr}, "
            f"Shapes={enable_shapes}, Windows={enable_windows})"
        )

    # ========================================================================
    # Main Actions
    # ========================================================================

    async def click(
        self,
        goal: str,
        max_attempts: int = 3,
        timeout: float = 30.0
    ) -> ActionResult:
        """
        Click a UI element matching the goal.

        Args:
            goal: Description of what to click (e.g., "OK button", "search icon")
            max_attempts: Max number of candidates to try
            timeout: Max time to spend

        Returns:
            ActionResult with success status and metadata
        """
        start_time = time.time()

        logger.info(f"[ComputerAgent] Clicking: '{goal}'")

        # 1. Take screenshot
        screenshot_path = tempfile.mktemp(suffix=".png", prefix="computer_agent_")
        screen_width, screen_height = await self.actuator.get_screen_size()

        success, error, _ = await self.actuator.screenshot(screenshot_path)
        if not success:
            return ActionResult(
                success=False,
                candidate=None,
                verification_method="screenshot_failed",
                metadata={"error": error}
            )

        # 2. Perception: Extract candidates
        candidates = await self.perception.extract_candidates(
            screenshot_path,
            screen_width,
            screen_height
        )

        if not candidates:
            return ActionResult(
                success=False,
                candidate=None,
                verification_method="no_candidates",
                metadata={"screenshot": screenshot_path}
            )

        # 3. Targeting: Rank by goal
        ranked = self.targeting.rank_candidates(
            candidates,
            goal,
            screen_width,
            screen_height
        )

        logger.info(
            f"[ComputerAgent] Found {len(ranked)} candidates, "
            f"top match: '{ranked[0].text}' (confidence={ranked[0].confidence:.3f})"
        )

        # 4. Try top candidates
        for attempt, candidate in enumerate(ranked[:max_attempts], 1):
            if time.time() - start_time > timeout:
                logger.warning(f"[ComputerAgent] Timeout after {timeout}s")
                break

            logger.info(
                f"[ComputerAgent] Attempt {attempt}/{max_attempts}: "
                f"Clicking '{candidate.text}' at ({candidate.bbox.x:.0f}, {candidate.bbox.y:.0f})"
            )

            # Before screenshot for verification
            before_screenshot = tempfile.mktemp(suffix=".png", prefix="before_")
            await self.actuator.screenshot(before_screenshot)

            # Execute click
            click_x = candidate.bbox.x + candidate.bbox.width / 2
            click_y = candidate.bbox.y + candidate.bbox.height / 2

            click_success, click_error = await self.actuator.click(
                int(click_x),
                int(click_y)
            )

            if not click_success:
                logger.warning(f"[ComputerAgent] Click failed: {click_error}")
                continue

            # Update last interaction position
            self.targeting.last_interaction_pos = (int(click_x), int(click_y))

            # Verify action
            verify_success, method, metadata = await self.verifier.verify_action(
                before_screenshot,
                self.actuator
            )

            if verify_success:
                logger.info(f"[ComputerAgent] Click succeeded ({method})")
                return ActionResult(
                    success=True,
                    candidate=candidate,
                    verification_method=method,
                    metadata={**metadata, "attempts": attempt}
                )

            logger.warning(f"[ComputerAgent] Verification failed ({method})")

        # All attempts failed
        return ActionResult(
            success=False,
            candidate=ranked[0] if ranked else None,
            verification_method="max_attempts_exceeded",
            metadata={"attempts": max_attempts, "candidates": len(ranked)}
        )

    async def type_text(
        self,
        text: str,
        into: Optional[str] = None,
        interval: float = 0.05
    ) -> ActionResult:
        """
        Type text, optionally clicking a target first.

        Args:
            text: Text to type
            into: Optional description of field to click first
            interval: Interval between keystrokes

        Returns:
            ActionResult with success status
        """
        logger.info(f"[ComputerAgent] Typing: '{text}' into='{into}'")

        # If target specified, click it first
        if into:
            click_result = await self.click(into)
            if not click_result.success:
                return ActionResult(
                    success=False,
                    candidate=None,
                    verification_method="click_failed",
                    metadata={"into": into}
                )

        # Type text
        before_screenshot = tempfile.mktemp(suffix=".png", prefix="before_type_")
        await self.actuator.screenshot(before_screenshot)

        success, error = await self.actuator.type_text(text, interval=interval)

        if not success:
            return ActionResult(
                success=False,
                candidate=None,
                verification_method="type_failed",
                metadata={"error": error}
            )

        # Verify
        verify_success, method, metadata = await self.verifier.verify_action(
            before_screenshot,
            self.actuator
        )

        return ActionResult(
            success=verify_success,
            candidate=None,
            verification_method=method,
            metadata=metadata
        )

    async def press_key(self, key: str, presses: int = 1) -> ActionResult:
        """
        Press a key.

        Args:
            key: Key name (e.g., "enter", "tab", "esc")
            presses: Number of times to press

        Returns:
            ActionResult with success status
        """
        logger.info(f"[ComputerAgent] Pressing key: '{key}' x{presses}")

        success, error = await self.actuator.press_key(key, presses=presses)

        if not success:
            return ActionResult(
                success=False,
                candidate=None,
                verification_method="press_failed",
                metadata={"error": error}
            )

        return ActionResult(
            success=True,
            candidate=None,
            verification_method="key_pressed",
            metadata={"key": key, "presses": presses}
        )

    async def scroll(self, clicks: int) -> ActionResult:
        """
        Scroll mouse wheel.

        Args:
            clicks: Number of scroll clicks (positive=up, negative=down)

        Returns:
            ActionResult with success status
        """
        logger.info(f"[ComputerAgent] Scrolling: {clicks} clicks")

        success, error = await self.actuator.scroll(clicks)

        if not success:
            return ActionResult(
                success=False,
                candidate=None,
                verification_method="scroll_failed",
                metadata={"error": error}
            )

        return ActionResult(
            success=True,
            candidate=None,
            verification_method="scrolled",
            metadata={"clicks": clicks}
        )
