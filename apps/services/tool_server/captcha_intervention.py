"""
CAPTCHA and auth blocker detection + intervention request system.

Detects when web pages are blocked by CAPTCHAs, login walls, or anti-bot
systems, and coordinates human intervention through async/await pattern.

Part of Pandora's human-in-the-loop research architecture.
"""

import asyncio
import logging
import uuid
import re
from enum import Enum
from typing import Dict, Optional, List, Any
from datetime import datetime
from urllib.parse import urlparse

from apps.services.tool_server.browser_session_registry import get_browser_session_registry

logger = logging.getLogger(__name__)


class InterventionType(str, Enum):
    """Types of blockers requiring human intervention"""
    CAPTCHA_RECAPTCHA = "captcha_recaptcha"
    CAPTCHA_HCAPTCHA = "captcha_hcaptcha"
    CAPTCHA_CLOUDFLARE = "captcha_cloudflare"
    CAPTCHA_GENERIC = "captcha_generic"
    LOGIN_REQUIRED = "login_required"
    AUTH_WALL = "auth_wall"
    RATE_LIMIT = "rate_limit"
    GEOFENCE = "geofence"
    BOT_DETECTION = "bot_detection"
    UNKNOWN_BLOCKER = "unknown_blocker"
    EXTRACTION_FAILED = "extraction_failed"  # Page loaded but couldn't extract data


class InterventionRequest:
    """
    Single intervention request awaiting user resolution.

    Implements async wait pattern: tool requests intervention, waits for
    user to resolve via UI, then continues with saved session state.
    """

    def __init__(
        self,
        intervention_id: str,
        intervention_type: InterventionType,
        url: str,
        screenshot_path: Optional[str],
        session_id: str,
        domain: str,
        blocker_details: Optional[Dict] = None,
        cdp_url: Optional[str] = None
    ):
        self.intervention_id = intervention_id
        self.intervention_type = intervention_type
        self.url = url
        self.screenshot_path = screenshot_path
        self.session_id = session_id
        self.domain = domain
        self.blocker_details = blocker_details or {}
        self.cdp_url = cdp_url  # CDP DevTools URL for viewing Playwright browser
        self.created_at = datetime.now()

        # Resolution state
        self.resolved = False
        self.resolution_success = False
        self.resolved_cookies: Optional[List[Dict]] = None
        self.resolved_at: Optional[datetime] = None
        self.skip_reason: Optional[str] = None

        # Asyncio event for waiting
        self._resolution_event = asyncio.Event()

        logger.info(
            f"[Intervention] Created: {intervention_id} for {domain} "
            f"(type={intervention_type.value})"
        )

    async def wait_for_resolution(self, timeout: float = 90) -> bool:
        """
        Wait for user to resolve intervention (blocks until resolved or timeout).

        Uses hybrid approach: Event-based for same-process, polling for cross-process.

        Args:
            timeout: Maximum wait time in seconds (default: 180 seconds)

        Returns:
            True if user successfully resolved, False if timeout or skipped
        """
        import json
        import os

        poll_interval = 2  # Check file every 2 seconds for cross-process resolution
        elapsed = 0

        logger.info(
            f"[Intervention] Waiting for resolution: {self.intervention_id} "
            f"(timeout={timeout}s)"
        )

        while elapsed < timeout:
            # Check if local event was set (same-process resolution)
            if self._resolution_event.is_set():
                logger.info(
                    f"[Intervention] Resolution received (in-process): {self.intervention_id} "
                    f"(success={self.resolution_success})"
                )
                return self.resolution_success

            # Check captcha_queue.json for cross-process resolution
            queue_file = os.path.join("panda_system_docs", "shared_state", "captcha_queue.json")
            if os.path.exists(queue_file):
                try:
                    with open(queue_file, 'r') as f:
                        pending_list = json.load(f)

                    # Check if our intervention is still pending
                    found = any(item.get("intervention_id") == self.intervention_id for item in pending_list)

                    if not found:
                        # Intervention removed from queue = resolved!
                        logger.info(
                            f"[Intervention] Resolution received (cross-process): {self.intervention_id}"
                        )
                        self.mark_resolved(success=True)
                        return True

                except Exception as e:
                    logger.warning(f"[Intervention] Error checking queue file: {e}")

            # Wait before next poll
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        # Timeout
        logger.warning(
            f"[Intervention] Timeout waiting for resolution: {self.intervention_id} "
            f"(waited {timeout}s)"
        )
        self.mark_resolved(success=False, skip_reason="timeout")
        return False

    def mark_resolved(
        self,
        success: bool,
        cookies: Optional[List[Dict]] = None,
        skip_reason: Optional[str] = None
    ):
        """
        Mark intervention as resolved by user.

        Args:
            success: Whether user successfully solved the blocker
            cookies: Session cookies captured after resolution (if applicable)
            skip_reason: Why intervention was skipped (if not successful)
        """
        self.resolved = True
        self.resolution_success = success
        self.resolved_cookies = cookies
        self.skip_reason = skip_reason
        self.resolved_at = datetime.now()

        # Resume browser session in registry
        try:
            registry = get_browser_session_registry()
            registry.mark_resumed(self.session_id)
            logger.debug(
                f"[Intervention] Resumed browser session: {self.session_id}"
            )
        except Exception as e:
            logger.warning(
                f"[Intervention] Could not resume browser session {self.session_id}: {e}"
            )

        # Wake up waiting tool
        self._resolution_event.set()

        resolution_time = (self.resolved_at - self.created_at).total_seconds()

        logger.info(
            f"[Intervention] Marked resolved: {self.intervention_id} "
            f"(success={success}, resolution_time={resolution_time:.1f}s)"
        )

    def to_dict(self) -> Dict:
        """Export as dictionary for SSE emission and API responses"""
        return {
            "intervention_id": self.intervention_id,
            "type": self.intervention_type.value,
            "url": self.url,
            "screenshot_path": self.screenshot_path,
            "session_id": self.session_id,
            "domain": self.domain,
            "blocker_details": self.blocker_details,
            "cdp_url": self.cdp_url,  # CDP DevTools URL for viewing Playwright browser
            "created_at": self.created_at.isoformat(),
            "resolved": self.resolved,
            "resolution_success": self.resolution_success if self.resolved else None,
            "resolution_time_seconds": (
                (self.resolved_at - self.created_at).total_seconds()
                if self.resolved_at else None
            )
        }


