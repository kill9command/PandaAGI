"""
orchestrator/browser_cdp_proxy.py

CDP (Chrome DevTools Protocol) WebSocket proxy for browser viewing/control.

Proxies CDP WebSocket connections between the web UI and Playwright browsers,
enabling users to view and control browser sessions from their laptop/phone.

Created: 2025-11-22
Part of: Browser Control Integration (Phase 2)
"""

import asyncio
import logging
import json
from typing import Dict, Optional, Any
from datetime import datetime

import websockets
from websockets.legacy.server import WebSocketServerProtocol
from websockets.legacy.client import WebSocketClientProtocol

from apps.services.tool_server.browser_session_registry import get_browser_session_registry, BrowserSession

logger = logging.getLogger(__name__)


class CDPProxy:
    """
    WebSocket proxy for Chrome DevTools Protocol connections.

    Forwards CDP messages bidirectionally between:
    - Web UI (viewer) → Playwright browser
    - Playwright browser → Web UI (viewer)

    Enables remote browser viewing and control.
    """

    def __init__(self):
        self.active_proxies: Dict[str, Dict[str, Any]] = {}
        logger.info("[CDPProxy] Initialized")

    async def create_proxy_connection(
        self,
        session_id: str,
        viewer_ws: WebSocketServerProtocol
    ) -> bool:
        """
        Create proxy connection between viewer and browser.

        Args:
            session_id: Browser session ID to attach to
            viewer_ws: WebSocket connection from viewer (UI)

        Returns:
            True if proxy established successfully, False otherwise
        """
        registry = get_browser_session_registry()
        session = registry.get_session(session_id)

        if not session:
            logger.warning(f"[CDPProxy] Session not found: {session_id}")
            await viewer_ws.send(json.dumps({
                "error": "session_not_found",
                "message": f"Browser session '{session_id}' not found"
            }))
            return False

        if not session.cdp_url:
            logger.warning(f"[CDPProxy] No CDP URL for session: {session_id}")
            await viewer_ws.send(json.dumps({
                "error": "cdp_not_available",
                "message": "CDP not enabled for this session"
            }))
            return False

        try:
            # Connect to Playwright browser's CDP endpoint
            browser_ws = await websockets.connect(
                session.cdp_url,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5
            )

            logger.info(
                f"[CDPProxy] Connected to browser CDP: {session_id} "
                f"(cdp_url={session.cdp_url})"
            )

            # Store proxy connection info
            self.active_proxies[session_id] = {
                "viewer_ws": viewer_ws,
                "browser_ws": browser_ws,
                "session": session,
                "connected_at": datetime.utcnow(),
                "messages_forwarded": 0
            }

            # Start bidirectional forwarding
            await self._forward_bidirectionally(session_id, viewer_ws, browser_ws)

            return True

        except Exception as e:
            logger.error(f"[CDPProxy] Failed to connect to browser CDP: {e}", exc_info=True)
            await viewer_ws.send(json.dumps({
                "error": "connection_failed",
                "message": f"Failed to connect to browser: {e}"
            }))
            return False

    async def _forward_bidirectionally(
        self,
        session_id: str,
        viewer_ws: WebSocketServerProtocol,
        browser_ws: WebSocketClientProtocol
    ):
        """
        Forward CDP messages bidirectionally between viewer and browser.

        Runs two async tasks:
        - Viewer → Browser (user CDP commands)
        - Browser → Viewer (browser events, responses)
        """
        async def forward_viewer_to_browser():
            """Forward messages from viewer to browser"""
            try:
                async for message in viewer_ws:
                    try:
                        # Parse and validate CDP message
                        if isinstance(message, str):
                            cdp_msg = json.loads(message)
                        else:
                            cdp_msg = json.loads(message.decode('utf-8'))

                        # Security: Block dangerous CDP methods
                        method = cdp_msg.get("method", "")
                        if self._is_method_blocked(method):
                            logger.warning(
                                f"[CDPProxy] Blocked dangerous method: {method} "
                                f"(session={session_id})"
                            )
                            await viewer_ws.send(json.dumps({
                                "id": cdp_msg.get("id"),
                                "error": {
                                    "code": -32000,
                                    "message": f"Method '{method}' is blocked for security"
                                }
                            }))
                            continue

                        # Forward to browser
                        await browser_ws.send(json.dumps(cdp_msg))

                        # Update stats
                        if session_id in self.active_proxies:
                            self.active_proxies[session_id]["messages_forwarded"] += 1

                        logger.debug(
                            f"[CDPProxy] Viewer→Browser: {method or 'response'} "
                            f"(session={session_id})"
                        )

                    except json.JSONDecodeError as e:
                        logger.warning(f"[CDPProxy] Invalid JSON from viewer: {e}")
                    except Exception as e:
                        logger.error(f"[CDPProxy] Error forwarding to browser: {e}")

            except websockets.exceptions.ConnectionClosed:
                logger.info(f"[CDPProxy] Viewer connection closed: {session_id}")
            except Exception as e:
                logger.error(f"[CDPProxy] Viewer→Browser forwarding error: {e}")

        async def forward_browser_to_viewer():
            """Forward messages from browser to viewer"""
            try:
                async for message in browser_ws:
                    try:
                        # Forward to viewer
                        if isinstance(message, bytes):
                            await viewer_ws.send(message)
                        else:
                            await viewer_ws.send(message)

                        # Update stats
                        if session_id in self.active_proxies:
                            self.active_proxies[session_id]["messages_forwarded"] += 1

                        logger.debug(f"[CDPProxy] Browser→Viewer (session={session_id})")

                    except Exception as e:
                        logger.error(f"[CDPProxy] Error forwarding to viewer: {e}")

            except websockets.exceptions.ConnectionClosed:
                logger.info(f"[CDPProxy] Browser connection closed: {session_id}")
            except Exception as e:
                logger.error(f"[CDPProxy] Browser→Viewer forwarding error: {e}")

        try:
            # Run both forwarding tasks concurrently
            await asyncio.gather(
                forward_viewer_to_browser(),
                forward_browser_to_viewer()
            )
        finally:
            # Cleanup
            await self._cleanup_proxy(session_id)

    def _is_method_blocked(self, method: str) -> bool:
        """
        Check if CDP method should be blocked for security.

        Blocks dangerous methods that could compromise the system:
        - File system access
        - Network interception
        - Process control
        - Extension installation

        Args:
            method: CDP method name (e.g., "Page.navigate")

        Returns:
            True if method should be blocked, False if allowed
        """
        blocked_methods = [
            # File system access
            "IO.read",
            "IO.write",

            # Network interception
            "Fetch.enable",
            "Fetch.continueRequest",
            "Fetch.fulfillRequest",
            "Fetch.failRequest",

            # Process/system control
            "Browser.close",
            "Target.closeTarget",
            "SystemInfo.getProcessInfo",

            # Extension installation
            "Target.createTarget",
        ]

        return method in blocked_methods

    async def _cleanup_proxy(self, session_id: str):
        """Clean up proxy connection and close WebSockets"""
        if session_id in self.active_proxies:
            proxy_info = self.active_proxies[session_id]

            # Close WebSockets
            try:
                await proxy_info["viewer_ws"].close()
            except:
                pass

            try:
                await proxy_info["browser_ws"].close()
            except:
                pass

            # Log stats
            messages_forwarded = proxy_info.get("messages_forwarded", 0)
            duration = (datetime.utcnow() - proxy_info["connected_at"]).total_seconds()

            logger.info(
                f"[CDPProxy] Closed proxy: {session_id} "
                f"(messages={messages_forwarded}, duration={duration:.1f}s)"
            )

            # Remove from active proxies
            del self.active_proxies[session_id]

    def get_active_proxies(self) -> list:
        """Get list of active proxy sessions"""
        return [
            {
                "session_id": session_id,
                "connected_at": info["connected_at"].isoformat(),
                "messages_forwarded": info["messages_forwarded"],
                "session_url": info["session"].current_url
            }
            for session_id, info in self.active_proxies.items()
        ]

    def get_stats(self) -> Dict[str, Any]:
        """Get proxy statistics"""
        return {
            "active_connections": len(self.active_proxies),
            "total_messages_forwarded": sum(
                info["messages_forwarded"]
                for info in self.active_proxies.values()
            )
        }


# Global singleton instance
_proxy_instance: Optional[CDPProxy] = None
_proxy_lock = asyncio.Lock()


async def get_cdp_proxy() -> CDPProxy:
    """
    Get the global CDP proxy (singleton).

    Thread-safe lazy initialization.
    """
    global _proxy_instance
    if _proxy_instance is None:
        async with _proxy_lock:
            if _proxy_instance is None:
                _proxy_instance = CDPProxy()
    return _proxy_instance
