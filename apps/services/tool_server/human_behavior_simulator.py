"""
Human behavior simulation for anti-bot detection evasion.

Adds realistic human-like behaviors:
- Variable typing speeds (not robotic fixed delays)
- Mouse cursor movements before clicks
- Random pauses and hesitations
- Scrolling patterns
- Session warming (visit, wait, browse before target action)

Part of Panda's stealth web crawling system.
"""

import asyncio
import random
import math
from typing import Optional
from playwright.async_api import Page
import logging

logger = logging.getLogger(__name__)


class HumanBehaviorSimulator:
    """Simulates realistic human browsing behavior"""

    def __init__(self, page: Page, seed: Optional[str] = None):
        """
        Initialize behavior simulator.

        Args:
            page: Playwright Page instance
            seed: Optional seed for deterministic randomization
        """
        self.page = page
        self.rng = random.Random(seed) if seed else random.Random()

    async def type_like_human(
        self,
        text: str,
        element=None,
        min_delay_ms: int = 50,
        max_delay_ms: int = 180,
        mistake_probability: float = 0.02
    ):
        """
        Type text with human-like variable delays and occasional mistakes.

        Args:
            text: Text to type
            element: Optional element to type into (if None, types at current focus)
            min_delay_ms: Minimum delay between keystrokes (milliseconds)
            max_delay_ms: Maximum delay between keystrokes (milliseconds)
            mistake_probability: Probability of making a typo (0.0-1.0)
        """
        for i, char in enumerate(text):
            # Occasional typo followed by backspace
            if self.rng.random() < mistake_probability and i > 0:
                # Type wrong character
                wrong_chars = "qwertyuiopasdfghjklzxcvbnm"
                wrong_char = self.rng.choice(wrong_chars)
                await self.page.keyboard.type(wrong_char, delay=0)

                # Pause (human realizes mistake)
                await asyncio.sleep(self.rng.uniform(0.15, 0.35))

                # Backspace
                await self.page.keyboard.press("Backspace")
                await asyncio.sleep(self.rng.uniform(0.05, 0.15))

            # Type the actual character with variable delay
            delay = self.rng.uniform(min_delay_ms, max_delay_ms)

            # Longer pauses at word boundaries (space) or after punctuation
            if char in ' .,!?':
                delay *= self.rng.uniform(1.5, 2.5)

            await self.page.keyboard.type(char, delay=0)

            # Wait the calculated delay
            await asyncio.sleep(delay / 1000.0)

        logger.info(f"[HumanBehavior] Typed '{text}' with human-like timing")

    async def move_mouse_to_element(
        self,
        element,
        steps: int = 20,
        duration_ms: int = 500
    ):
        """
        Move mouse cursor to element with realistic bezier curve motion.

        Args:
            element: Playwright element to move to
            steps: Number of intermediate points (more = smoother)
            duration_ms: Total duration of movement
        """
        try:
            # Get element bounding box
            box = await element.bounding_box()
            if not box:
                logger.warning("[HumanBehavior] Element has no bounding box, skipping mouse movement")
                return

            # Target center of element (with small random offset for realism)
            target_x = box["x"] + box["width"] / 2 + self.rng.uniform(-5, 5)
            target_y = box["y"] + box["height"] / 2 + self.rng.uniform(-5, 5)

            # Get current viewport size to estimate starting position
            viewport = self.page.viewport_size
            if not viewport:
                viewport = {"width": 1920, "height": 1080}

            # Start from random position (simulate cursor was somewhere else)
            start_x = self.rng.uniform(100, viewport["width"] - 100)
            start_y = self.rng.uniform(100, viewport["height"] - 100)

            # Generate bezier curve points for realistic movement
            delay_per_step = duration_ms / steps / 1000.0

            for i in range(steps + 1):
                t = i / steps

                # Ease-in-out curve (slower at start/end, faster in middle)
                t_eased = self._ease_in_out_cubic(t)

                # Calculate position along curve
                x = start_x + (target_x - start_x) * t_eased
                y = start_y + (target_y - start_y) * t_eased

                # Add small random jitter (human hands aren't perfectly smooth)
                x += self.rng.uniform(-2, 2)
                y += self.rng.uniform(-2, 2)

                # Move mouse
                await self.page.mouse.move(x, y)

                # Small delay between movements
                await asyncio.sleep(delay_per_step)

            logger.info(f"[HumanBehavior] Moved mouse to element at ({target_x:.0f}, {target_y:.0f})")

        except Exception as e:
            logger.warning(f"[HumanBehavior] Mouse movement failed: {e}")

    async def click_like_human(
        self,
        element,
        move_mouse: bool = True,
        pause_before_click_ms: int = 100
    ):
        """
        Click element with human-like behavior (mouse movement + pause).

        Args:
            element: Element to click
            move_mouse: Whether to move mouse to element first
            pause_before_click_ms: Pause duration before clicking (milliseconds)
        """
        if move_mouse:
            await self.move_mouse_to_element(element, steps=20, duration_ms=400)

        # Small pause before clicking (humans don't click instantly)
        pause = self.rng.uniform(
            pause_before_click_ms / 1000.0,
            (pause_before_click_ms + 200) / 1000.0
        )
        await asyncio.sleep(pause)

        # Click the element
        await element.click()

        logger.info("[HumanBehavior] Clicked element with human-like behavior")

    async def warm_up_session(
        self,
        url: str,
        min_wait_seconds: float = 2.0,
        max_wait_seconds: float = 4.0,
        scroll: bool = True
    ):
        """
        Warm up session by visiting page and behaving like a human.

        This helps avoid detection by:
        - Not immediately performing automated actions
        - Showing natural browsing behavior
        - Building up session state

        Args:
            url: URL to visit
            min_wait_seconds: Minimum time to wait on page
            max_wait_seconds: Maximum time to wait on page
            scroll: Whether to scroll a bit (natural behavior)
        """
        logger.info(f"[HumanBehavior] Warming up session on {url}")

        # Navigate to page
        await self.page.goto(url, wait_until="domcontentloaded")

        # Wait for page to load (random duration)
        initial_wait = self.rng.uniform(0.5, 1.5)
        await asyncio.sleep(initial_wait)

        # Optionally scroll a bit (humans often scroll)
        if scroll:
            # Small scroll down
            scroll_y = self.rng.randint(100, 300)
            await self.page.evaluate(f"window.scrollBy(0, {scroll_y})")

            # Wait
            await asyncio.sleep(self.rng.uniform(0.5, 1.5))

            # Maybe scroll back up a bit
            if self.rng.random() < 0.3:
                scroll_y = -self.rng.randint(50, 150)
                await self.page.evaluate(f"window.scrollBy(0, {scroll_y})")
                await asyncio.sleep(self.rng.uniform(0.3, 0.8))

        # Final wait before allowing action
        final_wait = self.rng.uniform(min_wait_seconds, max_wait_seconds)
        await asyncio.sleep(final_wait)

        total_time = initial_wait + final_wait + (1.0 if scroll else 0.0)
        logger.info(f"[HumanBehavior] Session warmed up ({total_time:.1f}s)")

    def _ease_in_out_cubic(self, t: float) -> float:
        """
        Cubic ease-in-out function for smooth acceleration/deceleration.

        Args:
            t: Time parameter (0.0 to 1.0)

        Returns:
            Eased value (0.0 to 1.0)
        """
        if t < 0.5:
            return 4 * t * t * t
        else:
            return 1 - pow(-2 * t + 2, 3) / 2

    async def random_pause(
        self,
        min_seconds: float = 0.5,
        max_seconds: float = 2.0,
        reason: str = "thinking"
    ):
        """
        Random pause to simulate human hesitation/thinking.

        Args:
            min_seconds: Minimum pause duration
            max_seconds: Maximum pause duration
            reason: Reason for pause (for logging)
        """
        duration = self.rng.uniform(min_seconds, max_seconds)
        logger.debug(f"[HumanBehavior] Pausing for {duration:.2f}s ({reason})")
        await asyncio.sleep(duration)