def detect_blocker(page_data: Dict) -> Optional[Dict]:
    """
    Detect if page is blocked by CAPTCHA, login wall, or anti-bot system.

    Uses heuristics based on:
    - HTTP status codes
    - Content patterns (keywords, iframe detection)
    - Page length
    - Response headers (if available)

    Args:
        page_data: Dict from playwright_stealth_mcp.fetch() containing:
            - content: Page HTML
            - status: HTTP status code
            - url: Final URL after redirects
            - screenshot_path: Path to screenshot (optional)

    Returns:
        Dict with blocker info if detected, None if page accessible
        {
            "type": InterventionType,
            "confidence": float (0.0-1.0),
            "indicators": List[str]  # What triggered detection
        }
    """
    content = page_data.get("content", "")
    content_lower = content.lower()
    status = page_data.get("status", 0)
    url = page_data.get("url", "")

    indicators = []

    # Priority 1: Known blocker URL patterns (highest confidence)
    # Check URL before content since URLs are definitive indicators
    blocker_url_patterns = [
        ("/sorry/", InterventionType.CAPTCHA_GENERIC, "Google CAPTCHA page"),
        ("google.com/sorry", InterventionType.CAPTCHA_GENERIC, "Google CAPTCHA page"),
        ("/static-pages/418", InterventionType.RATE_LIMIT, "DuckDuckGo rate limit (418)"),
        ("duckduckgo.com/static-pages/418", InterventionType.RATE_LIMIT, "DuckDuckGo rate limit (418)"),
        # Walmart and other retailers use /blocked path
        ("/blocked", InterventionType.CAPTCHA_GENERIC, "Retailer block page"),
        ("blocked?url=", InterventionType.CAPTCHA_GENERIC, "Retailer block page with redirect"),
        # Generic challenge paths
        ("/challenge", InterventionType.CAPTCHA_GENERIC, "Challenge page"),
        ("/verify", InterventionType.BOT_DETECTION, "Verification page"),
    ]

    for pattern, intervention_type, description in blocker_url_patterns:
        if pattern in url.lower():
            indicators.append(f"Known blocker URL: {description}")
            return {
                "type": intervention_type,
                "confidence": 0.95,  # High confidence - URL is definitive
                "indicators": indicators
            }

    # Priority 2: reCAPTCHA detection (high confidence)
    # NOTE: Many sites include invisible reCAPTCHA v3 for fraud prevention.
    # reCAPTCHA v3 is INVISIBLE and does NOT block users - it's passive scoring.
    # Only trigger if there's an ACTUAL VISIBLE challenge (v2 checkbox, image grid).
    #
    # How to distinguish:
    # - reCAPTCHA v3: Uses "render=" parameter, NO visible widget, passive scoring
    # - reCAPTCHA v2: Uses "data-sitekey" as HTML attribute (not JS var), HAS visible widget
    #
    # IMPORTANT: "sitekey" appearing in JavaScript variables (like wpcf7_recaptcha = {"sitekey":...})
    # is reCAPTCHA v3 for contact forms - NOT a blocking captcha!

    # Check for reCAPTCHA v3 (invisible) - these are NOT blocking
    is_recaptcha_v3 = (
        "recaptcha/api.js?render=" in content or  # v3 uses render parameter
        "grecaptcha.execute" in content or         # v3 programmatic execution
        'wpcf7_recaptcha' in content or            # WordPress Contact Form 7 v3
        'recaptcha/v3' in content_lower            # Explicit v3 reference
    )

    if is_recaptcha_v3:
        # reCAPTCHA v3 is invisible/passive - not a blocker
        # Don't trigger intervention for this
        pass
    elif "recaptcha" in content_lower or "g-recaptcha" in content:
        # Might be reCAPTCHA v2 - check for actual visible challenge widget
        recaptcha_v2_challenge_indicators = [
            # Actual visible widget elements (not JS variables)
            'class="g-recaptcha"',              # Visible widget div
            'class="recaptcha-checkbox"',       # Checkbox widget
            'class="rc-anchor"',                # reCAPTCHA anchor frame
            "recaptcha-anchor",                 # Checkbox anchor
            "rc-imageselect",                   # Image selection challenge
            "select all squares",               # Image challenge text
            "click verify once there are none left",  # Image challenge instruction
            "i'm not a robot",                  # Checkbox text
            'data-sitekey="',                   # HTML attribute (with quote - not JS var)
        ]

        # More strict: require VISIBLE widget indicators
        has_visible_widget = any(
            indicator in content_lower or indicator in content
            for indicator in recaptcha_v2_challenge_indicators
        )

        # Extra check: make sure it's not just a hidden form field
        # reCAPTCHA v3 uses hidden input "_wpcf7_recaptcha_response"
        is_just_hidden_field = (
            '_recaptcha_response' in content and
            not has_visible_widget
        )

        if has_visible_widget and not is_just_hidden_field:
            indicators.append("reCAPTCHA v2 challenge widget detected")
            return {
                "type": InterventionType.CAPTCHA_RECAPTCHA,
                "confidence": 0.95,
                "indicators": indicators
            }

    # Priority 3: hCaptcha detection (high confidence)
    # Similar to reCAPTCHA - only trigger on actual VISIBLE challenge, not just script presence
    if "hcaptcha" in content_lower or "h-captcha" in content:
        hcaptcha_challenge_indicators = [
            'class="h-captcha"',      # Visible widget div
            'data-sitekey="',         # HTML attribute (with quote - not JS var)
            "hcaptcha-box",           # Challenge box
            "hcaptcha-challenge",     # Challenge iframe
            "hcaptcha-iframe",        # Challenge iframe
        ]

        has_visible_widget = any(
            indicator in content_lower or indicator in content
            for indicator in hcaptcha_challenge_indicators
        )

        if has_visible_widget:
            indicators.append("hCaptcha challenge widget detected")
            return {
                "type": InterventionType.CAPTCHA_HCAPTCHA,
                "confidence": 0.95,
                "indicators": indicators
            }

    # Priority 4: Cloudflare challenge (high confidence)
    if "cloudflare" in content_lower:
        if any(keyword in content_lower for keyword in [
            "checking your browser",
            "challenge page",
            "why have i been blocked",
            "ray id:",
            "cloudflare-static/rocket-loader",
        ]):
            indicators.append("Cloudflare challenge page detected")
            return {
                "type": InterventionType.CAPTCHA_CLOUDFLARE,
                "confidence": 0.9,
                "indicators": indicators
            }

    # Priority 5: Generic CAPTCHA patterns
    # IMPORTANT: Skip generic detection if this is reCAPTCHA v3 (already checked above)
    # because v3 script URLs contain "captcha" but are NOT blocking
    if not is_recaptcha_v3:
        captcha_keywords = [
            # Be more specific - don't just match "captcha" anywhere
            # as it appears in script URLs for non-blocking v3
            "verify you are human",
            "prove you're not a robot",
            "i'm not a robot",  # reCAPTCHA checkbox text
            "robot or human",  # Walmart specific - "Robot or human?"
            "are you a robot",  # Common variant
            "are you human",  # Common variant
            "human verification",  # Generic
            "verify you're human",  # Variant with contraction
            "confirm you are human",  # Variant
            "press and hold",  # Walmart's "PRESS & HOLD" button
            "press & hold",  # Walmart variant
            "unusual traffic",  # Google's reCAPTCHA page text
            "detected unusual traffic from your computer",  # Google's reCAPTCHA page
            "security check",
            "bot check",
            "access verification",  # Generic challenge
            "unfortunately, bots use duckduckgo too",  # DuckDuckGo specific
            "select all squares containing",  # Image CAPTCHA
            "click each image containing",  # Image CAPTCHA variant
            "solve this puzzle",  # Generic puzzle CAPTCHA
            "complete the captcha",  # Explicit captcha instruction
            "enter the captcha",  # Explicit captcha instruction
            "captcha challenge",  # Captcha in challenge context
        ]
        for keyword in captcha_keywords:
            if keyword in content_lower:
                indicators.append(f"CAPTCHA keyword detected: '{keyword}'")
                return {
                    "type": InterventionType.CAPTCHA_GENERIC,
                    "confidence": 0.7,
                    "indicators": indicators
                }

    # Priority 6: Login/auth walls
    if status in [401, 403]:
        if any(keyword in content_lower for keyword in [
            "login",
            "sign in",
            "authenticate",
            "access denied",
            "unauthorized",
        ]):
            indicators.append(f"HTTP {status} with login keywords")
            return {
                "type": InterventionType.LOGIN_REQUIRED,
                "confidence": 0.85,
                "indicators": indicators
            }

    # Priority 7: Rate limiting
    if status == 429:
        indicators.append("HTTP 429 Too Many Requests")
        return {
            "type": InterventionType.RATE_LIMIT,
            "confidence": 1.0,
            "indicators": indicators
        }

    # Priority 8: Bot detection patterns
    # NOTE: These patterns are TOO BROAD - they match normal anti-bot scripts
    # that are present on pages but not actively blocking.
    # Only trigger on EXPLICIT blocking messages, not script references.
    bot_blocking_phrases = [
        "we have detected unusual traffic",  # Explicit blocking message
        "your access has been blocked",  # Explicit block
        "automated access detected",  # Explicit message (not just script)
        "this request was blocked",  # Explicit block
        "we noticed unusual activity",  # Explicit notice
        "please verify you're human",  # Explicit request (not covered by captcha keywords)
    ]
    for phrase in bot_blocking_phrases:
        if phrase in content_lower:
            indicators.append(f"Bot detection message: '{phrase}'")
            return {
                "type": InterventionType.BOT_DETECTION,
                "confidence": 0.85,
                "indicators": indicators
            }

    # Priority 9: Geofencing (location-based blocking)
    # NOTE: Removed "geolocation" - too broad, matches shipping/location features
    # Only match explicit blocking messages
    geofence_phrases = [
        "not available in your country",
        "not available in your region",
        "this content is not available in your area",
        "geo-restricted",
        "unavailable in your location",
    ]
    if status == 451 or any(phrase in content_lower for phrase in geofence_phrases):
        indicators.append("Geofencing detected")
        return {
            "type": InterventionType.GEOFENCE,
            "confidence": 0.8,
            "indicators": indicators
        }

    # Priority 10: Suspiciously short content (low confidence)
    if len(content.strip()) < 100 and status == 200:
        indicators.append(f"Suspiciously short content ({len(content)} bytes)")
        return {
            "type": InterventionType.UNKNOWN_BLOCKER,
            "confidence": 0.4,
            "indicators": indicators
        }

    # No blocker detected
    return None


