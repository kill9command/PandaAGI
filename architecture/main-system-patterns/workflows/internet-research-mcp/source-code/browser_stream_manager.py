"""
Browser Stream Manager - Live browser streaming for remote CAPTCHA solving.

Streams Playwright browser frames via WebSocket and handles user interactions.
Allows users to interact with the server's browser from their phone/laptop.
"""

import asyncio
import base64
import logging
from typing import Dict, Optional, Any, Set
from datetime import datetime
from playwright.async_api import Page

logger = logging.getLogger(__name__)


class BrowserStream:
    """
    Manages live streaming of a Playwright page.

    Captures screenshots at regular intervals and sends to WebSocket clients.
    Receives user interactions (clicks, typing) and executes in Playwright.
    """

    def __init__(
        self,
        stream_id: str,
        page: Page,
        fps: int = 2
    ):
        self.stream_id = stream_id
        self.page = page
        self.fps = fps
        self.frame_interval = 1.0 / fps

        # WebSocket clients subscribed to this stream
        self.clients: Set[Any] = set()

        # Stream state
        self.streaming = False
        self.stream_task: Optional[asyncio.Task] = None
        self.created_at = datetime.utcnow()
        self.last_frame_at: Optional[datetime] = None

        logger.info(
            f"[BrowserStream] Created: {stream_id} (fps={fps})"
        )

    async def start_streaming(self):
        """Start streaming frames to connected clients."""
        if self.streaming:
            logger.warning(f"[BrowserStream] Already streaming: {self.stream_id}")
            return

        self.streaming = True
        self.stream_task = asyncio.create_task(self._stream_loop())
        logger.info(f"[BrowserStream] Started streaming: {self.stream_id}")

    async def stop_streaming(self):
        """Stop streaming frames."""
        if not self.streaming:
            return

        self.streaming = False
        if self.stream_task:
            self.stream_task.cancel()
            try:
                await self.stream_task
            except asyncio.CancelledError:
                pass

        logger.info(f"[BrowserStream] Stopped streaming: {self.stream_id}")

    async def _stream_loop(self):
        """Main streaming loop - captures and sends frames."""
        logger.info(f"[BrowserStream] Stream loop started: {self.stream_id}")

        try:
            while self.streaming:
                # Capture screenshot
                screenshot_bytes = await self.page.screenshot(type='jpeg', quality=80)
                screenshot_b64 = base64.b64encode(screenshot_bytes).decode('utf-8')

                # Get page dimensions
                viewport = self.page.viewport_size

                # Create frame message
                frame_msg = {
                    "type": "frame",
                    "stream_id": self.stream_id,
                    "image": screenshot_b64,
                    "format": "jpeg",
                    "width": viewport['width'] if viewport else 1280,
                    "height": viewport['height'] if viewport else 720,
                    "timestamp": datetime.utcnow().isoformat()
                }

                # Send to all connected clients
                await self._broadcast(frame_msg)

                self.last_frame_at = datetime.utcnow()

                # Wait for next frame
                await asyncio.sleep(self.frame_interval)

        except asyncio.CancelledError:
            logger.info(f"[BrowserStream] Stream loop cancelled: {self.stream_id}")
        except Exception as e:
            logger.error(f"[BrowserStream] Stream loop error: {e}", exc_info=True)

    async def _broadcast(self, message: Dict):
        """Send message to all connected WebSocket clients."""
        if not self.clients:
            return

        # Remove disconnected clients
        disconnected = set()

        for client in self.clients:
            try:
                await client.send_json(message)
            except Exception as e:
                logger.warning(f"[BrowserStream] Client send error: {e}")
                disconnected.add(client)

        # Clean up disconnected clients
        self.clients -= disconnected

    def add_client(self, websocket: Any):
        """Add WebSocket client to stream."""
        self.clients.add(websocket)
        logger.info(
            f"[BrowserStream] Client connected: {self.stream_id} "
            f"(total clients: {len(self.clients)})"
        )

    def remove_client(self, websocket: Any):
        """Remove WebSocket client from stream."""
        self.clients.discard(websocket)
        logger.info(
            f"[BrowserStream] Client disconnected: {self.stream_id} "
            f"(total clients: {len(self.clients)})"
        )

    async def handle_click(self, x: int, y: int):
        """
        Handle click event from user.

        Args:
            x: X coordinate (relative to page viewport)
            y: Y coordinate (relative to page viewport)
        """
        try:
            logger.info(f"[BrowserStream] Click at ({x}, {y})")
            await self.page.mouse.click(x, y)
        except Exception as e:
            logger.error(f"[BrowserStream] Click error: {e}", exc_info=True)

    async def handle_scroll(self, delta_x: int, delta_y: int):
        """
        Handle scroll event from user.

        Args:
            delta_x: Horizontal scroll delta
            delta_y: Vertical scroll delta
        """
        try:
            logger.info(f"[BrowserStream] Scroll delta=({delta_x}, {delta_y})")
            await self.page.mouse.wheel(delta_x, delta_y)
        except Exception as e:
            logger.error(f"[BrowserStream] Scroll error: {e}", exc_info=True)

    async def handle_typing(self, text: str):
        """
        Handle typing event from user.

        Args:
            text: Text to type
        """
        try:
            logger.info(f"[BrowserStream] Typing: {text[:20]}...")
            await self.page.keyboard.type(text)
        except Exception as e:
            logger.error(f"[BrowserStream] Typing error: {e}", exc_info=True)

    async def handle_keypress(self, key: str):
        """
        Handle keypress event from user.

        Args:
            key: Key name (e.g., 'Enter', 'Tab', 'Backspace')
        """
        try:
            logger.info(f"[BrowserStream] Keypress: {key}")
            await self.page.keyboard.press(key)
        except Exception as e:
            logger.error(f"[BrowserStream] Keypress error: {e}", exc_info=True)


