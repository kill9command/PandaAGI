# STATUS: Prototype - not wired into pipeline. Integration pending.
"""
User Satisfaction Detector

Detects user satisfaction/frustration from conversation flow patterns.

Location: apps/services/gateway/satisfaction_detector.py
"""

import re
from typing import Dict, Optional


class UserSatisfactionDetector:
    """Detects user satisfaction from conversation flow."""

    # Frustration/dissatisfaction patterns
    FRUSTRATION_PATTERNS = [
        r"but (I|i) (want|need|asked for)",
        r"(no|not) what (I|i) (meant|wanted|asked)",
        r"can you (actually|really) find",
        r"(still|again) (looking for|want|need)",
        r"never mind",
        r"forget it",
        r"(that'?s|this is) not (what|it)",
        r"(i|I) (don't|do not) want",
        r"(why|how come) (did you|are you)",
        r"(wrong|incorrect|mistake)",
    ]

    # Satisfaction patterns
    SATISFACTION_PATTERNS = [
        r"(thank|thanks|thx|ty|tysm)",
        r"(perfect|great|awesome|excellent|amazing)",
        r"(that'?s|exactly) what (I|i) (wanted|needed)",
        r"(yes|yeah|yep), (that|this) (works|helps)",
        r"(appreciate|helpful|useful)",
        r"(love|like) (this|that|it)",
    ]

    # Clarification patterns (neutral - user wants more info)
    CLARIFICATION_PATTERNS = [
        r"(what|which|how) (about|is)",
        r"can you (explain|tell me more)",
        r"(show|give) me (more|another)",
        r"(what|where) (else|other)",
    ]

    def analyze_follow_up(
        self,
        original_query: str,
        original_intent: str,
        response: str,
        follow_up_query: str,
        follow_up_intent: Optional[str] = None
    ) -> Dict:
        """Analyze if follow-up indicates satisfaction or frustration.

        Args:
            original_query: The user's original question
            original_intent: Classified intent of original query
            response: System's response to original query
            follow_up_query: User's follow-up message
            follow_up_intent: Classified intent of follow-up (optional)

        Returns:
            {
                "satisfied": bool | None,
                "confidence": 0.0-1.0,
                "reason": str,
                "suggested_quality_adjustment": float  # -0.3 to +0.3
                "detected_patterns": List[str]
            }
        """
        follow_up_lower = follow_up_query.lower()
        detected_patterns = []

        # Check for frustration
        for pattern in self.FRUSTRATION_PATTERNS:
            if re.search(pattern, follow_up_query, re.IGNORECASE):
                detected_patterns.append(f"frustration: {pattern}")
                return {
                    "satisfied": False,
                    "confidence": 0.8,
                    "reason": f"Frustration pattern detected: {pattern}",
                    "suggested_quality_adjustment": -0.3,
                    "detected_patterns": detected_patterns
                }

        # Check for satisfaction
        for pattern in self.SATISFACTION_PATTERNS:
            if re.search(pattern, follow_up_query, re.IGNORECASE):
                detected_patterns.append(f"satisfaction: {pattern}")
                return {
                    "satisfied": True,
                    "confidence": 0.9,
                    "reason": f"Satisfaction pattern detected: {pattern}",
                    "suggested_quality_adjustment": +0.2,
                    "detected_patterns": detected_patterns
                }

        # Check for clarification (neutral)
        for pattern in self.CLARIFICATION_PATTERNS:
            if re.search(pattern, follow_up_query, re.IGNORECASE):
                detected_patterns.append(f"clarification: {pattern}")
                return {
                    "satisfied": None,  # Neutral
                    "confidence": 0.5,
                    "reason": f"Clarification request: {pattern}",
                    "suggested_quality_adjustment": 0.0,
                    "detected_patterns": detected_patterns
                }

        # Intent shift detection
        if follow_up_intent and follow_up_intent == original_intent:
            # User asking similar question again = not satisfied
            return {
                "satisfied": False,
                "confidence": 0.6,
                "reason": "User repeating similar query (intent unchanged)",
                "suggested_quality_adjustment": -0.2,
                "detected_patterns": ["intent_repetition"]
            }

        # Check for very short follow-ups that might indicate confusion
        if len(follow_up_query.split()) <= 3:
            # Short queries might be clarifications or dissatisfaction
            if any(word in follow_up_lower for word in ["what", "huh", "??", "why"]):
                return {
                    "satisfied": False,
                    "confidence": 0.5,
                    "reason": "Short confusion query",
                    "suggested_quality_adjustment": -0.1,
                    "detected_patterns": ["short_confusion"]
                }

        # No clear signals
        return {
            "satisfied": None,
            "confidence": 0.3,
            "reason": "No clear satisfaction signals",
            "suggested_quality_adjustment": 0.0,
            "detected_patterns": []
        }

    def analyze_session_quality(
        self,
        turns: list[Dict]
    ) -> Dict:
        """Analyze overall session quality from multiple turns.

        Args:
            turns: List of turn dictionaries with keys:
                   - user_query
                   - intent
                   - response_quality (predicted)
                   - user_satisfaction (detected)

        Returns:
            {
                "aggregate_quality": float,
                "quality_trend": "improving" | "declining" | "stable",
                "satisfaction_rate": float,
                "issues": List[str]
            }
        """
        if not turns:
            return {
                "aggregate_quality": 0.5,
                "quality_trend": "stable",
                "satisfaction_rate": 0.5,
                "issues": []
            }

        # Calculate aggregate quality
        valid_turns = [t for t in turns if "response_quality" in t]
        if valid_turns:
            aggregate_quality = sum(t["response_quality"] for t in valid_turns) / len(valid_turns)
        else:
            aggregate_quality = 0.5

        # Calculate satisfaction rate
        satisfaction_turns = [t for t in turns if t.get("user_satisfaction") is not None]
        if satisfaction_turns:
            satisfaction_rate = sum(
                1 for t in satisfaction_turns if t["user_satisfaction"] > 0.6
            ) / len(satisfaction_turns)
        else:
            satisfaction_rate = 0.5

        # Detect quality trend
        if len(valid_turns) >= 3:
            recent_quality = sum(t["response_quality"] for t in valid_turns[-3:]) / 3
            older_quality = sum(t["response_quality"] for t in valid_turns[:-3]) / max(len(valid_turns) - 3, 1)

            if recent_quality > older_quality + 0.1:
                trend = "improving"
            elif recent_quality < older_quality - 0.1:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "stable"

        # Detect issues
        issues = []
        if aggregate_quality < 0.5:
            issues.append("Low average response quality")
        if satisfaction_rate < 0.5:
            issues.append("Low user satisfaction rate")
        if trend == "declining":
            issues.append("Quality trend declining")

        # Check for intent repetition (user frustrated, asking same thing)
        intent_sequence = [t.get("intent") for t in turns[-3:] if "intent" in t]
        if len(intent_sequence) >= 3 and len(set(intent_sequence)) == 1:
            issues.append("User repeating same intent (likely frustrated)")

        return {
            "aggregate_quality": aggregate_quality,
            "quality_trend": trend,
            "satisfaction_rate": satisfaction_rate,
            "issues": issues,
            "turn_count": len(turns),
            "satisfied_turns": len([t for t in satisfaction_turns if t["user_satisfaction"] > 0.6]),
            "dissatisfied_turns": len([t for t in satisfaction_turns if t["user_satisfaction"] < 0.4])
        }


