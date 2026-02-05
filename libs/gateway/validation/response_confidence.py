"""
Response Confidence Calculator

Calculates aggregate response confidence from multiple signals:
- Claim confidences (from tool results)
- Source quality (relevance scores from memory)
- Goal coverage (achieved goals / total goals)

Based on patterns from Project Manager Assistant Agent:
- Aggregate quality metric enables iteration comparison
- Single number to track improvement across attempts

Usage:
    calculator = ResponseConfidenceCalculator()
    aggregate = calculator.calculate(
        claim_confidences=[0.9, 0.85, 0.7],
        source_relevances=[0.8, 0.6],
        goals_achieved=2,
        goals_total=3
    )
    # Returns: AggregateConfidence(score=0.82, breakdown={...})
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class AggregateConfidence:
    """Aggregate confidence score with breakdown."""

    score: float
    """Final aggregate confidence 0.0-1.0."""

    breakdown: Dict[str, float] = field(default_factory=dict)
    """Component scores for transparency."""

    issues: List[str] = field(default_factory=list)
    """Issues that lowered confidence."""

    def to_markdown(self) -> str:
        """Format for inclusion in context.md."""
        lines = [
            f"**Aggregate Confidence:** {self.score:.2f}",
            "",
            "| Component | Score | Weight |",
            "|-----------|-------|--------|",
        ]
        for name, score in self.breakdown.items():
            weight = COMPONENT_WEIGHTS.get(name, 0.0)
            lines.append(f"| {name} | {score:.2f} | {weight:.0%} |")

        if self.issues:
            lines.append("")
            lines.append("**Confidence Issues:**")
            for issue in self.issues:
                lines.append(f"- {issue}")

        return "\n".join(lines)


# Component weights for aggregate calculation
COMPONENT_WEIGHTS = {
    "claim_confidence": 0.40,   # How confident are individual claims
    "source_quality": 0.25,     # How relevant were the sources
    "goal_coverage": 0.25,      # What % of goals were achieved
    "evidence_depth": 0.10,     # How much evidence do we have
}


class ResponseConfidenceCalculator:
    """
    Calculates aggregate response confidence.

    Inspired by Project Manager Assistant pattern of aggregating
    individual scores into a project-level quality metric.
    """

    def __init__(self, weights: Dict[str, float] = None):
        """
        Initialize calculator with optional custom weights.

        Args:
            weights: Custom component weights (must sum to 1.0)
        """
        self.weights = weights or COMPONENT_WEIGHTS

    def calculate(
        self,
        claim_confidences: List[float] = None,
        source_relevances: List[float] = None,
        goals_achieved: int = 0,
        goals_total: int = 0,
        has_tool_results: bool = False,
        has_memory_context: bool = False,
    ) -> AggregateConfidence:
        """
        Calculate aggregate confidence from component scores.

        Args:
            claim_confidences: Confidence scores for each claim (0.0-1.0)
            source_relevances: Relevance scores for each source (0.0-1.0)
            goals_achieved: Number of goals marked as achieved
            goals_total: Total number of goals
            has_tool_results: Whether tool results were obtained
            has_memory_context: Whether memory context was found

        Returns:
            AggregateConfidence with score, breakdown, and issues
        """
        claim_confidences = claim_confidences or []
        source_relevances = source_relevances or []

        breakdown = {}
        issues = []

        # 1. Claim confidence (average of all claim scores)
        if claim_confidences:
            claim_score = sum(claim_confidences) / len(claim_confidences)
            breakdown["claim_confidence"] = claim_score

            # Flag low-confidence claims
            low_conf_claims = [c for c in claim_confidences if c < 0.7]
            if low_conf_claims:
                issues.append(f"{len(low_conf_claims)} claims with confidence < 0.7")
        else:
            # No claims - use default based on context availability
            if has_memory_context:
                breakdown["claim_confidence"] = 0.75  # Memory-based response
            elif has_tool_results:
                breakdown["claim_confidence"] = 0.70  # Tool results but no claims extracted
            else:
                breakdown["claim_confidence"] = 0.60  # No evidence
                issues.append("No claims extracted from results")

        # 2. Source quality (average relevance)
        if source_relevances:
            source_score = sum(source_relevances) / len(source_relevances)
            breakdown["source_quality"] = source_score

            # Flag low-relevance sources
            low_rel_sources = [r for r in source_relevances if r < 0.5]
            if low_rel_sources:
                issues.append(f"{len(low_rel_sources)} sources with relevance < 0.5")
        else:
            # No source scores - estimate based on context
            if has_memory_context:
                breakdown["source_quality"] = 0.80  # Memory is pre-vetted
            elif has_tool_results:
                breakdown["source_quality"] = 0.65  # Fresh research, unknown quality
            else:
                breakdown["source_quality"] = 0.50  # No sources
                issues.append("No source quality scores available")

        # 3. Goal coverage
        if goals_total > 0:
            goal_score = goals_achieved / goals_total
            breakdown["goal_coverage"] = goal_score

            unfulfilled = goals_total - goals_achieved
            if unfulfilled > 0:
                issues.append(f"{unfulfilled} goals not fully achieved")
        else:
            # No explicit goals - assume single implicit goal
            breakdown["goal_coverage"] = 0.80  # Default for simple queries

        # 4. Evidence depth (based on amount of evidence)
        evidence_count = len(claim_confidences) + len(source_relevances)
        if evidence_count >= 5:
            breakdown["evidence_depth"] = 1.0
        elif evidence_count >= 3:
            breakdown["evidence_depth"] = 0.8
        elif evidence_count >= 1:
            breakdown["evidence_depth"] = 0.6
        else:
            breakdown["evidence_depth"] = 0.4
            issues.append("Limited evidence depth")

        # Calculate weighted aggregate
        aggregate_score = sum(
            breakdown.get(component, 0.0) * weight
            for component, weight in self.weights.items()
        )

        # Clamp to 0.0-1.0
        aggregate_score = max(0.0, min(1.0, aggregate_score))

        logger.debug(
            f"[ResponseConfidence] Calculated aggregate: {aggregate_score:.2f} "
            f"(claims={breakdown.get('claim_confidence', 0):.2f}, "
            f"sources={breakdown.get('source_quality', 0):.2f}, "
            f"goals={breakdown.get('goal_coverage', 0):.2f})"
        )

        return AggregateConfidence(
            score=aggregate_score,
            breakdown=breakdown,
            issues=issues
        )

    def calculate_from_context(
        self,
        claims: List[Dict] = None,
        memory_results: List = None,
        goal_statuses: List[Dict] = None,
    ) -> AggregateConfidence:
        """
        Calculate confidence from context document components.

        Convenience method that extracts scores from typical context structures.

        Args:
            claims: List of claim dicts with 'confidence' key
            memory_results: List of MemoryResult with 'relevance' attribute
            goal_statuses: List of goal status dicts with 'score' and 'status' keys
        """
        claims = claims or []
        memory_results = memory_results or []
        goal_statuses = goal_statuses or []

        # Extract claim confidences
        claim_confidences = [
            c.get("confidence", 0.8)
            for c in claims
            if isinstance(c, dict)
        ]

        # Extract source relevances
        source_relevances = []
        for result in memory_results:
            if hasattr(result, "relevance"):
                source_relevances.append(result.relevance)
            elif isinstance(result, dict) and "relevance" in result:
                source_relevances.append(result["relevance"])

        # Count achieved goals
        goals_achieved = sum(
            1 for g in goal_statuses
            if g.get("status") == "fulfilled" or g.get("score", 0) >= 0.8
        )
        goals_total = len(goal_statuses) if goal_statuses else 0

        return self.calculate(
            claim_confidences=claim_confidences,
            source_relevances=source_relevances,
            goals_achieved=goals_achieved,
            goals_total=goals_total,
            has_tool_results=bool(claims),
            has_memory_context=bool(memory_results),
        )


# Module-level instance
_calculator: Optional[ResponseConfidenceCalculator] = None


def get_confidence_calculator() -> ResponseConfidenceCalculator:
    """Get the global ResponseConfidenceCalculator instance."""
    global _calculator
    if _calculator is None:
        _calculator = ResponseConfidenceCalculator()
    return _calculator


def calculate_aggregate_confidence(
    claim_confidences: List[float] = None,
    source_relevances: List[float] = None,
    goals_achieved: int = 0,
    goals_total: int = 0,
    **kwargs
) -> AggregateConfidence:
    """
    Convenience function to calculate aggregate confidence.

    See ResponseConfidenceCalculator.calculate() for full documentation.
    """
    calculator = get_confidence_calculator()
    return calculator.calculate(
        claim_confidences=claim_confidences,
        source_relevances=source_relevances,
        goals_achieved=goals_achieved,
        goals_total=goals_total,
        **kwargs
    )