async def request_intervention(
    blocker_type: str,
    url: str,
    screenshot_path: Optional[str],
    session_id: str,
    blocker_details: Optional[Dict] = None,
    cdp_url: Optional[str] = None
) -> InterventionRequest:
    """
    Create intervention request and register for user resolution.

    Args:
        blocker_type: Type of blocker (InterventionType enum value)
        url: Blocked URL
        screenshot_path: Path to screenshot of blocked page
        session_id: Current crawl session ID
        blocker_details: Additional blocker information (optional)
        cdp_url: CDP DevTools URL for viewing Playwright browser (optional)

    Returns:
        InterventionRequest object that tool can wait on
    """
    domain = urlparse(url).netloc
    intervention_id = str(uuid.uuid4())

    intervention = InterventionRequest(
        intervention_id=intervention_id,
        intervention_type=InterventionType(blocker_type),
        url=url,
        screenshot_path=screenshot_path,
        session_id=session_id,
        domain=domain,
        blocker_details=blocker_details,
        cdp_url=cdp_url
    )

    # Pause browser session in registry
    try:
        registry = get_browser_session_registry()
        registry.mark_paused(
            session_id=session_id,
            intervention_id=intervention_id,
            reason=blocker_type
        )
        logger.debug(
            f"[Intervention] Paused browser session: {session_id} "
            f"(intervention={intervention_id})"
        )
    except Exception as e:
        logger.warning(
            f"[Intervention] Could not pause browser session {session_id}: {e}"
        )

    # Register in global pending registry
    register_pending_intervention(intervention)

    logger.info(
        f"[Intervention] Registered: {intervention_id} for {domain} "
        f"(type={blocker_type}, session={session_id})"
    )

    return intervention


