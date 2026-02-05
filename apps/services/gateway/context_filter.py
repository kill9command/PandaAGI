"""
Context Injection Filter

Prevents toxic Q&A pairs from polluting context.
Only injects high-quality, intent-aligned metadata.

Location: apps/services/gateway/app.py (integrate into existing code)
"""

from typing import Dict, List, Optional


class ContextInjectionFilter:
    """Filters historical patterns for safe context injection."""

    # Intent-Result Type Compatibility Matrix
    INTENT_RESULT_COMPATIBILITY = {
        "transactional": ["shopping_listings", "product_specs", "navigation"],
        "informational": ["care_guides", "general_info", "product_specs"],
        "navigational": ["navigation", "shopping_listings"],
        "code": ["code_output"]
    }

    def __init__(self, quality_threshold: float = 0.6):
        """
        Args:
            quality_threshold: Minimum quality score for injection (default 0.6)
        """
        self.quality_threshold = quality_threshold

    def should_inject_historical_pattern(
        self,
        pattern: Dict,
        current_intent: str,
        strict_mode: bool = True
    ) -> tuple[bool, str]:
        """Decide if a historical pattern should be injected as context.

        Rules:
        1. Only inject high-quality patterns (quality_score >= threshold)
        2. Only inject patterns that match current intent
        3. Only inject patterns where intent was fulfilled
        4. Never inject full Q&A pairs, only metadata
        5. Result type must align with intent

        Args:
            pattern: Historical pattern dictionary
            current_intent: Current query's classified intent
            strict_mode: If True, apply all rules. If False, allow some flexibility.

        Returns:
            (should_inject: bool, reason: str)
        """
        # Rule 1: Quality gate
        quality_score = pattern.get("quality_score", 0)
        if quality_score < self.quality_threshold:
            return (False, f"Low quality: {quality_score} < {self.quality_threshold}")

        # Rule 2: Must not be deprecated
        if pattern.get("deprecated", False):
            return (False, f"Pattern deprecated: {pattern.get('deprecation_reason', 'unknown')}")

        # Rule 3: Intent alignment
        pattern_intent = pattern.get("intent")
        if not pattern_intent:
            return (False, "Missing intent metadata")

        if pattern_intent != current_intent:
            # Exception: Navigational can include transactional for shopping sites
            if not (current_intent == "navigational" and pattern_intent == "transactional"):
                return (False, f"Intent mismatch: {pattern_intent} != {current_intent}")

        # Rule 4: Intent fulfillment
        if strict_mode and not pattern.get("intent_fulfilled", False):
            return (False, "Intent was not fulfilled in original interaction")

        # Rule 5: Must have result_type metadata
        result_type = pattern.get("result_type")
        if not result_type:
            return (False, "Missing result_type metadata")

        # Rule 6: Result type must align with intent
        allowed_result_types = self.INTENT_RESULT_COMPATIBILITY.get(current_intent, [])
        if result_type not in allowed_result_types:
            return (False, f"Result type mismatch: {result_type} not compatible with {current_intent}")

        # All checks passed
        return (True, "Pattern meets all quality criteria")

    def filter_historical_patterns(
        self,
        patterns: List[Dict],
        current_intent: str,
        max_patterns: int = 3
    ) -> List[Dict]:
        """Filter and rank historical patterns for injection.

        Args:
            patterns: List of historical pattern dictionaries
            current_intent: Current query's classified intent
            max_patterns: Maximum number of patterns to inject

        Returns:
            Filtered and ranked list of patterns (metadata only, no full Q&A)
        """
        # Filter and annotate with reasons
        filtered = []
        for pattern in patterns:
            should_inject, reason = self.should_inject_historical_pattern(
                pattern, current_intent
            )
            if should_inject:
                filtered.append({
                    **pattern,
                    "_injection_reason": reason
                })

        # Sort by quality score (descending)
        filtered.sort(key=lambda p: p.get("quality_score", 0), reverse=True)

        # Limit to max_patterns
        return filtered[:max_patterns]

    def convert_to_metadata_only(self, pattern: Dict) -> Dict:
        """Convert pattern to metadata-only format (NO full Q&A text).

        Before (TOXIC):
            {
                "type": "learned_pattern",
                "content": "Question: find hamsters for sale\nAnswer: Housing requirements..."
            }

        After (SAFE):
            {
                "type": "learned_pattern",
                "query": "find hamsters for sale",
                "intent": "transactional",
                "result_type": "shopping_listings",
                "quality_score": 0.78,
                "intent_fulfilled": true,
                "summary": "Found 12 shopping listings",
                "helpful": true
            }
        """
        return {
            "type": "learned_pattern",
            "query": pattern.get("query", ""),
            "intent": pattern.get("intent"),
            "result_type": pattern.get("result_type"),
            "quality_score": pattern.get("quality_score", 0),
            "intent_fulfilled": pattern.get("intent_fulfilled", False),
            "summary": self._generate_summary(pattern),
            "helpful": pattern.get("user_feedback_score", 0.5) > 0.6,
            "times_reused": pattern.get("times_reused", 0),
            "times_helpful": pattern.get("times_helpful", 0)
            # NOTE: NO "response" or "answer" field - only metadata!
        }

    def _generate_summary(self, pattern: Dict) -> str:
        """Generate a brief summary of the pattern outcome."""
        result_type = pattern.get("result_type", "unknown")
        intent_fulfilled = pattern.get("intent_fulfilled", False)
        quality_score = pattern.get("quality_score", 0)

        if quality_score > 0.7 and intent_fulfilled:
            return f"Successfully found {result_type}"
        elif quality_score > 0.5:
            return f"Partially found {result_type}"
        else:
            return f"Low quality result: {result_type}"

    def create_context_injection_block(
        self,
        patterns: List[Dict],
        current_intent: str,
        max_patterns: int = 3
    ) -> str:
        """Create a safe context injection block from historical patterns.

        Returns:
            Formatted string for context injection (metadata only, no full responses)
        """
        filtered = self.filter_historical_patterns(patterns, current_intent, max_patterns)

        if not filtered:
            return ""

        # Convert to metadata-only
        metadata_patterns = [self.convert_to_metadata_only(p) for p in filtered]

        # Format for injection
        context_block = "## Historical Context (Metadata Only)\n\n"
        for i, pattern in enumerate(metadata_patterns, 1):
            context_block += f"### Pattern {i}\n"
            context_block += f"- Query: {pattern['query']}\n"
            context_block += f"- Intent: {pattern['intent']}\n"
            context_block += f"- Result Type: {pattern['result_type']}\n"
            context_block += f"- Quality: {pattern['quality_score']:.2f}\n"
            context_block += f"- Outcome: {pattern['summary']}\n"
            context_block += f"- Helpful: {'Yes' if pattern['helpful'] else 'No'}\n"
            context_block += "\n"

        context_block += "**Note:** Use this metadata to inform your approach, "
        context_block += "but ALWAYS perform fresh searches for current queries.\n"

        return context_block


