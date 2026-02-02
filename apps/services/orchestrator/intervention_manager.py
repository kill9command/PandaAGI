"""
orchestrator/intervention_manager.py

Manages human interventions for blocked web research (captchas, geo-fences, etc).
Uses async Future pattern to pause research until human resolves the blocker.
"""
from __future__ import annotations
import asyncio
import logging
import uuid
from typing import Dict, Any, Optional
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class InterventionStatus(Enum):
    """Status of an intervention request."""
    PENDING = "pending"
    SOLVED = "solved"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class Intervention:
    """
    Represents a single intervention request.

    Uses asyncio.Future to block research until human resolves the issue.
    """

    def __init__(
        self,
        intervention_id: str,
        blocker_type: str,
        url: str,
        screenshot_path: Optional[str] = None,
        blocker_details: Optional[Dict[str, Any]] = None
    ):
        self.intervention_id = intervention_id
        self.blocker_type = blocker_type
        self.url = url
        self.screenshot_path = screenshot_path
        self.blocker_details = blocker_details or {}
        self.status = InterventionStatus.PENDING
        self.created_at = datetime.utcnow()
        self.resolved_at: Optional[datetime] = None
        self.resolution_data: Dict[str, Any] = {}

        # Future to await resolution
        self.future: asyncio.Future = asyncio.Future()

    async def wait_for_resolution(self, timeout: float = 180) -> bool:
        """
        Wait for human to resolve the intervention.

        Args:
            timeout: Maximum time to wait in seconds (default: 180 seconds)

        Returns:
            True if resolved successfully, False if timeout/skipped/cancelled
        """
        try:
            # Wait for future with timeout
            await asyncio.wait_for(self.future, timeout=timeout)
            return self.status == InterventionStatus.SOLVED
        except asyncio.TimeoutError:
            logger.warning(
                f"[Intervention] Timeout waiting for resolution: {self.intervention_id} "
                f"(waited {timeout}s)"
            )
            self.status = InterventionStatus.TIMEOUT
            self.resolved_at = datetime.utcnow()
            return False
        except Exception as e:
            logger.error(f"[Intervention] Error waiting for resolution: {e}")
            return False

    def resolve(self, action: str, data: Optional[Dict[str, Any]] = None):
        """
        Mark intervention as resolved.

        Args:
            action: Action taken (solved, skipped, cancelled)
            data: Optional resolution data (cookies, session state, etc.)
        """
        if self.future.done():
            logger.warning(f"[Intervention] Already resolved: {self.intervention_id}")
            return

        if action == "solved":
            self.status = InterventionStatus.SOLVED
        elif action == "skipped":
            self.status = InterventionStatus.SKIPPED
        elif action == "cancelled":
            self.status = InterventionStatus.CANCELLED
        else:
            logger.warning(f"[Intervention] Unknown action: {action}")
            self.status = InterventionStatus.SKIPPED

        self.resolved_at = datetime.utcnow()
        self.resolution_data = data or {}

        # Signal the waiting task
        self.future.set_result(True)

        logger.info(
            f"[Intervention] Resolved: {self.intervention_id} "
            f"(action={action}, status={self.status.value})"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "intervention_id": self.intervention_id,
            "blocker_type": self.blocker_type,
            "url": self.url,
            "screenshot_path": self.screenshot_path,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolution_data": self.resolution_data,
            "blocker_details": self.blocker_details
        }


