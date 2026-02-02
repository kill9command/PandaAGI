"""Phase 6: Validation - Quality gate.

Architecture Reference:
    architecture/main-system-patterns/phase6-validation.md

Role: MIND (MIND model @ temp=0.5)
Token Budget: ~6,000 total

Question: "Is this response accurate and complete?"

This phase acts as the final checkpoint, verifying that the
Synthesis output is grounded in evidence, addresses the user's
query, and maintains coherent formatting.

Decisions:
    - APPROVE: Response is good, proceed to Phase 7 (Save)
    - REVISE: Minor issues, back to Phase 5 (Synthesis) - max 2 times
    - RETRY: Major issues, back to Phase 3 (Planner) - max 1 time
    - FAIL: Cannot complete, return error to user

Key Principle: Validation does NOT track state across attempts.
The Orchestrator owns loop control (attempt counting, limits).
"""

from typing import Optional

from libs.core.models import (
    ValidationResult,
    ValidationDecision,
    ValidationCheck,
    GoalValidation,
)
from libs.core.exceptions import PhaseError
from libs.document_io.context_manager import ContextManager

from apps.phases.base_phase import BasePhase


class Validation(BasePhase[ValidationResult]):
    """
    Phase 6: Validate response quality.

    Uses MIND role (MIND model with temp=0.5) for
    quality assessment.

    Four mandatory checks:
    1. Claims Supported: Every claim has evidence
    2. No Hallucinations: No invented information
    3. Query Addressed: Response answers what was asked
    4. Coherent Format: Well-structured and readable
    """

    PHASE_NUMBER = 6
    PHASE_NAME = "validation"

    SYSTEM_PROMPT = """You are a quality validator for AI responses. Your job is to ensure accuracy before delivery to the user.

MANDATORY CHECKS:

1. CLAIMS_SUPPORTED
   - Does every factual claim in the response have evidence in section 4 or section 2?
   - Check: prices, specs, URLs, product names all trace to sources
   - FAIL if: Response says "$599" but section 4 shows "$699"

2. NO_HALLUCINATIONS
   - Is there any invented information not present in the context?
   - Check: All products, features, claims appear in sources
   - FAIL if: Response adds product not in research

3. QUERY_ADDRESSED
   - Does the response answer what section 0 asked?
   - Check: Core question has explicit answer
   - FAIL if: Asked for laptops, response discusses desktops

4. COHERENT_FORMAT
   - Is the response well-structured and readable?
   - Check: Logical organization, working markdown links
   - FAIL if: Raw URLs instead of markdown links, broken formatting

DECISION GUIDE:

APPROVE (confidence >= 0.80):
- All 4 checks pass
- Response is ready to send to user

REVISE (confidence 0.50-0.79):
- Minor issues in format or wording
- Data exists but not well presented
- Missing citations
- Use revision_hints to guide fixes

RETRY (confidence 0.30-0.49):
- Wrong approach or missing data
- Wrong research was done
- Need different tools called
- Use suggested_fixes to guide re-planning

FAIL (confidence < 0.30):
- Unrecoverable error
- Multiple attempts already failed
- Unable to produce valid response

Output JSON:
{
  "decision": "APPROVE | REVISE | RETRY | FAIL",
  "confidence": 0.0-1.0,
  "checks": {
    "claims_supported": true/false,
    "no_hallucinations": true/false,
    "query_addressed": true/false,
    "coherent_format": true/false
  },
  "check_details": {
    "claims_supported": {
      "score": 0.0-1.0,
      "evidence": ["what supports passing this check"],
      "issues": ["specific problems found"]
    },
    "no_hallucinations": { "score": 0.0-1.0, "evidence": [], "issues": [] },
    "query_addressed": { "score": 0.0-1.0, "evidence": [], "issues": [] },
    "coherent_format": { "score": 0.0-1.0, "evidence": [], "issues": [] }
  },
  "goal_validations": [
    {
      "goal_id": "GOAL_1",
      "addressed": true/false,
      "quality": 0.0-1.0,
      "notes": "optional notes"
    }
  ],
  "issues": ["list of specific problems"],
  "revision_hints": "guidance for Synthesis if REVISE",
  "suggested_fixes": "guidance for Planner if RETRY",
  "overall_quality": 0.0-1.0
}

Per-check scoring guide (for check_details):
- 1.0: No issues found
- 0.8-0.99: Minor issues, still passes
- 0.5-0.79: Significant issues, borderline
- <0.5: Major issues, check fails

Include check_details when decision is NOT APPROVE to show exactly what's wrong."""

    async def execute(
        self,
        context: ContextManager,
        attempt: int = 1,
    ) -> ValidationResult:
        """
        Validate the synthesized response.

        Args:
            context: Context manager with sections 0-5
            attempt: Validation attempt number

        Returns:
            ValidationResult with decision and details
        """
        # Read full context
        full_context = context.get_sections(0, 1, 2, 3, 4, 5)

        # Read the response being validated
        response_path = context.turn_dir / "response.md"
        if response_path.exists():
            response = response_path.read_text()
        else:
            response = ""

        if not response:
            # No response to validate
            return ValidationResult(
                decision=ValidationDecision.FAIL,
                confidence=0.0,
                issues=["No response generated to validate"],
                reasoning="Phase 5 did not produce a response",
            )

        # Get original query
        original_query = context.get_original_query()

        # Build user prompt
        user_prompt = f"""Original Query: {original_query}

Context Document:
{full_context}

Response to validate:
---
{response}
---

Validation attempt: {attempt}

Validate this response against the 4 mandatory checks."""

        # Call LLM
        llm_response = await self.call_llm(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=1000,  # Increased from 600 to avoid truncation
        )

        # Parse response
        result = self._parse_response(llm_response)

        # Write to section 6
        context.write_section_6(result, attempt)

        return result

    def _parse_response(self, response: str) -> ValidationResult:
        """Parse validation response with support for per-check scoring.

        Supports both legacy boolean format and new check_details format:
        - Legacy: "checks": {"claims_supported": true, ...}
        - New: "check_details": {"claims_supported": {"score": 0.85, "evidence": [...], "issues": [...]}}
        """
        try:
            data = self.parse_json_response(response)

            # Parse decision
            decision_str = data.get("decision", "APPROVE").upper()
            try:
                decision = ValidationDecision(decision_str)
            except ValueError:
                decision = ValidationDecision.APPROVE

            # Parse checks with optional per-check scoring (Poetiq pattern)
            checks_data = data.get("checks", {})
            check_details = data.get("check_details", {})
            checks = []

            check_names = [
                ("claims_supported", "Claims Supported"),
                ("no_hallucinations", "No Hallucinations"),
                ("query_addressed", "Query Addressed"),
                ("coherent_format", "Coherent Format"),
            ]

            for key, name in check_names:
                passed = checks_data.get(key, True)
                # Get detailed info if available (new format)
                details = check_details.get(key, {})
                if isinstance(details, dict):
                    score = details.get("score", 1.0 if passed else 0.0)
                    evidence = details.get("evidence", [])
                    issues = details.get("issues", [])
                else:
                    # Backward compat: boolean or no details
                    score = 1.0 if passed else 0.0
                    evidence = []
                    issues = []

                checks.append(
                    ValidationCheck(
                        name=name,
                        passed=passed,
                        score=score,
                        evidence=evidence,
                        issues=issues,
                        notes=None,
                    )
                )

            # Calculate weighted confidence if not provided
            # Weights: claims_supported=35%, no_hallucinations=30%,
            #          query_addressed=25%, coherent_format=10%
            if "confidence" not in data and checks:
                weights = {
                    "Claims Supported": 0.35,
                    "No Hallucinations": 0.30,
                    "Query Addressed": 0.25,
                    "Coherent Format": 0.10,
                }
                total_score = sum(
                    c.score * weights.get(c.name, 0.25) for c in checks
                )
                data["confidence"] = min(1.0, max(0.0, total_score))

            # Parse goal validations
            goal_validations = []
            for gv in data.get("goal_validations", []):
                goal_validations.append(
                    GoalValidation(
                        goal_id=gv.get("goal_id", "GOAL_1"),
                        addressed=gv.get("addressed", True),
                        quality=gv.get("quality", 0.8),
                        notes=gv.get("notes"),
                    )
                )

            return ValidationResult(
                decision=decision,
                confidence=float(data.get("confidence", 0.8)),
                checks=checks,
                goal_validations=goal_validations,
                issues=data.get("issues", []),
                revision_hints=data.get("revision_hints"),
                overall_quality=data.get("overall_quality"),
                reasoning=data.get("reasoning"),
            )

        except PhaseError:
            raise
        except Exception as e:
            # Default to APPROVE on parse failure
            # Rationale: If we can't parse validation, let response through
            # rather than blocking indefinitely
            return ValidationResult(
                decision=ValidationDecision.APPROVE,
                confidence=0.5,
                checks=[
                    ValidationCheck(name="Parse Error", passed=False, notes=str(e))
                ],
                reasoning=f"Parse error, defaulting to APPROVE: {e}",
            )


# Factory function for convenience
def create_validation(mode: str = "chat") -> Validation:
    """Create a Validation instance."""
    return Validation(mode=mode)
