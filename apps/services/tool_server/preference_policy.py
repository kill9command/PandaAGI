"""
Preference Update Policy - Context Manager Authority

This module implements the preference update policy for the Context Manager.
It classifies user statements into 5 types and determines if preferences should be updated.

Author: Panda Team
Created: 2025-11-13
Quality Agent Reviewed: ✅ Approved
"""

from enum import Enum
from typing import Optional, Dict, Any, Tuple
import re
import logging
import time

logger = logging.getLogger(__name__)


class PreferenceUpdateType(Enum):
    """Types of preference-related user statements (5-type classification)"""
    EXPLICIT_DECLARATION = "explicit_declaration"  # "My favorite is X"
    IMPLICIT_PREFERENCE = "implicit_preference"    # Actions reveal preference
    CONTRADICTORY_REQUEST = "contradictory_request"  # "Actually I want Y instead"
    EXPLORATORY_QUERY = "exploratory_query"        # "Find X for me"
    CONFIRMING_ACTION = "confirming_action"        # User acts on recommendation


class PreferenceUpdateDecision:
    """Decision on whether to update a preference"""

    def __init__(
        self,
        should_update: bool,
        reason: str,
        confidence: float,
        update_type: PreferenceUpdateType,
        requires_audit: bool = False
    ):
        self.should_update = should_update
        self.reason = reason
        self.confidence = confidence
        self.update_type = update_type
        self.requires_audit = requires_audit


def classify_preference_statement(
    user_message: str,
    guide_response: str,
    key: str,
    new_value: str,
    old_value: Optional[str],
    tool_results: list
) -> PreferenceUpdateType:
    """
    Classify user statement into 5 types.

    Args:
        user_message: User's query
        guide_response: Guide's response
        key: Preference key (e.g., "favorite_hamster")
        new_value: Proposed new value
        old_value: Current value (None if new)
        tool_results: Tool execution results

    Returns:
        PreferenceUpdateType classification
    """
    msg_lower = user_message.lower()
    value_lower = new_value.lower()

    # Type 1: EXPLICIT_DECLARATION
    # "My favorite is X", "I prefer Y", "I like Z best"
    explicit_patterns = [
        rf"my favorite\s+\w+\s+(?:is|are)\s+{re.escape(value_lower)}",
        rf"I\s+prefer\s+{re.escape(value_lower)}",
        rf"I\s+like\s+{re.escape(value_lower)}\s+(?:best|most)",
        rf"I\s+want\s+{re.escape(value_lower)}(?:\s+hamsters?)?$",  # Terminal want
        rf"my\s+\w+\s+is\s+{re.escape(value_lower)}",
    ]

    for pattern in explicit_patterns:
        if re.search(pattern, msg_lower):
            return PreferenceUpdateType.EXPLICIT_DECLARATION

    # Type 3: CONTRADICTORY_REQUEST (check before EXPLORATORY_QUERY)
    # "Actually I want Y", "Changed my mind", "I prefer Y instead"
    contradiction_keywords = [
        "actually", "instead", "changed my mind", "no,", "not",
        "prefer.*instead", "want.*instead", "rather"
    ]

    if old_value and old_value != new_value:
        for keyword in contradiction_keywords:
            if re.search(keyword, msg_lower):
                return PreferenceUpdateType.CONTRADICTORY_REQUEST

    # Type 4: EXPLORATORY_QUERY
    # "Find X for me", "Can you show me Y", "What about Z", "Where to buy X"
    exploratory_patterns = [
        rf"(?:find|show|get|locate)\s+(?:me\s+)?(?:some\s+)?{re.escape(value_lower)}",
        rf"(?:can you|could you)\s+(?:find|show|get)",
        rf"what about\s+{re.escape(value_lower)}",
        rf"where\s+(?:can I|to)\s+(?:buy|find|get)",
        rf"(?:search|look)\s+for\s+{re.escape(value_lower)}",
        r"for sale",
        r"available",
    ]

    for pattern in exploratory_patterns:
        if re.search(pattern, msg_lower):
            return PreferenceUpdateType.EXPLORATORY_QUERY

    # Type 5: CONFIRMING_ACTION
    # User acted on a recommendation (detected via tool results)
    if tool_results and old_value:
        # Check if user is following up on previous recommendation
        for tool in tool_results:
            tool_name = tool.get("tool", "")
            if "purchase" in tool_name or "buy" in tool_name:
                # User took action on recommendation
                return PreferenceUpdateType.CONFIRMING_ACTION

    # Type 2: IMPLICIT_PREFERENCE (default for unclear cases)
    return PreferenceUpdateType.IMPLICIT_PREFERENCE