class BrowserStreamManager:
    """
    Manages multiple browser streams.

    Creates streams for interventions and handles cleanup.
    """

    def __init__(self):
        self.streams: Dict[str, BrowserStream] = {}
        logger.info("[BrowserStreamManager] Initialized")

    async def create_stream(
        self,
        stream_id: str,
        page: Page,
        fps: int = 2
    ) -> BrowserStream:
        """
        Create a new browser stream.

        Args:
            stream_id: Unique stream identifier (e.g., intervention_id)
            page: Playwright page to stream
            fps: Frames per second (default: 2)

        Returns:
            BrowserStream instance
        """
        if stream_id in self.streams:
            logger.warning(f"[BrowserStreamManager] Stream already exists: {stream_id}")
            return self.streams[stream_id]

        stream = BrowserStream(
            stream_id=stream_id,
            page=page,
            fps=fps
        )

        self.streams[stream_id] = stream
        await stream.start_streaming()

        logger.info(f"[BrowserStreamManager] Created stream: {stream_id}")
        return stream

    async def stop_stream(self, stream_id: str):
        """Stop and remove a stream."""
        stream = self.streams.get(stream_id)
        if not stream:
            logger.warning(f"[BrowserStreamManager] Stream not found: {stream_id}")
            return

        await stream.stop_streaming()
        del self.streams[stream_id]

        logger.info(f"[BrowserStreamManager] Stopped stream: {stream_id}")

    def get_stream(self, stream_id: str) -> Optional[BrowserStream]:
        """Get stream by ID."""
        return self.streams.get(stream_id)

    async def cleanup_old_streams(self, max_age_seconds: int = 600):
        """Clean up streams older than max_age_seconds."""
        now = datetime.utcnow()
        to_remove = []

        for stream_id, stream in self.streams.items():
            age = (now - stream.created_at).total_seconds()
            if age > max_age_seconds:
                to_remove.append(stream_id)

        for stream_id in to_remove:
            await self.stop_stream(stream_id)

        if to_remove:
            logger.info(
                f"[BrowserStreamManager] Cleaned up {len(to_remove)} old streams"
            )


# Global manager instance
_stream_manager: Optional[BrowserStreamManager] = None


def get_browser_stream_manager() -> BrowserStreamManager:
    """Get global BrowserStreamManager instance."""
    global _stream_manager
    if _stream_manager is None:
        _stream_manager = BrowserStreamManager()
    return _stream_manager