# Example usage
if __name__ == "__main__":
    filter = ContextInjectionFilter(quality_threshold=0.6)

    # Example patterns (simulating historical data)
    patterns = [
        {
            "query": "find hamsters for sale online",
            "intent": "transactional",
            "result_type": "care_guides",  # WRONG!
            "quality_score": 0.3,
            "intent_fulfilled": False,
            "user_feedback_score": 0.1,
            "times_reused": 4,
            "times_helpful": 1
        },
        {
            "query": "syrian hamster for sale",
            "intent": "transactional",
            "result_type": "shopping_listings",  # CORRECT!
            "quality_score": 0.78,
            "intent_fulfilled": True,
            "user_feedback_score": 0.9,
            "times_reused": 10,
            "times_helpful": 9
        },
        {
            "query": "what do hamsters eat",
            "intent": "informational",
            "result_type": "care_guides",
            "quality_score": 0.85,
            "intent_fulfilled": True,
            "user_feedback_score": 0.9,
            "times_reused": 8,
            "times_helpful": 8
        }
    ]

    print("=== Filtering for Transactional Query ===")
    print("Current intent: transactional\n")

    for i, pattern in enumerate(patterns, 1):
        should_inject, reason = filter.should_inject_historical_pattern(
            pattern, "transactional"
        )
        print(f"Pattern {i}: {pattern['query']}")
        print(f"  Result type: {pattern['result_type']}")
        print(f"  Quality: {pattern['quality_score']}")
        print(f"  Should inject: {should_inject}")
        print(f"  Reason: {reason}\n")

    print("\n=== Filtered Context Block ===")
    context = filter.create_context_injection_block(patterns, "transactional", max_patterns=2)
    print(context)

    print("\n=== Key Observations ===")
    print("✓ Low-quality pattern (care_guides for shopping) was EXCLUDED")
    print("✓ High-quality shopping pattern was INCLUDED")
    print("✓ Informational pattern (wrong intent) was EXCLUDED")
    print("✓ NO full Q&A text injected, only metadata")
    print("✓ Clear guidance to perform fresh search")