class InterventionManager:
    """
    Manages active intervention requests.

    Responsibilities:
    - Create intervention requests
    - Track pending interventions
    - Resolve interventions based on user actions
    - Emit events to WebSocket clients
    """

    def __init__(self, event_emitter: Optional[Any] = None):
        """
        Initialize intervention manager.

        Args:
            event_emitter: Optional ResearchEventEmitter for broadcasting events
        """
        self.event_emitter = event_emitter
        self.interventions: Dict[str, Intervention] = {}

    async def request_intervention(
        self,
        blocker_type: str,
        url: str,
        screenshot_path: Optional[str] = None,
        blocker_details: Optional[Dict[str, Any]] = None
    ) -> Intervention:
        """
        Request human intervention for a blocked page.

        Args:
            blocker_type: Type of blocker (captcha, geofence, etc.)
            url: URL that's blocked
            screenshot_path: Path to screenshot of blocked page
            blocker_details: Additional blocker information

        Returns:
            Intervention object (can await .wait_for_resolution())
        """
        intervention_id = str(uuid.uuid4())
        intervention = Intervention(
            intervention_id=intervention_id,
            blocker_type=blocker_type,
            url=url,
            screenshot_path=screenshot_path,
            blocker_details=blocker_details
        )

        # Store intervention
        self.interventions[intervention_id] = intervention

        # Emit event to dashboard
        if self.event_emitter:
            await self.event_emitter.emit_intervention_needed(
                intervention_id=intervention_id,
                url=url,
                blocker_type=blocker_type,
                screenshot_path=screenshot_path
            )

        logger.info(
            f"[InterventionManager] Requested intervention: {intervention_id} "
            f"(type={blocker_type}, url={url[:60]})"
        )

        return intervention

    async def resolve_intervention(
        self,
        intervention_id: str,
        action: str,
        data: Optional[Dict[str, Any]] = None
    ):
        """
        Resolve an intervention request.

        Args:
            intervention_id: Intervention identifier
            action: Action taken (solved, skipped, cancelled)
            data: Optional resolution data
        """
        intervention = self.interventions.get(intervention_id)
        if not intervention:
            logger.warning(f"[InterventionManager] Unknown intervention: {intervention_id}")
            return

        intervention.resolve(action, data)

        # Emit event to dashboard
        if self.event_emitter:
            await self.event_emitter.emit_intervention_resolved(
                intervention_id=intervention_id,
                action=action,
                success=(action == "solved")
            )

    def get_intervention(self, intervention_id: str) -> Optional[Intervention]:
        """Get intervention by ID."""
        return self.interventions.get(intervention_id)

    def get_pending_interventions(self) -> list[Intervention]:
        """Get all pending interventions."""
        return [
            i for i in self.interventions.values()
            if i.status == InterventionStatus.PENDING
        ]

    def get_all_interventions(self) -> list[Intervention]:
        """Get all interventions."""
        return list(self.interventions.values())

    def clear_old_interventions(self, max_age_seconds: int = 3600):
        """Clear interventions older than max_age_seconds."""
        now = datetime.utcnow()
        to_remove = []
        for intervention_id, intervention in self.interventions.items():
            age = (now - intervention.created_at).total_seconds()
            if age > max_age_seconds and intervention.status != InterventionStatus.PENDING:
                to_remove.append(intervention_id)

        for intervention_id in to_remove:
            del self.interventions[intervention_id]

        if to_remove:
            logger.info(f"[InterventionManager] Cleared {len(to_remove)} old interventions")


# Global registry of intervention managers by session_id
_intervention_managers: Dict[str, InterventionManager] = {}


def get_intervention_manager(session_id: str) -> Optional[InterventionManager]:
    """Get intervention manager for a specific session."""
    return _intervention_managers.get(session_id)


def register_intervention_manager(session_id: str, manager: InterventionManager):
    """Register an intervention manager for a session."""
    _intervention_managers[session_id] = manager
    logger.info(f"[InterventionRegistry] Registered manager for session {session_id}")


def unregister_intervention_manager(session_id: str):
    """Unregister an intervention manager."""
    if session_id in _intervention_managers:
        del _intervention_managers[session_id]
        logger.info(f"[InterventionRegistry] Unregistered manager for session {session_id}")


# =============================================================================
# DEVELOPMENT DEBUG INTERVENTION SYSTEM
# =============================================================================
# This system logs errors for developer investigation during development.
# See: panda_system_docs/architecture/mcp-tool-patterns/internet-research-mcp/internet-research-mcp.md
# Section: Error Recovery & Intervention System

import json
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path
from collections import Counter
from typing import List, Dict, Any

# Development mode - when True, HIGH severity interventions will halt
DEVELOPMENT_MODE = os.getenv("DEVELOPMENT_MODE", "true").lower() == "true"


@dataclass
class DebugIntervention:
    """Request for developer investigation during development."""
    id: str                                    # Unique ID for tracking
    timestamp: str                             # When the intervention was created
    type: str                                  # extraction_failed, navigation_stuck, blocked, etc.
    severity: str                              # HIGH, MEDIUM, LOW
    component: str                             # Which component failed
    error_details: str                         # Error message/stack trace
    context: Dict[str, Any] = field(default_factory=dict)  # What was happening
    page_state: Dict[str, Any] = field(default_factory=dict)  # URL, screenshot, summary
    recovery_attempted: bool = False           # Did we try to recover?
    recovery_result: Optional[str] = None      # What happened when we tried
    suggested_action: Optional[str] = None     # What might fix this


