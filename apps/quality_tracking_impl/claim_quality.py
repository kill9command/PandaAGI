# STATUS: Prototype - not wired into pipeline. Integration pending.
"""
Claim Quality Scoring System

Scores claims based on:
- Intent alignment: Does result type match query intent?
- Evidence strength: How confident/complete is the data?
- User feedback: Did this claim help the user?

Location: orchestrator/claim_quality.py (to be created)
"""

from typing import Dict, Optional, Literal
from datetime import datetime


class ClaimQualityScorer:
    """Scores claim quality across multiple dimensions."""

    # Intent-Result Type Compatibility Matrix
    ALIGNMENT_MATRIX = {
        "transactional": {
            "shopping_listings": 1.0,
            "product_specs": 0.7,
            "navigation": 0.6,
            "care_guides": 0.1,  # ← The problem case!
            "general_info": 0.2,
            "unknown": 0.3
        },
        "informational": {
            "care_guides": 1.0,
            "general_info": 0.9,
            "product_specs": 0.8,
            "shopping_listings": 0.4,
            "navigation": 0.3,
            "unknown": 0.5
        },
        "navigational": {
            "navigation": 1.0,
            "shopping_listings": 0.6,
            "product_specs": 0.4,
            "care_guides": 0.3,
            "general_info": 0.3,
            "unknown": 0.4
        },
        "code": {
            "code_output": 1.0,
            "general_info": 0.3,
            "unknown": 0.2
        }
    }

    def score_intent_alignment(
        self,
        query_intent: str,
        result_type: str,
        tool_status: Literal["success", "error", "empty", "partial"]
    ) -> float:
        """Score how well the result aligns with query intent.

        Args:
            query_intent: The classified intent (transactional, informational, etc.)
            result_type: The detected result type (shopping_listings, care_guides, etc.)
            tool_status: Tool execution status

        Returns:
            Score from 0.0 (complete mismatch) to 1.0 (perfect match)
        """
        # Get base alignment score from matrix
        base_score = self.ALIGNMENT_MATRIX.get(query_intent, {}).get(result_type, 0.3)

        # Apply status penalties
        status_multipliers = {
            "success": 1.0,
            "partial": 0.6,
            "empty": 0.2,
            "error": 0.1
        }
        multiplier = status_multipliers.get(tool_status, 0.5)

        return base_score * multiplier

    def score_evidence_strength(
        self,
        tool_metadata: Dict,
        claim_specificity: float = 0.5,
        source_count: int = 1
    ) -> float:
        """Score the strength of evidence backing this claim.

        Args:
            tool_metadata: Metadata from tool execution
            claim_specificity: How specific is the claim? (0.0-1.0)
            source_count: Number of supporting sources

        Returns:
            Evidence strength score (0.0-1.0)
        """
        data_quality = tool_metadata.get("data_quality", {})

        # Aggregate data quality metrics
        quality_score = (
            data_quality.get("structured", 0.5) * 0.3 +
            data_quality.get("completeness", 0.5) * 0.4 +
            data_quality.get("source_confidence", 0.5) * 0.3
        )

        # Boost for multiple sources (caps at 3 sources = 1.0)
        source_boost = min(source_count / 3.0, 1.0)

        # Combine factors
        evidence_score = (
            quality_score * 0.5 +
            claim_specificity * 0.3 +
            source_boost * 0.2
        )

        return min(evidence_score, 1.0)

    def calculate_overall_quality(
        self,
        intent_alignment: float,
        evidence_strength: float,
        user_feedback_score: Optional[float] = None
    ) -> float:
        """Calculate overall quality score.

        Args:
            intent_alignment: Intent alignment score (0.0-1.0)
            evidence_strength: Evidence strength score (0.0-1.0)
            user_feedback_score: User satisfaction (0.0-1.0), defaults to 0.5

        Returns:
            Overall quality score (0.0-1.0)
        """
        # Use neutral 0.5 if no user feedback yet
        feedback = user_feedback_score if user_feedback_score is not None else 0.5

        # Weighted combination
        quality_score = (
            intent_alignment * 0.4 +  # Intent match is most important
            evidence_strength * 0.3 +  # Evidence quality matters
            feedback * 0.3              # User feedback validates
        )

        return quality_score

    def score_claim(
        self,
        query_intent: str,
        result_type: str,
        tool_status: str,
        tool_metadata: Dict,
        claim_specificity: float = 0.5,
        source_count: int = 1,
        user_feedback_score: Optional[float] = None
    ) -> Dict:
        """Score a claim across all dimensions.

        Returns:
            Dictionary with all quality scores and metadata
        """
        intent_alignment = self.score_intent_alignment(
            query_intent, result_type, tool_status
        )

        evidence_strength = self.score_evidence_strength(
            tool_metadata, claim_specificity, source_count
        )

        overall_quality = self.calculate_overall_quality(
            intent_alignment, evidence_strength, user_feedback_score
        )

        return {
            "intent_alignment": intent_alignment,
            "evidence_strength": evidence_strength,
            "user_feedback_score": user_feedback_score,
            "overall_score": overall_quality,
            "scored_at": datetime.utcnow().isoformat(),
            "components": {
                "intent_match": f"{query_intent} → {result_type}",
                "tool_status": tool_status,
                "data_quality": tool_metadata.get("data_quality", {})
            }
        }

    def calculate_claim_ttl(
        self,
        quality_score: float,
        times_reused: int = 0,
        times_helpful: int = 0,
        base_ttl_hours: int = 168  # 7 days
    ) -> int:
        """Calculate claim TTL based on quality and usage.

        High-quality, frequently helpful claims live longer.
        Low-quality, unhelpful claims decay faster.

        Args:
            quality_score: Overall quality score (0.0-1.0)
            times_reused: Number of times this claim was reused
            times_helpful: Number of times it was helpful
            base_ttl_hours: Base TTL in hours

        Returns:
            TTL in hours (6-720 hours = 6 hours to 30 days)
        """
        # Helpfulness ratio
        helpfulness = times_helpful / max(times_reused, 1) if times_reused > 0 else 0.5

        # Quality multiplier (0.3 to 2.0)
        quality_multiplier = 0.3 + (quality_score * 1.7)

        # Helpfulness multiplier (0.5 to 1.5)
        helpfulness_multiplier = 0.5 + (helpfulness * 1.0)

        # Combined TTL
        ttl_hours = base_ttl_hours * quality_multiplier * helpfulness_multiplier

        # Clamp between 6 hours and 30 days
        return max(6, min(int(ttl_hours), 720))


