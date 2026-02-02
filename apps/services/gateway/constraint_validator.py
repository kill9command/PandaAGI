"""
gateway/constraint_validator.py

Guide pre-delegation constraint validation.

Purpose:
- Check if Guide has all critical information needed before creating Task Ticket
- Identify missing constraints by query type (commerce_search, research, etc.)
- Generate clarification questions for user
- Prevent wasted research on incomplete/ambiguous queries

Created: 2025-11-17
"""
import logging
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)


# Critical constraints by query type
QUERY_TYPE_CONSTRAINTS = {
    "commerce_search": {
        "critical": ["subject", "location"],  # Must have
        "important": ["budget", "delivery_preference"],  # Nice to have
        "optional": ["timeframe", "specific_features", "brand_preference"]
    },
    "research": {
        "critical": ["subject", "research_goal"],
        "important": ["depth_preference"],  # "quick overview" vs "deep dive"
        "optional": ["perspective", "sources_to_include", "timeframe"]
    },
    "local_service": {
        "critical": ["subject", "location", "timeframe"],
        "important": ["budget", "service_type"],
        "optional": ["preferences", "availability"]
    },
    "informational": {
        "critical": ["subject"],
        "important": ["context", "depth"],
        "optional": ["perspective", "examples"]
    },
    "comparison": {
        "critical": ["subjects_to_compare", "comparison_criteria"],
        "important": ["use_case", "budget"],
        "optional": ["priorities", "must_haves"]
    }
}


