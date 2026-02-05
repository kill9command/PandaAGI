"""
orchestrator/desktop_actuator.py

Desktop Actuator - Cross-platform computer control via pyautogui

Provides keyboard/mouse actions for desktop automation:
- Mouse: move, click, drag, scroll
- Keyboard: type, press, hotkeys
- Screenshots: capture, locate

Works on: Windows, macOS, Linux (via pyautogui)
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Tuple, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Lazy-load pyautogui (only when actually used)
_pyautogui = None


def _get_pyautogui():
    """Lazy-load pyautogui to avoid import errors if not installed."""
    global _pyautogui
    if _pyautogui is None:
        try:
            import pyautogui
            _pyautogui = pyautogui
            # Safety settings
            _pyautogui.PAUSE = 0.1  # 100ms between actions
            _pyautogui.FAILSAFE = True  # Move mouse to corner to abort
        except ImportError:
            logger.error("pyautogui not installed. Run: pip install pyautogui")
            raise ImportError("pyautogui required for desktop automation")
    return _pyautogui


@dataclass
class ScreenRegion:
    """Screen region for area-specific operations."""
    x: int
    y: int
    width: int
    height: int


class DesktopActuator:
    """
    Cross-platform desktop automation via pyautogui.

    Provides low-level mouse/keyboard actions for ComputerAgent.
    All methods are async for consistency with web agent.
    """

    def __init__(self, human_timing: bool = True):
        """
        Initialize desktop actuator.

        Args:
            human_timing: Add human-like delays and movements
        """
        self.human_timing = human_timing
        self.last_mouse_pos: Optional[Tuple[int, int]] = None
        self._pyautogui = None

    def _ensure_pyautogui(self):
        """Ensure pyautogui is loaded."""
        if self._pyautogui is None:
            self._pyautogui = _get_pyautogui()
        return self._pyautogui

    # ========================================================================
    # Mouse Actions
    # ========================================================================

    async def move_mouse(
        self,
        x: int,
        y: int,
        duration: float = 0.2,
        use_human_curve: bool = None
    ) -> Tuple[bool, str]:
        """
        Move mouse to position.

        Args:
            x: Target X coordinate
            y: Target Y coordinate
            duration: Movement duration (seconds)
            use_human_curve: Use human-like movement curve (default: self.human_timing)

        Returns:
            (success, error_message)
        """
        try:
            pg = self._ensure_pyautogui()

            if use_human_curve is None:
                use_human_curve = self.human_timing

            if use_human_curve:
                # Use tweening for human-like movement
                await asyncio.to_thread(
                    pg.moveTo, x, y, duration=duration, tween=pg.easeOutQuad
                )
            else:
                await asyncio.to_thread(pg.moveTo, x, y, duration=0)

            self.last_mouse_pos = (x, y)
            logger.debug(f"[DesktopActuator] Mouse moved to ({x}, {y})")
            return (True, "")

        except Exception as e:
            logger.error(f"[DesktopActuator] Mouse move failed: {e}")
            return (False, str(e))

    async def click(
        self,
        x: Optional[int] = None,
        y: Optional[int] = None,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.0
    ) -> Tuple[bool, str]:
        """
        Click mouse at position.

        Args:
            x: X coordinate (None = current position)
            y: Y coordinate (None = current position)
            button: "left", "right", or "middle"
            clicks: Number of clicks (1=single, 2=double)
            interval: Interval between clicks (seconds)

        Returns:
            (success, error_message)
        """
        try:
            pg = self._ensure_pyautogui()

            if x is not None and y is not None:
                # Move then click
                success, error = await self.move_mouse(x, y, duration=0.2)
                if not success:
                    return (False, error)

            await asyncio.to_thread(pg.click, button=button, clicks=clicks, interval=interval)

            logger.info(f"[DesktopActuator] Clicked {button} button at ({x}, {y})")
            return (True, "")

        except Exception as e:
            logger.error(f"[DesktopActuator] Click failed: {e}")
            return (False, str(e))

    async def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.5,
        button: str = "left"
    ) -> Tuple[bool, str]:
        """
        Drag mouse from start to end position.

        Args:
            start_x: Start X coordinate
            start_y: Start Y coordinate
            end_x: End X coordinate
            end_y: End Y coordinate
            duration: Drag duration (seconds)
            button: Mouse button to hold

        Returns:
            (success, error_message)
        """
        try:
            pg = self._ensure_pyautogui()

            # Move to start
            await self.move_mouse(start_x, start_y, duration=0.2)

            # Drag to end
            await asyncio.to_thread(
                pg.drag,
                end_x - start_x,
                end_y - start_y,
                duration=duration,
                button=button,
                tween=pg.easeOutQuad if self.human_timing else pg.linear
            )

            logger.info(f"[DesktopActuator] Dragged from ({start_x},{start_y}) to ({end_x},{end_y})")
            return (True, "")

        except Exception as e:
            logger.error(f"[DesktopActuator] Drag failed: {e}")
            return (False, str(e))

    async def scroll(
        self,
        clicks: int,
        x: Optional[int] = None,
        y: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        Scroll mouse wheel.

        Args:
            clicks: Number of scroll clicks (positive=up, negative=down)
            x: X position to scroll at (None=current)
            y: Y position to scroll at (None=current)

        Returns:
            (success, error_message)
        """
        try:
            pg = self._ensure_pyautogui()

            if x is not None and y is not None:
                await self.move_mouse(x, y, duration=0.1)

            await asyncio.to_thread(pg.scroll, clicks)

            direction = "up" if clicks > 0 else "down"
            logger.info(f"[DesktopActuator] Scrolled {direction} ({abs(clicks)} clicks)")
            return (True, "")

        except Exception as e:
            logger.error(f"[DesktopActuator] Scroll failed: {e}")
            return (False, str(e))

    # ========================================================================
    # Keyboard Actions
    # ========================================================================

    async def type_text(
        self,
        text: str,
        interval: float = 0.05
    ) -> Tuple[bool, str]:
        """
        Type text with keyboard.

        Args:
            text: Text to type
            interval: Interval between keystrokes (seconds)

        Returns:
            (success, error_message)
        """
        try:
            pg = self._ensure_pyautogui()

            if self.human_timing:
                # Variable human-like typing speed
                await asyncio.to_thread(pg.write, text, interval=interval)
            else:
                await asyncio.to_thread(pg.write, text, interval=0)

            logger.info(f"[DesktopActuator] Typed: {text[:50]}...")
            return (True, "")

        except Exception as e:
            logger.error(f"[DesktopActuator] Type failed: {e}")
            return (False, str(e))

    async def press_key(
        self,
        key: str,
        presses: int = 1,
        interval: float = 0.0
    ) -> Tuple[bool, str]:
        """
        Press a single key.

        Args:
            key: Key name (e.g., "enter", "esc", "tab", "space", "a", "1")
            presses: Number of times to press
            interval: Interval between presses

        Returns:
            (success, error_message)
        """
        try:
            pg = self._ensure_pyautogui()

            await asyncio.to_thread(pg.press, key, presses=presses, interval=interval)

            logger.info(f"[DesktopActuator] Pressed '{key}' {presses} time(s)")
            return (True, "")

        except Exception as e:
            logger.error(f"[DesktopActuator] Press key failed: {e}")
            return (False, str(e))

    async def hotkey(
        self,
        *keys: str,
        interval: float = 0.05
    ) -> Tuple[bool, str]:
        """
        Press multiple keys simultaneously (hotkey combo).

        Args:
            keys: Keys to press together (e.g., "ctrl", "c")
            interval: Interval between key presses

        Returns:
            (success, error_message)
        """
        try:
            pg = self._ensure_pyautogui()

            await asyncio.to_thread(pg.hotkey, *keys, interval=interval)

            key_combo = "+".join(keys)
            logger.info(f"[DesktopActuator] Hotkey: {key_combo}")
            return (True, "")

        except Exception as e:
            logger.error(f"[DesktopActuator] Hotkey failed: {e}")
            return (False, str(e))

    # ========================================================================
    # Screen Actions
    # ========================================================================

    async def screenshot(
        self,
        filename: Optional[str] = None,
        region: Optional[ScreenRegion] = None
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Capture screenshot.

        Args:
            filename: Path to save screenshot (None = return PIL image)
            region: Specific region to capture (None = full screen)

        Returns:
            (success, error_message, image_path or None)
        """
        try:
            pg = self._ensure_pyautogui()

            if region:
                region_tuple = (region.x, region.y, region.width, region.height)
            else:
                region_tuple = None

            if filename:
                await asyncio.to_thread(pg.screenshot, filename, region=region_tuple)
                logger.info(f"[DesktopActuator] Screenshot saved: {filename}")
                return (True, "", filename)
            else:
                img = await asyncio.to_thread(pg.screenshot, region=region_tuple)
                logger.info(f"[DesktopActuator] Screenshot captured (PIL image)")
                return (True, "", None)

        except Exception as e:
            logger.error(f"[DesktopActuator] Screenshot failed: {e}")
            return (False, str(e), None)

    async def locate_on_screen(
        self,
        needle_image: str,
        confidence: float = 0.8,
        grayscale: bool = True
    ) -> Tuple[bool, str, Optional[Tuple[int, int, int, int]]]:
        """
        Find image on screen (template matching).

        Args:
            needle_image: Path to image to find
            confidence: Match confidence (0.0-1.0)
            grayscale: Convert to grayscale for faster matching

        Returns:
            (success, error_message, (left, top, width, height) or None)
        """
        try:
            pg = self._ensure_pyautogui()

            location = await asyncio.to_thread(
                pg.locateOnScreen,
                needle_image,
                confidence=confidence,
                grayscale=grayscale
            )

            if location:
                logger.info(
                    f"[DesktopActuator] Found image at "
                    f"({location.left}, {location.top}, {location.width}, {location.height})"
                )
                return (True, "", (location.left, location.top, location.width, location.height))
            else:
                logger.warning(f"[DesktopActuator] Image not found: {needle_image}")
                return (False, "image_not_found", None)

        except Exception as e:
            logger.error(f"[DesktopActuator] Locate on screen failed: {e}")
            return (False, str(e), None)

    # ========================================================================
    # Utility Functions
    # ========================================================================

    async def get_screen_size(self) -> Tuple[int, int]:
        """Get screen resolution (width, height)."""
        try:
            pg = self._ensure_pyautogui()
            size = await asyncio.to_thread(pg.size)
            return (size.width, size.height)
        except Exception as e:
            logger.error(f"[DesktopActuator] Get screen size failed: {e}")
            return (1920, 1080)  # Default

    async def get_mouse_position(self) -> Tuple[int, int]:
        """Get current mouse position."""
        try:
            pg = self._ensure_pyautogui()
            pos = await asyncio.to_thread(pg.position)
            return (pos.x, pos.y)
        except Exception as e:
            logger.error(f"[DesktopActuator] Get mouse position failed: {e}")
            return (0, 0)

    async def wait(self, seconds: float):
        """Wait/sleep for specified duration."""
        await asyncio.sleep(seconds)
