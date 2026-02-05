"""
orchestrator/research_evaluator.py

Satisfaction evaluator for Deep research mode.
Evaluates whether research has gathered enough information to satisfy the goal.

Criteria:
1. Coverage: Enough sources checked?
2. Quality: Sources credible and relevant?
3. Completeness: All required info present?
4. Contradictions: Findings consistent?

Created: 2025-11-17
"""
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class SatisfactionEvaluator:
    """
    Evaluates research completeness for Deep mode iteration control.
    """

    # Default thresholds (can be overridden per query)
    DEFAULT_MIN_SOURCES = 8
    DEFAULT_MIN_CONFIDENCE = 0.75
    MAX_PASSES = 3

    def __init__(self, min_sources: int = DEFAULT_MIN_SOURCES, min_confidence: float = DEFAULT_MIN_CONFIDENCE):
        self.min_sources = min_sources
        self.min_confidence = min_confidence

    async def evaluate(
        self,
        pass_number: int,
        pass_results: Dict[str, Any],
        required_info: List[str],
        intent: str = "informational"  # Use intent instead of legacy query_type
    ) -> Dict[str, Any]:
        """
        Evaluate whether research pass satisfied completion criteria.

        Args:
            pass_number: Current pass number (1-3)
            pass_results: Results from research pass
            required_info: List of required information fields
            intent: Intent (navigation, site_search, commerce, informational)

        Returns:
            {
                "decision": "COMPLETE" | "CONTINUE",
                "criteria": {
                    "coverage": {...},
                    "quality": {...},
                    "completeness": {...},
                    "contradictions": {...}
                },
                "missing": [...],  # What's missing if CONTINUE
                "next_actions": [...],  # Suggested next steps
                "reasoning": "..."
            }
        """
        logger.info(f"[SatisfactionEvaluator] Evaluating Pass {pass_number}")

        # Extract results
        phase1_results = pass_results.get("phase1_results", {})
        phase2_results = pass_results.get("phase2_results", {})
        synthesis = phase2_results.get("synthesis", {})

        # 1. Coverage Check
        coverage_result = self._check_coverage(phase1_results, phase2_results)

        # 2. Quality Check
        quality_result = self._check_quality(synthesis, phase2_results)

        # 3. Completeness Check
        completeness_result = self._check_completeness(phase2_results, required_info, intent)

        # 4. Contradictions Check
        contradictions_result = self._check_contradictions(synthesis)

        # Aggregate criteria
        criteria = {
            "coverage": coverage_result,
            "quality": quality_result,
            "completeness": completeness_result,
            "contradictions": contradictions_result
        }

        # Determine decision
        all_met = all([
            coverage_result["met"],
            quality_result["met"],
            completeness_result["met"],
            contradictions_result["met"]
        ])

        # Force completion if max passes reached
        if pass_number >= self.MAX_PASSES:
            decision = "COMPLETE"
            reasoning = f"Max passes ({self.MAX_PASSES}) reached. Returning best effort results."
            if not all_met:
                reasoning += f" Note: Not all criteria met, but cannot continue further."
        elif all_met:
            decision = "COMPLETE"
            reasoning = "All satisfaction criteria met: coverage, quality, completeness, contradictions resolved."
        else:
            decision = "CONTINUE"
            not_met = [k for k, v in criteria.items() if not v["met"]]
            reasoning = f"Criteria not met: {', '.join(not_met)}. Need additional research pass."

        # Generate missing items and next actions if continuing
        missing = []
        next_actions = []
        if decision == "CONTINUE":
            missing, next_actions = self._generate_next_actions(criteria, pass_results, intent)

        evaluation = {
            "pass_number": pass_number,
            "decision": decision,
            "criteria": criteria,
            "all_met": all_met,
            "missing": missing,
            "next_actions": next_actions,
            "reasoning": reasoning,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        logger.info(
            f"[SatisfactionEvaluator] Pass {pass_number} Decision: {decision} "
            f"(Coverage: {coverage_result['met']}, Quality: {quality_result['met']}, "
            f"Completeness: {completeness_result['met']}, Contradictions: {contradictions_result['met']})"
        )

        return evaluation

    def _check_coverage(self, phase1_results: Dict, phase2_results: Dict) -> Dict[str, Any]:
        """Check if enough sources were checked."""
        phase1_sources = phase1_results.get("sources_gathered", 0)
        phase2_sources = phase2_results.get("vendors_found", 0) or len(phase2_results.get("vendors", []))
        total_sources = phase1_sources + phase2_sources

        met = total_sources >= self.min_sources

        # Count unique domains for diversity check
        domains = set()
        if "sources" in phase1_results:
            for source in phase1_results["sources"]:
                if isinstance(source, dict) and "url" in source:
                    from urllib.parse import urlparse
                    domain = urlparse(source["url"]).netloc
                    domains.add(domain)

        return {
            "met": met,
            "sources_found": total_sources,
            "min_required": self.min_sources,
            "domains_covered": len(domains),
            "notes": f"Checked {total_sources} sources from {len(domains)} domains"
        }

    def _check_quality(self, synthesis: Dict, phase2_results: Dict) -> Dict[str, Any]:
        """Check if sources are credible and relevant."""
        confidence = synthesis.get("confidence", 0.0)
        met = confidence >= self.min_confidence

        # Count credible sources (those with credibility signals)
        vendors = phase2_results.get("vendors", [])
        credible_count = 0
        for vendor in vendors:
            if isinstance(vendor, dict):
                credibility = vendor.get("credibility", "")
                # Check for credibility signals
                if any(signal in str(credibility).lower() for signal in ["usda", "licensed", "certified", "years"]):
                    credible_count += 1

        return {
            "met": met,
            "avg_confidence": confidence,
            "min_required": self.min_confidence,
            "credible_sources": credible_count,
            "total_sources": len(vendors),
            "notes": f"Confidence {confidence:.2f}, {credible_count}/{len(vendors)} credible sources"
        }

    def _check_completeness(self, phase2_results: Dict, required_info: List[str], intent: str) -> Dict[str, Any]:
        """Check if all required information fields are present."""
        vendors = phase2_results.get("vendors", [])

        if not vendors:
            return {
                "met": False,
                "required_info": required_info,
                "found_info": [],
                "missing": required_info,
                "notes": "No vendors found"
            }

        # Check first few vendors for completeness
        sample_vendors = vendors[:3]
        found_fields = set()
        missing_fields = set(required_info)

        for vendor in sample_vendors:
            if not isinstance(vendor, dict):
                continue

            for field in required_info:
                if field in vendor and vendor[field]:
                    found_fields.add(field)
                    missing_fields.discard(field)

        met = len(missing_fields) == 0

        return {
            "met": met,
            "required_info": required_info,
            "found_info": list(found_fields),
            "missing": list(missing_fields),
            "notes": f"Present: {', '.join(found_fields) or 'none'}; Missing: {', '.join(missing_fields) or 'none'}"
        }

    def _check_contradictions(self, synthesis: Dict) -> Dict[str, Any]:
        """Check if findings have contradictions."""
        # Check for contradictions field in synthesis
        contradictions = synthesis.get("contradictions", [])

        # Contradictions are "met" if none exist or all are resolved
        met = len(contradictions) == 0

        return {
            "met": met,
            "found": len(contradictions),
            "resolved": 0,  # Would need resolution tracking
            "flagged": len(contradictions),
            "details": contradictions if contradictions else [],
            "notes": f"{'No contradictions' if met else f'{len(contradictions)} unresolved contradictions'}"
        }

    def _generate_next_actions(
        self,
        criteria: Dict[str, Any],
        pass_results: Dict[str, Any],
        intent: str  # Use intent instead of legacy query_type
    ) -> tuple[List[str], List[str]]:
        """
        Generate missing items and next actions based on unmet criteria.

        Args:
            intent: Intent (navigation, site_search, commerce, informational)

        Returns:
            (missing_items, next_actions)
        """
        missing = []
        next_actions = []

        # Coverage not met
        if not criteria["coverage"]["met"]:
            sources_gap = self.min_sources - criteria["coverage"]["sources_found"]
            missing.append(f"Need {sources_gap} more sources")
            next_actions.append(f"Broaden search to find {sources_gap} additional credible sources")
            next_actions.append("Try alternative search engines or forums")

        # Quality not met
        if not criteria["quality"]["met"]:
            conf_gap = self.min_confidence - criteria["quality"]["avg_confidence"]
            missing.append(f"Need higher confidence (currently {criteria['quality']['avg_confidence']:.2f})")
            next_actions.append("Focus on more credible sources (USDA licensed, established domains)")
            next_actions.append("Cross-reference claims with expert sites")

        # Completeness not met
        if not criteria["completeness"]["met"]:
            missing_fields = criteria["completeness"]["missing"]
            for field in missing_fields:
                missing.append(f"Missing field: {field}")

            if "availability" in missing_fields:
                next_actions.append("Deep-crawl vendor catalog pages for current stock information")
                next_actions.append("Visit /available or /inventory sections")

            if "price" in missing_fields or "pricing" in missing_fields:
                next_actions.append("Search specifically for pricing information")
                next_actions.append("Check vendor product pages directly")

            if "contact" in missing_fields:
                next_actions.append("Visit vendor about/contact pages")

            # Generic action for other missing fields
            if missing_fields:
                next_actions.append(f"Search specifically for: {', '.join(missing_fields)}")

        # Contradictions not met
        if not criteria["contradictions"]["met"]:
            missing.append(f"{criteria['contradictions']['found']} contradictions need resolution")
            next_actions.append("Revisit sources with contradictory information")
            next_actions.append("Trust more credible sources when resolving conflicts")

        return missing, next_actions


# Convenience function
async def evaluate_research_satisfaction(
    pass_number: int,
    pass_results: Dict[str, Any],
    required_info: List[str],
    intent: str = "informational",  # Use intent instead of legacy query_type
    min_sources: int = 8,
    min_confidence: float = 0.75
) -> Dict[str, Any]:
    """
    Evaluate research satisfaction (standalone function).

    Args:
        pass_number: Current pass (1-3)
        pass_results: Results from research pass
        required_info: Required information fields
        intent: Intent (navigation, site_search, commerce, informational)
        min_sources: Minimum sources threshold
        min_confidence: Minimum confidence threshold

    Returns:
        Satisfaction evaluation result
    """
    evaluator = SatisfactionEvaluator(min_sources=min_sources, min_confidence=min_confidence)
    return await evaluator.evaluate(pass_number, pass_results, required_info, intent)