class DebugInterventionManager:
    """
    Manages debug intervention requests during research development.

    This is separate from the captcha InterventionManager - this one logs
    errors for later investigation rather than blocking for human input.

    Usage:
        manager = DebugInterventionManager(session_id="abc123")

        # When something fails
        manager.create_intervention(
            type="extraction_failed",
            severity="HIGH",
            component="UniversalAgent.extract_from_vendor",
            error_details="Zero products extracted from amazon.com",
            context={"vendor": "amazon.com", "query": "laptop"},
            page_state={"url": "https://amazon.com/s?k=laptop"}
        )

        # At end of session, get summary
        summary = manager.get_summary()
    """

    def __init__(self, session_id: str, event_emitter=None):
        self.session_id = session_id
        self.event_emitter = event_emitter
        self.interventions: List[DebugIntervention] = []
        self.intervention_dir = Path("panda_system_docs/interventions")
        self.intervention_dir.mkdir(parents=True, exist_ok=True)

    def create_intervention(
        self,
        type: str,
        severity: str,
        component: str,
        error_details: str,
        context: Dict[str, Any] = None,
        page_state: Dict[str, Any] = None,
        recovery_attempted: bool = False,
        recovery_result: str = None,
        suggested_action: str = None
    ) -> DebugIntervention:
        """
        Create and log a debug intervention request.

        Args:
            type: Type of intervention (extraction_failed, navigation_stuck, blocked, etc.)
            severity: HIGH (halt in dev), MEDIUM (warn), LOW (log only)
            component: Which component/function failed
            error_details: Error message or description
            context: Additional context (vendor, query, step number, etc.)
            page_state: Page information (url, screenshot path, summary)
            recovery_attempted: Whether we tried to recover
            recovery_result: What happened when we tried to recover
            suggested_action: Suggested fix for the developer

        Returns:
            The created DebugIntervention
        """
        intervention = DebugIntervention(
            id=f"dbg_{self.session_id}_{len(self.interventions)}_{datetime.utcnow().strftime('%H%M%S')}",
            timestamp=datetime.utcnow().isoformat(),
            type=type,
            severity=severity,
            component=component,
            error_details=error_details,
            context=context or {},
            page_state=page_state or {},
            recovery_attempted=recovery_attempted,
            recovery_result=recovery_result,
            suggested_action=suggested_action
        )

        # Save to file
        self._save_intervention(intervention)

        # Log based on severity
        self._log_intervention(intervention)

        # Track for summary
        self.interventions.append(intervention)

        # Emit real-time alert for HIGH severity
        if intervention.severity == "HIGH" and self.event_emitter:
            self._emit_alert(intervention)

        return intervention

    def _log_intervention(self, intervention: DebugIntervention):
        """Log intervention with appropriate level."""
        msg = (
            f"[DEBUG_INTERVENTION:{intervention.severity}] {intervention.type} in {intervention.component}: "
            f"{intervention.error_details[:150]}"
        )

        if intervention.suggested_action:
            msg += f" | Suggested: {intervention.suggested_action[:100]}"

        if intervention.severity == "HIGH":
            logger.error(msg)
        elif intervention.severity == "MEDIUM":
            logger.warning(msg)
        else:
            logger.info(msg)

    def _emit_alert(self, intervention: DebugIntervention):
        """Send alert to research monitor UI via event emitter."""
        if not self.event_emitter:
            return

        try:
            event_data = {
                "id": intervention.id,
                "type": intervention.type,
                "severity": intervention.severity,
                "component": intervention.component,
                "error": intervention.error_details[:200],
                "suggested_action": intervention.suggested_action,
                "timestamp": intervention.timestamp
            }
            # Try different emit patterns depending on event_emitter type
            if hasattr(self.event_emitter, 'emit'):
                self.event_emitter.emit("debug_intervention", event_data)
            elif hasattr(self.event_emitter, 'emit_event'):
                self.event_emitter.emit_event("debug_intervention", event_data)
        except Exception as e:
            logger.warning(f"Failed to emit debug intervention alert: {e}")

    def _save_intervention(self, intervention: DebugIntervention):
        """Save intervention to file for later review."""
        try:
            date_dir = self.intervention_dir / datetime.utcnow().strftime("%Y%m%d")
            date_dir.mkdir(exist_ok=True)

            filepath = date_dir / f"{intervention.id}.json"
            with open(filepath, "w") as f:
                json.dump(asdict(intervention), f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save debug intervention to file: {e}")

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of interventions for this session."""
        return {
            "total": len(self.interventions),
            "by_severity": {
                "HIGH": len([i for i in self.interventions if i.severity == "HIGH"]),
                "MEDIUM": len([i for i in self.interventions if i.severity == "MEDIUM"]),
                "LOW": len([i for i in self.interventions if i.severity == "LOW"])
            },
            "by_type": dict(Counter(i.type for i in self.interventions)),
            "has_critical": any(i.severity == "HIGH" for i in self.interventions),
            "interventions": [
                {
                    "id": i.id,
                    "type": i.type,
                    "severity": i.severity,
                    "component": i.component,
                    "error": i.error_details[:100],
                    "suggested_action": i.suggested_action
                }
                for i in self.interventions
            ]
        }

    def should_halt(self) -> bool:
        """
        Check if we should halt due to HIGH severity interventions.

        Only halts in development mode.
        """
        if not DEVELOPMENT_MODE:
            return False
        return any(i.severity == "HIGH" for i in self.interventions)

    def get_halt_reason(self) -> Optional[str]:
        """Get the reason for halting (first HIGH severity intervention)."""
        for i in self.interventions:
            if i.severity == "HIGH":
                return f"{i.type} in {i.component}: {i.error_details[:100]}"
        return None


# Global registry of debug intervention managers
_debug_intervention_managers: Dict[str, DebugInterventionManager] = {}


def get_debug_intervention_manager(session_id: str) -> Optional[DebugInterventionManager]:
    """Get or create debug intervention manager for a session."""
    if session_id not in _debug_intervention_managers:
        _debug_intervention_managers[session_id] = DebugInterventionManager(session_id)
    return _debug_intervention_managers[session_id]


def clear_debug_intervention_manager(session_id: str):
    """Clear debug intervention manager for a session."""
    if session_id in _debug_intervention_managers:
        del _debug_intervention_managers[session_id]


# =============================================================================
# CONVENIENCE FUNCTIONS FOR COMMON INTERVENTION TYPES
# =============================================================================

def log_extraction_failed(
    session_id: str,
    vendor: str,
    query: str,
    error: str,
    url: str = None,
    screenshot_path: str = None,
    page_summary: str = None
) -> DebugIntervention:
    """Log an extraction failure intervention."""
    manager = get_debug_intervention_manager(session_id)
    return manager.create_intervention(
        type="extraction_failed",
        severity="HIGH",
        component="extraction",
        error_details=f"Zero products extracted from {vendor}: {error}",
        context={"vendor": vendor, "query": query},
        page_state={
            "url": url,
            "screenshot": screenshot_path,
            "summary": page_summary[:500] if page_summary else None
        },
        suggested_action="Check if page structure changed or extraction prompts need updating"
    )


def log_navigation_stuck(
    session_id: str,
    vendor: str,
    step: int,
    failed_actions: List[Dict[str, Any]],
    url: str = None,
    screenshot_path: str = None
) -> DebugIntervention:
    """Log a navigation stuck intervention."""
    manager = get_debug_intervention_manager(session_id)

    # Format failed actions for readable error message
    action_summary = []
    for fa in failed_actions[-3:]:  # Last 3 failures
        action = fa.get("action", "unknown")
        target = fa.get("target", "unknown")
        reason = fa.get("reason", "")
        action_summary.append(f"{action}('{target}'): {reason[:40]}")

    return manager.create_intervention(
        type="navigation_stuck",
        severity="HIGH",
        component="navigation",
        error_details=f"Navigation stuck at {vendor} after {step} steps. Recent failures: {'; '.join(action_summary)}",
        context={"vendor": vendor, "step": step, "failed_actions": failed_actions},
        page_state={"url": url, "screenshot": screenshot_path},
        suggested_action="Check if site layout changed or agent needs better navigation hints"
    )


def log_llm_error(
    session_id: str,
    component: str,
    error: str,
    prompt_snippet: str = None
) -> DebugIntervention:
    """Log an LLM call failure intervention."""
    manager = get_debug_intervention_manager(session_id)
    return manager.create_intervention(
        type="llm_error",
        severity="HIGH",
        component=component,
        error_details=f"LLM call failed: {error}",
        context={"prompt_snippet": prompt_snippet[:500] if prompt_snippet else None},
        suggested_action="Check vLLM service status, model availability, or prompt format"
    )


def log_verification_failed(
    session_id: str,
    action: str,
    expected_state: Dict[str, Any],
    actual_state: Dict[str, Any],
    url: str = None
) -> DebugIntervention:
    """Log a verification failure intervention."""
    manager = get_debug_intervention_manager(session_id)
    return manager.create_intervention(
        type="unexpected_state",
        severity="MEDIUM",
        component="verification",
        error_details=f"Action '{action}' did not reach expected state",
        context={
            "action": action,
            "expected": expected_state,
            "actual": actual_state
        },
        page_state={"url": url},
        suggested_action="Check if action target was correct or page behaves differently"
    )