# Example usage
if __name__ == "__main__":
    detector = UserSatisfactionDetector()

    # Example 1: User frustrated (the hamster bug!)
    print("=== Example 1: User Frustration ===")
    result1 = detector.analyze_follow_up(
        original_query="can you find me some hamsters for sale online?",
        original_intent="transactional",
        response="Here are care guides... Housing requirements...",
        follow_up_query="but I wanted to BUY one!"
    )
    print(f"Satisfied: {result1['satisfied']}")
    print(f"Confidence: {result1['confidence']}")
    print(f"Reason: {result1['reason']}")
    print(f"Quality adjustment: {result1['suggested_quality_adjustment']}")

    # Example 2: User satisfied
    print("\n=== Example 2: User Satisfaction ===")
    result2 = detector.analyze_follow_up(
        original_query="find syrian hamsters for sale",
        original_intent="transactional",
        response="Found 12 listings at Petco, local breeders...",
        follow_up_query="thanks! that petco one looks perfect"
    )
    print(f"Satisfied: {result2['satisfied']}")
    print(f"Confidence: {result2['confidence']}")
    print(f"Reason: {result2['reason']}")
    print(f"Quality adjustment: {result2['suggested_quality_adjustment']}")

    # Example 3: Intent repetition (dissatisfaction)
    print("\n=== Example 3: Intent Repetition ===")
    result3 = detector.analyze_follow_up(
        original_query="find hamsters for sale",
        original_intent="transactional",
        response="Care guides...",
        follow_up_query="can you actually find some for sale?",
        follow_up_intent="transactional"  # Same intent = not satisfied
    )
    print(f"Satisfied: {result3['satisfied']}")
    print(f"Confidence: {result3['confidence']}")
    print(f"Reason: {result3['reason']}")

    # Example 4: Session quality analysis
    print("\n=== Example 4: Session Quality Analysis ===")
    session_turns = [
        {"user_query": "what do hamsters eat?", "intent": "informational",
         "response_quality": 0.85, "user_satisfaction": 0.9},
        {"user_query": "find some for sale", "intent": "transactional",
         "response_quality": 0.3, "user_satisfaction": 0.1},
        {"user_query": "but I want to buy one!", "intent": "transactional",
         "response_quality": 0.25, "user_satisfaction": 0.05},
    ]
    session_analysis = detector.analyze_session_quality(session_turns)
    print(f"Aggregate quality: {session_analysis['aggregate_quality']}")
    print(f"Satisfaction rate: {session_analysis['satisfaction_rate']}")
    print(f"Quality trend: {session_analysis['quality_trend']}")
    print(f"Issues: {session_analysis['issues']}")