def calculate_preference_age(
    old_value: Optional[str],
    preference_history: list,
    key: str
) -> Tuple[int, int]:
    """
    Calculate how established a preference is.

    Returns:
        (turn_count_since_set, total_updates)
    """
    if not old_value or not preference_history:
        return (0, 0)

    # Find when this preference was last updated
    turns_since_set = 0
    total_updates = 0

    for history_entry in reversed(preference_history):
        if history_entry.get("key") == key:
            total_updates += 1
            if turns_since_set == 0:
                # First (most recent) entry
                turns_since_set = history_entry.get("turn", 0)

    return (turns_since_set, total_updates)


def evaluate_preference_update(
    key: str,
    new_value: str,
    old_value: Optional[str],
    user_message: str,
    guide_response: str,
    tool_results: list,
    extraction_confidence: float,
    preference_history: list,
    current_turn: int
) -> PreferenceUpdateDecision:
    """
    Context Manager's preference update policy.

    This is the ONLY place where preferences are modified.
    Implements 5-type classification with time decay for established preferences.

    Args:
        key: Preference key (e.g., "favorite_hamster")
        new_value: Proposed new value
        old_value: Current value (None if new)
        user_message: Original user message
        guide_response: Guide's synthesized response
        tool_results: Tool execution results
        extraction_confidence: LLM extraction confidence
        preference_history: List of previous preference changes
        current_turn: Current turn number

    Returns:
        PreferenceUpdateDecision with should_update and reasoning
    """

    # RULE 1: If no existing value, apply lower threshold
    if old_value is None:
        update_type = classify_preference_statement(
            user_message, guide_response, key, new_value, old_value, tool_results
        )

        if update_type == PreferenceUpdateType.EXPLICIT_DECLARATION:
            if extraction_confidence >= 0.75:  # Lower threshold for new preferences
                return PreferenceUpdateDecision(
                    should_update=True,
                    reason=f"New preference with explicit declaration (confidence: {extraction_confidence:.2f})",
                    confidence=extraction_confidence,
                    update_type=update_type
                )
            else:
                return PreferenceUpdateDecision(
                    should_update=False,
                    reason=f"New preference but confidence too low ({extraction_confidence:.2f} < 0.75)",
                    confidence=extraction_confidence,
                    update_type=update_type
                )

        elif update_type == PreferenceUpdateType.IMPLICIT_PREFERENCE:
            if extraction_confidence >= 0.60:
                return PreferenceUpdateDecision(
                    should_update=True,
                    reason=f"New preference from implicit signal (confidence: {extraction_confidence:.2f})",
                    confidence=extraction_confidence,
                    update_type=update_type
                )

        # Exploratory queries don't set new preferences
        return PreferenceUpdateDecision(
            should_update=False,
            reason=f"Not a preference declaration (type: {update_type.value})",
            confidence=extraction_confidence,
            update_type=update_type
        )

    # RULE 2: If same value, skip
    if old_value == new_value:
        return PreferenceUpdateDecision(
            should_update=False,
            reason="Value unchanged",
            confidence=1.0,
            update_type=PreferenceUpdateType.CONFIRMING_ACTION
        )

    # RULE 3: Classify the statement type
    update_type = classify_preference_statement(
        user_message, guide_response, key, new_value, old_value, tool_results
    )

    # RULE 4: Calculate preference age (time decay)
    turns_since_set, total_updates = calculate_preference_age(
        old_value, preference_history, key
    )

    # Fresh preference (< 5 turns): Lower threshold (0.75)
    # Established preference (> 10 turns): Higher threshold (0.90)
    if turns_since_set < 5:
        age_category = "fresh"
        confidence_threshold_modifier = -0.10  # Easier to change
    elif turns_since_set > 10:
        age_category = "established"
        confidence_threshold_modifier = +0.05  # Harder to change
    else:
        age_category = "moderate"
        confidence_threshold_modifier = 0.0

    # RULE 5: Apply update policy based on type

    if update_type == PreferenceUpdateType.EXPLORATORY_QUERY:
        # User is just asking about entity, not declaring preference
        logger.info(
            f"[PreferencePolicy] Blocked exploratory query: "
            f"{key} '{old_value}' → '{new_value}' (preserving existing)"
        )
        return PreferenceUpdateDecision(
            should_update=False,
            reason=f"Exploratory query about '{new_value}', not a preference change. Preserving '{old_value}'.",
            confidence=extraction_confidence,
            update_type=update_type
        )

    elif update_type == PreferenceUpdateType.EXPLICIT_DECLARATION:
        # Direct statement: "My favorite is X"
        threshold = 0.85 + confidence_threshold_modifier
        if extraction_confidence >= threshold:
            logger.warning(
                f"[PreferencePolicy] Explicit re-declaration: "
                f"{key} '{old_value}' → '{new_value}' (confidence: {extraction_confidence:.2f}, "
                f"age: {age_category}, turns: {turns_since_set})"
            )
            return PreferenceUpdateDecision(
                should_update=True,
                reason=f"Explicit re-declaration with high confidence ({extraction_confidence:.2f})",
                confidence=extraction_confidence,
                update_type=update_type,
                requires_audit=True
            )
        else:
            return PreferenceUpdateDecision(
                should_update=False,
                reason=f"Confidence too low for re-declaration ({extraction_confidence:.2f} < {threshold:.2f}). Preserving '{old_value}'.",
                confidence=extraction_confidence,
                update_type=update_type
            )

    elif update_type == PreferenceUpdateType.CONTRADICTORY_REQUEST:
        # "Actually I want Y instead"
        threshold = 0.90 + confidence_threshold_modifier
        if extraction_confidence >= threshold:
            logger.warning(
                f"[PreferencePolicy] Preference contradiction: "
                f"{key} '{old_value}' → '{new_value}' (confidence: {extraction_confidence:.2f}, "
                f"age: {age_category}, turns: {turns_since_set})"
            )
            return PreferenceUpdateDecision(
                should_update=True,
                reason=f"Explicit contradiction with high confidence ({extraction_confidence:.2f})",
                confidence=extraction_confidence,
                update_type=update_type,
                requires_audit=True  # Require logging
            )
        else:
            return PreferenceUpdateDecision(
                should_update=False,
                reason=f"Unclear contradiction (confidence {extraction_confidence:.2f} < {threshold:.2f}). Preserving '{old_value}'.",
                confidence=extraction_confidence,
                update_type=update_type
            )

    elif update_type == PreferenceUpdateType.CONFIRMING_ACTION:
        # User acted on recommendation - strengthen existing preference
        return PreferenceUpdateDecision(
            should_update=False,
            reason=f"User confirmed preference for '{old_value}' through action",
            confidence=extraction_confidence,
            update_type=update_type
        )

    elif update_type == PreferenceUpdateType.IMPLICIT_PREFERENCE:
        # Tentative update from behavior patterns
        threshold = 0.60 + confidence_threshold_modifier
        if extraction_confidence >= threshold:
            logger.info(
                f"[PreferencePolicy] Tentative preference update: "
                f"{key} '{old_value}' → '{new_value}' (confidence: {extraction_confidence:.2f})"
            )
            return PreferenceUpdateDecision(
                should_update=True,
                reason=f"Implicit preference detected (confidence: {extraction_confidence:.2f})",
                confidence=extraction_confidence,
                update_type=update_type
            )
        else:
            return PreferenceUpdateDecision(
                should_update=False,
                reason=f"Implicit signal too weak (confidence {extraction_confidence:.2f} < {threshold:.2f}). Preserving '{old_value}'.",
                confidence=extraction_confidence,
                update_type=update_type
            )

    # RULE 6: Default - conservative (don't update)
    logger.info(
        f"[PreferencePolicy] Blocked unclear update: "
        f"{key} '{old_value}' → '{new_value}' (type: {update_type.value}, confidence: {extraction_confidence:.2f})"
    )
    return PreferenceUpdateDecision(
        should_update=False,
        reason=f"Unclear intent (type: {update_type.value}). Preserving existing preference '{old_value}'.",
        confidence=extraction_confidence,
        update_type=update_type
    )
