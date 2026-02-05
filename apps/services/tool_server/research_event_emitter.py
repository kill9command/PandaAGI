"""
orchestrator/research_event_emitter.py

Event emitter for real-time research monitoring.
Broadcasts events to connected WebSocket clients via Gateway.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
import json

logger = logging.getLogger(__name__)


class ResearchEventEmitter:
    """
    Emits research events to WebSocket clients for real-time monitoring.

    Events are sent to Gateway via callback, which then broadcasts to connected clients.
    """

    def __init__(self, session_id: str, gateway_callback: Optional[Callable] = None):
        """
        Initialize event emitter.

        Args:
            session_id: Session identifier for this research session
            gateway_callback: Async function to call with events (sends to Gateway)
        """
        self.session_id = session_id
        self.gateway_callback = gateway_callback
        self.events: List[Dict[str, Any]] = []
        self.enabled = gateway_callback is not None

    async def emit(self, event_type: str, data: Dict[str, Any]):
        """
        Emit an event to connected clients.

        Args:
            event_type: Type of event (search_started, candidate_checking, etc.)
            data: Event-specific data
        """
        event = {
            "type": event_type,
            "session_id": self.session_id,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data
        }

        # Store event
        self.events.append(event)

        # Send to Gateway if callback configured (run in background to avoid blocking)
        if self.enabled and self.gateway_callback:
            import asyncio

            # Wrapper to catch exceptions from background task
            async def safe_callback():
                try:
                    await self.gateway_callback(event)
                except Exception as e:
                    logger.error(
                        f"[ResearchEventEmitter] Failed to send {event_type} event: "
                        f"{type(e).__name__}: {e}",
                        exc_info=True
                    )

            # Create background task with error handling
            task = asyncio.create_task(safe_callback())
            # Don't await - let it run in background

    async def emit_search_started(self, query: str, max_candidates: int):
        """Emit search_started event."""
        await self.emit("search_started", {
            "query": query,
            "max_candidates": max_candidates
        })

    async def emit_candidate_checking(self, index: int, total: int, url: str, title: str):
        """Emit candidate_checking event."""
        await self.emit("candidate_checking", {
            "index": index,
            "total": total,
            "url": url,
            "title": title
        })

    async def emit_fetch_complete(
        self,
        url: str,
        status: int,
        success: bool,
        screenshot_path: Optional[str] = None,
        error: Optional[str] = None
    ):
        """Emit fetch_complete event."""
        await self.emit("fetch_complete", {
            "url": url,
            "status": status,
            "success": success,
            "screenshot_path": screenshot_path,
            "error": error
        })

    async def emit_blocker_detected(
        self,
        url: str,
        blocker_type: str,
        confidence: float,
        screenshot_path: Optional[str] = None
    ):
        """Emit blocker_detected event."""
        await self.emit("blocker_detected", {
            "url": url,
            "blocker_type": blocker_type,
            "confidence": confidence,
            "screenshot_path": screenshot_path
        })

    async def emit_intervention_needed(
        self,
        intervention_id: str,
        url: str,
        blocker_type: str,
        screenshot_path: Optional[str] = None,
        cdp_url: Optional[str] = None
    ):
        """Emit intervention_needed event."""
        await self.emit("intervention_needed", {
            "intervention_id": intervention_id,
            "url": url,
            "blocker_type": blocker_type,
            "screenshot_path": screenshot_path,
            "cdp_url": cdp_url
        })

    async def emit_intervention_resolved(
        self,
        intervention_id: str,
        action: str,
        success: bool
    ):
        """Emit intervention_resolved event."""
        await self.emit("intervention_resolved", {
            "intervention_id": intervention_id,
            "action": action,
            "success": success
        })

    async def emit_candidate_accepted(
        self,
        url: str,
        title: str,
        quality_score: float,
        species_score: float,
        partial: bool = False
    ):
        """Emit candidate_accepted event."""
        await self.emit("candidate_accepted", {
            "url": url,
            "title": title,
            "quality_score": quality_score,
            "species_score": species_score,
            "partial": partial
        })

    async def emit_candidate_rejected(
        self,
        url: str,
        title: str,
        reason: str,
        details: str
    ):
        """Emit candidate_rejected event."""
        await self.emit("candidate_rejected", {
            "url": url,
            "title": title,
            "reason": reason,
            "details": details
        })

    async def emit_progress(self, checked: int, total: int, accepted: int, rejected: int):
        """Emit progress update event."""
        await self.emit("progress", {
            "checked": checked,
            "total": total,
            "accepted": accepted,
            "rejected": rejected,
            "progress_pct": int((checked / total) * 100) if total > 0 else 0
        })

    async def emit_search_complete(
        self,
        total_checked: int,
        total_accepted: int,
        total_rejected: int,
        avg_quality: float,
        duration_ms: int
    ):
        """Emit search_complete event."""
        await self.emit("search_complete", {
            "total_checked": total_checked,
            "total_accepted": total_accepted,
            "total_rejected": total_rejected,
            "avg_quality": avg_quality,
            "duration_ms": duration_ms
        })

    async def emit_phase_started(self, phase: str, description: str):
        """Emit phase_started event (for multi-phase research)."""
        await self.emit("phase_started", {
            "phase": phase,
            "description": description
        })

    async def emit_phase_complete(self, phase: str, result: Dict[str, Any]):
        """Emit phase_complete event (for multi-phase research)."""
        await self.emit("phase_complete", {
            "phase": phase,
            "result": result
        })

    async def emit_research_complete(self, synthesis: Dict[str, Any]):
        """Emit research_complete event (final synthesis)."""
        await self.emit("research_complete", {
            "synthesis": synthesis
        })

    def get_events(self) -> List[Dict[str, Any]]:
        """Get all events emitted in this session."""
        return self.events.copy()

    def clear_events(self):
        """Clear event history."""
        self.events.clear()