# ============================================================================
# Global Intervention Registry
# ============================================================================

_PENDING_INTERVENTIONS: Dict[str, InterventionRequest] = {}


def register_pending_intervention(intervention: InterventionRequest):
    """Add intervention to pending registry and persist to shared storage"""
    import json
    import os

    _PENDING_INTERVENTIONS[intervention.intervention_id] = intervention

    # Persist to shared storage for cross-process access (gateway needs to see these)
    queue_file = os.path.join("panda_system_docs", "shared_state", "captcha_queue.json")
    try:
        os.makedirs(os.path.dirname(queue_file), exist_ok=True)

        # Write all pending interventions to file
        pending_list = [i.to_dict() for i in _PENDING_INTERVENTIONS.values() if not i.resolved]
        with open(queue_file, 'w') as f:
            json.dump(pending_list, f, indent=2)

        logger.debug(
            f"[Registry] Persisted {len(pending_list)} interventions to {queue_file}"
        )
    except Exception as e:
        logger.error(f"[Registry] Failed to persist interventions: {e}")

    logger.debug(
        f"[Registry] Registered intervention: {intervention.intervention_id} "
        f"({len(_PENDING_INTERVENTIONS)} pending)"
    )


def get_pending_intervention(intervention_id: str) -> Optional[InterventionRequest]:
    """Get intervention by ID (loads from shared storage if needed for cross-process access)"""
    import json
    import os

    # Check in-memory registry first
    if intervention_id in _PENDING_INTERVENTIONS:
        return _PENDING_INTERVENTIONS[intervention_id]

    # Load from shared storage if not in memory (cross-process access)
    queue_file = os.path.join("panda_system_docs", "shared_state", "captcha_queue.json")
    if os.path.exists(queue_file):
        try:
            with open(queue_file, 'r') as f:
                pending_list = json.load(f)

            # Find matching intervention
            for item in pending_list:
                if item.get("intervention_id") == intervention_id:
                    # Reconstruct InterventionRequest object
                    type_value = item.get("type") or item.get("intervention_type")
                    intervention = InterventionRequest(
                        intervention_id=intervention_id,
                        intervention_type=InterventionType(type_value),
                        url=item["url"],
                        screenshot_path=item.get("screenshot_path"),
                        session_id=item["session_id"],
                        domain=item.get("domain", ""),
                        blocker_details=item.get("blocker_details"),
                        cdp_url=item.get("cdp_url")
                    )
                    intervention.created_at = datetime.fromisoformat(item["created_at"])

                    # Cache in memory for future calls
                    _PENDING_INTERVENTIONS[intervention_id] = intervention

                    logger.debug(
                        f"[Registry] Loaded intervention from file: {intervention_id}"
                    )
                    return intervention

        except Exception as e:
            logger.warning(f"[Registry] Failed to load intervention from file: {e}")

    return None