# Convenience functions for common patterns

async def search_google_like_human(
    page: Page,
    query: str,
    warm_up: bool = True,
    seed: Optional[str] = None
) -> bool:
    """
    Perform Google search with human-like behavior.

    Args:
        page: Playwright page
        query: Search query
        warm_up: Whether to warm up session first
        seed: Optional seed for reproducible behavior

    Returns:
        True if search succeeded, False otherwise
    """
    simulator = HumanBehaviorSimulator(page, seed=seed)

    try:
        # Warm up session if requested
        if warm_up and page.url != "https://www.google.com":
            await simulator.warm_up_session(
                "https://www.google.com",
                min_wait_seconds=2.0,
                max_wait_seconds=4.0,
                scroll=True
            )

        # Find search box
        search_selectors = [
            'textarea[name="q"]',  # Google desktop
            'input[name="q"]',     # Google mobile
        ]

        search_box = None
        for selector in search_selectors:
            search_box = await page.query_selector(selector)
            if search_box:
                logger.info(f"[HumanBehavior] Found search box with selector: {selector}")
                break

        if not search_box:
            logger.error("[HumanBehavior] Could not find search box")
            return False

        # Click search box like a human
        await simulator.click_like_human(search_box, move_mouse=True, pause_before_click_ms=150)

        # Type query like a human
        await simulator.type_like_human(
            query,
            min_delay_ms=60,
            max_delay_ms=180,
            mistake_probability=0.01  # 1% chance of typo
        )

        # Pause before pressing Enter (humans don't immediately press Enter)
        await simulator.random_pause(0.3, 0.8, reason="reviewing query")

        # Press Enter
        await page.keyboard.press("Enter")

        # Wait for navigation
        await page.wait_for_load_state("domcontentloaded", timeout=10000)

        logger.info(f"[HumanBehavior] Completed Google search for: {query}")
        return True

    except Exception as e:
        logger.error(f"[HumanBehavior] Google search failed: {e}")
        return False