class ConstraintValidator:
    """
    Validates that Guide has all critical constraints before delegation.
    """

    def validate(
        self,
        user_query: str,
        intent: str,
        extracted_constraints: Dict[str, Any],
        unified_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate constraints for query type.

        Args:
            user_query: User's original query
            intent: Classified intent (commerce_search, research, etc.)
            extracted_constraints: Constraints extracted from query by Guide
            unified_context: Session context (preferences, prior info)

        Returns:
            {
                "valid": bool,
                "decision": "PROCEED" | "REQUEST_CLARIFICATION",
                "missing_critical": [...],
                "missing_important": [...],
                "clarification_questions": [...],
                "reasoning": str
            }
        """
        # Get required constraints for this query type
        required = QUERY_TYPE_CONSTRAINTS.get(intent, {
            "critical": ["subject"],
            "important": [],
            "optional": []
        })

        # Merge extracted constraints with context
        all_constraints = self._merge_constraints(extracted_constraints, unified_context)

        # Check critical constraints
        missing_critical = []
        for constraint in required["critical"]:
            if not self._has_constraint(constraint, all_constraints):
                missing_critical.append(constraint)

        # Check important constraints
        missing_important = []
        for constraint in required["important"]:
            if not self._has_constraint(constraint, all_constraints):
                missing_important.append(constraint)

        # Decision
        if missing_critical:
            decision = "REQUEST_CLARIFICATION"
            valid = False
            reasoning = f"Missing critical constraints: {', '.join(missing_critical)}"
        else:
            decision = "PROCEED"
            valid = True
            reasoning = "All critical constraints present"

        # Generate clarification questions if needed
        clarification_questions = []
        if not valid:
            clarification_questions = self._generate_questions(
                intent=intent,
                missing_critical=missing_critical,
                missing_important=missing_important,
                user_query=user_query
            )

        logger.info(
            f"[ConstraintValidator] {intent}: {decision} "
            f"(missing_critical: {len(missing_critical)}, missing_important: {len(missing_important)})"
        )

        return {
            "valid": valid,
            "decision": decision,
            "missing_critical": missing_critical,
            "missing_important": missing_important,
            "present_constraints": list(all_constraints.keys()),
            "clarification_questions": clarification_questions,
            "reasoning": reasoning
        }

    def _merge_constraints(
        self,
        extracted: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merge extracted constraints with unified context.

        Context can fill in missing constraints from preferences.
        """
        merged = extracted.copy()

        # Check context for common constraint fields
        preferences = context.get("preferences", {})

        # Location
        if "location" not in merged and "location" in preferences:
            merged["location"] = preferences["location"]

        # Budget
        if "budget" not in merged and "budget_constraint" in preferences:
            merged["budget"] = preferences["budget_constraint"]

        # Other preferences
        for key, value in preferences.items():
            if key not in merged and value:
                merged[key] = value

        return merged

    def _has_constraint(self, constraint: str, all_constraints: Dict) -> bool:
        """
        Check if constraint is present and non-empty.
        """
        value = all_constraints.get(constraint)
        if value is None:
            return False
        if isinstance(value, str) and not value.strip():
            return False
        if isinstance(value, (list, dict)) and not value:
            return False
        return True

    def _generate_questions(
        self,
        intent: str,
        missing_critical: List[str],
        missing_important: List[str],
        user_query: str
    ) -> List[Dict[str, str]]:
        """
        Generate clarification questions for missing constraints.

        Returns:
            [
                {"constraint": "location", "question": "What's your location?"},
                ...
            ]
        """
        questions = []

        # Question templates by constraint
        templates = {
            # Commerce search
            "subject": "What exactly are you looking for?",
            "location": "What's your location or preferred region?",
            "budget": "What's your budget range?",
            "delivery_preference": "Do you prefer local pickup or are you okay with shipping?",
            "timeframe": "When do you need this by?",

            # Research
            "research_goal": "What are you trying to learn or accomplish?",
            "depth_preference": "Do you want a quick overview or comprehensive research?",
            "perspective": "Are you looking for any specific perspective (beginner, expert, etc.)?",

            # Local service
            "service_type": "What type of service are you looking for?",

            # Comparison
            "subjects_to_compare": "What items/options do you want to compare?",
            "comparison_criteria": "What criteria matter to you for this comparison?",
            "use_case": "What will you be using this for?",

            # Generic
            "context": "Can you provide more context about what you're trying to do?",
            "depth": "How detailed would you like the information?"
        }

        # Generate questions for missing critical constraints
        for constraint in missing_critical:
            template = templates.get(constraint, f"Can you provide: {constraint}?")
            questions.append({
                "constraint": constraint,
                "question": template,
                "priority": "critical"
            })

        # Add important constraints if user might not realize they're useful
        for constraint in missing_important[:2]:  # Limit to 2 important questions
            template = templates.get(constraint, f"(Optional) {constraint}?")
            questions.append({
                "constraint": constraint,
                "question": template,
                "priority": "important"
            })

        return questions


def validate_constraints(
    user_query: str,
    intent: str,
    extracted_constraints: Dict[str, Any],
    unified_context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Validate constraints (standalone function).

    This is the main entry point for Guide to check constraints before delegation.
    """
    validator = ConstraintValidator()
    return validator.validate(user_query, intent, extracted_constraints, unified_context)


# Example clarification response builder
def build_clarification_response(validation_result: Dict) -> str:
    """
    Build a natural language clarification response for user.

    Args:
        validation_result: Result from validate_constraints()

    Returns:
        Natural language question(s) for user
    """
    if validation_result["valid"]:
        return ""  # No clarification needed

    questions = validation_result["clarification_questions"]

    if not questions:
        return "I need a bit more information to help you with this."

    # Build response
    response_parts = []

    # Opening
    if len(questions) == 1:
        response_parts.append("I can help with that! To give you the best results, I need to know:")
    else:
        response_parts.append("I can help with that! To give you the best results, I have a few questions:")

    # Critical questions
    critical = [q for q in questions if q["priority"] == "critical"]
    for q in critical:
        response_parts.append(f"- {q['question']}")

    # Important questions (optional)
    important = [q for q in questions if q["priority"] == "important"]
    if important:
        response_parts.append("\nOptional (but helpful):")
        for q in important:
            response_parts.append(f"- {q['question']}")

    # Closing
    response_parts.append("\nOnce I know this, I'll search for the best options for you.")

    return "\n".join(response_parts)


# Testing
if __name__ == "__main__":
    # Test case 1: Missing location
    result = validate_constraints(
        user_query="Find Syrian hamster breeders under $40",
        intent="commerce_search",
        extracted_constraints={
            "subject": "Syrian hamster breeders",
            "budget": "$40"
        },
        unified_context={}
    )

    print("Test 1: Missing location")
    print(f"Valid: {result['valid']}")
    print(f"Decision: {result['decision']}")
    print(f"Missing: {result['missing_critical']}")
    print(f"Questions: {result['clarification_questions']}")
    print()

    # Test case 2: All constraints present
    result2 = validate_constraints(
        user_query="Find Syrian hamster breeders in California under $40",
        intent="commerce_search",
        extracted_constraints={
            "subject": "Syrian hamster breeders",
            "budget": "$40",
            "location": "California"
        },
        unified_context={}
    )

    print("Test 2: All constraints present")
    print(f"Valid: {result2['valid']}")
    print(f"Decision: {result2['decision']}")
    print()

    # Test case 3: Build clarification response
    response = build_clarification_response(result)
    print("Test 3: Clarification response")
    print(response)
