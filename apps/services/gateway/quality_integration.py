"""
Quality Tracking Integration Helper

Simple helper functions to integrate quality tracking into the gateway.
Import these functions into app.py and call at appropriate points.
"""

from typing import Any, Dict, List, Optional

# Lazy imports to avoid startup overhead
_quality_tracker = None


def get_quality_tracker():
    """Lazy-load the quality tracker."""
    global _quality_tracker
    if _quality_tracker is None:
        from .session_quality_tracker import SessionQualityTracker
        _quality_tracker = SessionQualityTracker()
    return _quality_tracker


def track_turn(
    session_id: str,
    turn_id: int,
    user_query: str,
    intent: Optional[str] = None,
    response_quality: float = 0.5,
    claims_used: Optional[List[str]] = None,
    intent_fulfilled: bool = True,
    cache_hit: bool = False,
) -> None:
    """
    Track a conversation turn.

    Call this AFTER returning a response to the user.

    Args:
        session_id: Session identifier
        turn_id: Turn number in session
        user_query: User's question/request
        intent: Classified intent (transactional, informational, etc.)
        response_quality: Predicted quality score (0.0-1.0)
        claims_used: List of claim IDs used in response
        intent_fulfilled: Whether the response addressed the intent
        cache_hit: Whether response used cached data
    """
    try:
        tracker = get_quality_tracker()
        tracker.record_turn(
            session_id=session_id,
            turn_id=turn_id,
            user_query=user_query,
            intent=intent,
            response_quality=response_quality,
            claims_used=claims_used,
            intent_fulfilled=intent_fulfilled,
            cache_hit=cache_hit,
        )
    except Exception as e:
        # Don't fail the request if quality tracking fails
        print(f"Quality tracking error: {e}")


def detect_satisfaction(
    session_id: str,
    current_turn_id: int,
    current_query: str,
    current_intent: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect user satisfaction from follow-up query.

    Call this BEFORE processing the current query, to analyze
    satisfaction with the previous response.

    Args:
        session_id: Session identifier
        current_turn_id: Current turn number
        current_query: Current user query
        current_intent: Classified intent of current query

    Returns:
        Satisfaction analysis dict with:
        - satisfied: bool (True/False/None)
        - confidence: float (0.0-1.0)
        - reason: str
        - satisfaction_score: float (0.0-1.0)
        - previous_turn_id: int
        - previous_claims: List[str]
    """
    try:
        tracker = get_quality_tracker()
        return tracker.detect_satisfaction_from_follow_up(
            session_id=session_id,
            current_turn_id=current_turn_id,
            current_query=current_query,
            current_intent=current_intent,
        )
    except Exception as e:
        print(f"Satisfaction detection error: {e}")
        return None


def propagate_feedback(session_id: str) -> int:
    """
    Propagate user feedback to claims.

    Call this periodically (e.g., every 5 turns or end of session)
    to update claim quality based on user satisfaction.

    Args:
        session_id: Session identifier

    Returns:
        Number of claims updated
    """
    try:
        tracker = get_quality_tracker()
        return tracker.propagate_feedback_to_claims(session_id)
    except Exception as e:
        print(f"Feedback propagation error: {e}")
        return 0


def get_session_analysis(session_id: str) -> Dict[str, Any]:
    """
    Get quality analysis for a session.

    Args:
        session_id: Session identifier

    Returns:
        Analysis dict with:
        - aggregate_quality: float
        - quality_trend: str (improving/declining/stable)
        - satisfaction_rate: float
        - issues: List[str]
    """
    try:
        tracker = get_quality_tracker()
        return tracker.analyze_session_quality(session_id)
    except Exception as e:
        print(f"Session analysis error: {e}")
        return {
            "aggregate_quality": 0.5,
            "quality_trend": "stable",
            "satisfaction_rate": 0.5,
            "issues": [],
        }


# Integration instructions for app.py:
"""
INTEGRATION GUIDE FOR app.py:

1. Add import at top of file:
   from .quality_integration import track_turn, detect_satisfaction, propagate_feedback

2. In chat_completions() function, BEFORE processing request:
   # Detect satisfaction from previous turn
   satisfaction = detect_satisfaction(
       session_id=session_id,
       current_turn_id=turn_id,
       current_query=user_msg,
       current_intent=classified_intent
   )
   if satisfaction and satisfaction["satisfied"] is False:
       # User dissatisfied - could trigger fresh search or retry logic
       logger.warning(f"User dissatisfied: {satisfaction['reason']}")

3. In chat_completions() function, AFTER generating response:
   # Track this turn
   track_turn(
       session_id=session_id,
       turn_id=turn_id,
       user_query=user_msg,
       intent=classified_intent,
       response_quality=predicted_quality,  # Extract from response metadata
       claims_used=claims_used,  # List of claim IDs from capsule
       intent_fulfilled=True,  # Could be extracted from Guide's response
       cache_hit=was_cache_hit  # Boolean indicating cache reuse
   )

4. Periodically (e.g., every 5 turns or session end):
   if turn_id % 5 == 0:
       updated = propagate_feedback(session_id)
       logger.info(f"Updated {updated} claims with user feedback")

MINIMAL INTEGRATION (if full integration is too complex):
Just add tracking after response generation - satisfaction detection
and feedback propagation will happen automatically on next request.
"""