def remove_pending_intervention(intervention_id: str):
    """Remove intervention from registry and persist changes"""
    import json
    import os

    intervention = _PENDING_INTERVENTIONS.pop(intervention_id, None)
    if intervention:
        # Persist updated list to shared storage
        queue_file = os.path.join("panda_system_docs", "shared_state", "captcha_queue.json")
        try:
            pending_list = [i.to_dict() for i in _PENDING_INTERVENTIONS.values() if not i.resolved]
            with open(queue_file, 'w') as f:
                json.dump(pending_list, f, indent=2)
        except Exception as e:
            logger.error(f"[Registry] Failed to persist after removal: {e}")

        logger.debug(
            f"[Registry] Removed intervention: {intervention_id} "
            f"({len(_PENDING_INTERVENTIONS)} pending)"
        )


def get_all_pending_interventions(session_id: Optional[str] = None) -> List[InterventionRequest]:
    """Get all pending interventions, optionally filtered by session"""
    import json
    import os

    # If in-memory registry is empty, load from shared storage
    # (handles cross-process access - gateway reading orchestrator's interventions)
    if not _PENDING_INTERVENTIONS:
        queue_file = os.path.join("panda_system_docs", "shared_state", "captcha_queue.json")
        if os.path.exists(queue_file):
            try:
                with open(queue_file, 'r') as f:
                    pending_list = json.load(f)

                # Reconstruct InterventionRequest objects from dicts
                for item in pending_list:
                    intervention_id = item.get("intervention_id")
                    if intervention_id and intervention_id not in _PENDING_INTERVENTIONS:
                        # Create intervention object from dict
                        # Note: JSON file uses "type" field, not "intervention_type"
                        type_value = item.get("type") or item.get("intervention_type")
                        intervention = InterventionRequest(
                            intervention_id=intervention_id,
                            intervention_type=InterventionType(type_value),
                            url=item["url"],
                            screenshot_path=item.get("screenshot_path"),
                            session_id=item["session_id"],
                            domain=item.get("domain", ""),
                            blocker_details=item.get("blocker_details"),
                            cdp_url=item.get("cdp_url")
                        )
                        intervention.created_at = datetime.fromisoformat(item["created_at"])
                        _PENDING_INTERVENTIONS[intervention_id] = intervention

                logger.debug(f"[Registry] Loaded {len(pending_list)} interventions from shared storage")
            except Exception as e:
                logger.warning(f"[Registry] Failed to load interventions from file: {e}")

    if session_id:
        return [
            i for i in _PENDING_INTERVENTIONS.values()
            if i.session_id == session_id and not i.resolved
        ]
    return [i for i in _PENDING_INTERVENTIONS.values() if not i.resolved]


def get_intervention_stats() -> Dict[str, Any]:
    """Get statistics about interventions for monitoring"""
    all_interventions = list(_PENDING_INTERVENTIONS.values())

    pending = [i for i in all_interventions if not i.resolved]
    resolved_success = [i for i in all_interventions if i.resolved and i.resolution_success]
    resolved_failed = [i for i in all_interventions if i.resolved and not i.resolution_success]

    # Calculate average resolution time
    resolution_times = [
        (i.resolved_at - i.created_at).total_seconds()
        for i in resolved_success
        if i.resolved_at
    ]
    avg_resolution_time = (
        sum(resolution_times) / len(resolution_times)
        if resolution_times else 0
    )

    # Count by type
    type_counts = {}
    for i in all_interventions:
        type_counts[i.intervention_type.value] = type_counts.get(i.intervention_type.value, 0) + 1

    return {
        "total_interventions": len(all_interventions),
        "pending": len(pending),
        "resolved_success": len(resolved_success),
        "resolved_failed": len(resolved_failed),
        "avg_resolution_time_seconds": avg_resolution_time,
        "by_type": type_counts
    }