# Example usage
if __name__ == "__main__":
    scorer = ClaimQualityScorer()

    # Example 1: Good shopping query result
    print("=== Example 1: Shopping Query Success ===")
    result1 = scorer.score_claim(
        query_intent="transactional",
        result_type="shopping_listings",
        tool_status="success",
        tool_metadata={
            "data_quality": {
                "structured": 0.9,
                "completeness": 0.85,
                "source_confidence": 0.8
            }
        },
        claim_specificity=0.9,
        source_count=12
    )
    print(f"Intent alignment: {result1['intent_alignment']}")
    print(f"Evidence strength: {result1['evidence_strength']}")
    print(f"Overall quality: {result1['overall_score']}")
    print(f"TTL: {scorer.calculate_claim_ttl(result1['overall_score'])} hours")

    # Example 2: Bad - care guides for shopping query (THE BUG!)
    print("\n=== Example 2: Shopping Query Returns Care Guides (BAD) ===")
    result2 = scorer.score_claim(
        query_intent="transactional",
        result_type="care_guides",  # ← MISMATCH!
        tool_status="success",
        tool_metadata={
            "data_quality": {
                "structured": 0.7,
                "completeness": 0.75,
                "source_confidence": 0.6
            }
        },
        claim_specificity=0.6,
        source_count=3
    )
    print(f"Intent alignment: {result2['intent_alignment']} ← LOW!")
    print(f"Evidence strength: {result2['evidence_strength']}")
    print(f"Overall quality: {result2['overall_score']} ← POOR!")
    print(f"TTL: {scorer.calculate_claim_ttl(result2['overall_score'])} hours ← SHORT!")

    # Example 3: User feedback integration
    print("\n=== Example 3: After User Feedback ===")
    print("User frustrated (satisfaction=0.1)...")
    result3 = scorer.calculate_overall_quality(
        intent_alignment=result2['intent_alignment'],
        evidence_strength=result2['evidence_strength'],
        user_feedback_score=0.1  # User very dissatisfied
    )
    print(f"Updated quality: {result3} ← DROPPED FURTHER!")
    print(f"New TTL: {scorer.calculate_claim_ttl(result3, times_reused=4, times_helpful=1)} hours")
