"""
Contract enforcement and repair for Pandora Gateway.

This module enforces contracts between components and automatically repairs
malformed responses when possible. The goal is to NEVER crash due to unexpected
LLM output formats.

Philosophy:
- Parse, don't validate (always return a valid object)
- Repair when possible (extract usable data from malformed responses)
- Fallback to safe defaults (better a degraded response than a crash)
- Log everything (violations help us improve prompts)
"""

import json
import logging
import re
from typing import Any, Dict, Optional, TypeVar, Type, List
from pydantic import ValidationError

from apps.services.gateway.contracts import (
    GuideResponse,
    CoordinatorResponse,
    ToolCall,
    ToolOutput,
    CapsuleEnvelope,
    Claim,
    TokenBudget,
)

logger = logging.getLogger(__name__)

T = TypeVar('T')


class ContractViolation(Exception):
    """Raised when a contract cannot be enforced even with repair"""
    pass


class ContractEnforcer:
    """
    Enforces contracts between components with automatic repair.

    Each parse_* method:
    1. Tries direct Pydantic parsing
    2. If that fails, attempts repair
    3. If repair fails, returns safe default
    4. NEVER raises exceptions (except ContractViolation for unrecoverable errors)
    """

    @staticmethod
    def parse_guide_response(raw: Any, fallback_answer: str = None) -> GuideResponse:
        """
        Parse Guide response, repair if needed, never fail.

        Args:
            raw: Raw response from Guide (dict, string, or other)
            fallback_answer: Optional fallback answer if repair fails

        Returns:
            Valid GuideResponse or safe default
        """
        # Handle non-dict responses
        if not isinstance(raw, dict):
            logger.warning(f"[Contract] Guide returned non-dict: {type(raw)}")
            if isinstance(raw, str):
                # Treat raw string as answer
                try:
                    return GuideResponse(answer=raw)
                except ValidationError:
                    pass

            # Give up, use fallback
            return GuideResponse(
                answer=fallback_answer or "I encountered an issue processing your request. Could you rephrase?",
                confidence=0.0,
                needs_more_context=True
            )

        try:
            # Try direct parse
            return GuideResponse(**raw)
        except ValidationError as e:
            logger.warning(f"[Contract] Guide response invalid: {e}")

            # Attempt repair
            repaired = ContractEnforcer._repair_guide_response(raw)
            try:
                return GuideResponse(**repaired)
            except ValidationError as e2:
                # Repair failed, use fallback
                logger.error(f"[Contract] Guide response unrepairable: {e2}")
                return GuideResponse(
                    answer=fallback_answer or "I encountered an issue processing your request. Could you rephrase?",
                    confidence=0.0,
                    needs_more_context=True
                )

    @staticmethod
    def _repair_guide_response(raw: Dict[str, Any]) -> Dict[str, Any]:
        """Attempt to repair malformed Guide response"""
        repaired = {}

        # Extract answer (REQUIRED)
        answer = (
            raw.get("answer") or
            raw.get("response") or
            raw.get("text") or
            raw.get("content") or
            raw.get("message") or
            ""
        )

        # If no obvious answer field, look for ANY substantial string
        if not answer or not answer.strip():
            for key, value in raw.items():
                if isinstance(value, str) and len(value) > 20:
                    answer = value
                    logger.info(f"[Contract] Using '{key}' field as answer")
                    break

        # Last resort: JSON dump the whole thing
        if not answer or not answer.strip():
            answer = json.dumps(raw, indent=2)
            logger.warning("[Contract] No answer field found, dumping raw JSON")

        repaired["answer"] = answer or "No response generated"

        # Extract confidence (optional)
        confidence = raw.get("confidence", 0.5)
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            confidence = 0.5
        repaired["confidence"] = float(confidence)

        # Extract sources (optional)
        sources = raw.get("sources", [])
        if not isinstance(sources, list):
            sources = []
        repaired["sources"] = [str(s) for s in sources if s]

        # Extract needs_more_context (optional)
        needs_more = raw.get("needs_more_context", False)
        repaired["needs_more_context"] = bool(needs_more)

        return repaired

    @staticmethod
    def parse_coordinator_response(raw: Any) -> CoordinatorResponse:
        """
        Parse Coordinator response, repair if needed, never fail.

        Returns:
            Valid CoordinatorResponse or safe default (empty plan signals failure)
        """
        if not isinstance(raw, dict):
            logger.warning(f"[Contract] Coordinator returned non-dict: {type(raw)}")
            return CoordinatorResponse(
                plan=[],
                notes={"error": f"Coordinator returned {type(raw).__name__}, expected dict"},
                confidence=0.0
            )

        try:
            return CoordinatorResponse(**raw)
        except ValidationError as e:
            logger.warning(f"[Contract] Coordinator response invalid: {e}")

            # Attempt repair
            repaired = ContractEnforcer._repair_coordinator_response(raw)
            try:
                return CoordinatorResponse(**repaired)
            except ValidationError as e2:
                # Repair failed, return empty plan
                logger.error(f"[Contract] Coordinator response unrepairable: {e2}")
                return CoordinatorResponse(
                    plan=[],
                    notes={"error": "Coordinator response malformed", "details": str(e2)},
                    confidence=0.0
                )

    @staticmethod
    def _repair_coordinator_response(raw: Dict[str, Any]) -> Dict[str, Any]:
        """Attempt to repair malformed Coordinator response"""
        repaired = {}

        # Extract plan (REQUIRED)
        plan = raw.get("plan", [])
        if not isinstance(plan, list):
            logger.warning(f"[Contract] Plan is {type(plan)}, expected list")
            plan = []

        # Validate and repair each tool call
        valid_plan = []
        for idx, item in enumerate(plan):
            if not isinstance(item, dict):
                logger.warning(f"[Contract] Plan item {idx} is {type(item)}, skipping")
                continue

            # Extract tool name (try various field names)
            tool = (
                item.get("tool") or
                item.get("name") or
                item.get("function") or
                item.get("action") or
                ""
            )

            if not tool or not isinstance(tool, str):
                logger.warning(f"[Contract] Plan item {idx} has no valid tool name")
                continue

            # Extract args (try various field names)
            args = (
                item.get("args") or
                item.get("arguments") or
                item.get("params") or
                item.get("parameters") or
                {}
            )

            if not isinstance(args, dict):
                logger.warning(f"[Contract] Args for {tool} is {type(args)}, using empty dict")
                args = {}

            valid_plan.append({
                "tool": tool.strip(),
                "args": args,
                "required": item.get("required", True)
            })

        repaired["plan"] = valid_plan

        # Extract optional fields with fallbacks
        repaired["reflection"] = str(raw.get("reflection", ""))[:500]  # Limit length
        repaired["notes"] = raw.get("notes", {}) if isinstance(raw.get("notes"), dict) else {}

        confidence = raw.get("confidence", 0.8)
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            confidence = 0.8
        repaired["confidence"] = float(confidence)

        return repaired

    @staticmethod
    def parse_tool_output(raw: Any, tool_name: str = "unknown") -> ToolOutput:
        """
        Parse tool output, wrap if needed, never fail.

        Args:
            raw: Raw output from tool (any type)
            tool_name: Name of tool for logging

        Returns:
            Valid ToolOutput
        """
        # If already a dict with success field, try direct parse
        if isinstance(raw, dict) and "success" in raw:
            try:
                return ToolOutput(**raw)
            except ValidationError as e:
                logger.warning(f"[Contract] Tool {tool_name} output invalid: {e}")

        # Wrap raw output based on type
        if isinstance(raw, dict) and "error" in raw:
            # Looks like an error response
            return ToolOutput(
                success=False,
                data=raw.get("data"),
                error=str(raw["error"]),
                metadata={"tool": tool_name, "raw_keys": list(raw.keys())}
            )
        elif isinstance(raw, dict) and any(k in raw for k in ["result", "data", "output"]):
            # Looks like a success response
            data = raw.get("result") or raw.get("data") or raw.get("output")
            return ToolOutput(
                success=True,
                data=data,
                error=None,
                metadata={"tool": tool_name, "raw_type": type(raw).__name__}
            )
        else:
            # Generic success wrapper
            return ToolOutput(
                success=True,
                data=raw,
                error=None,
                metadata={"tool": tool_name, "raw_type": type(raw).__name__}
            )

    @staticmethod
    def parse_capsule(raw: Any) -> CapsuleEnvelope:
        """
        Parse capsule envelope, repair if needed, never fail.

        Returns:
            Valid CapsuleEnvelope or empty capsule (safe default)
        """
        if not isinstance(raw, dict):
            logger.warning(f"[Contract] Capsule is {type(raw)}, expected dict")
            return CapsuleEnvelope(
                claims=[],
                summary="",
                status="error",
                metadata={"error": f"Capsule was {type(raw).__name__}, not dict"}
            )

        try:
            return CapsuleEnvelope(**raw)
        except ValidationError as e:
            logger.warning(f"[Contract] Capsule invalid: {e}")

            # Try to extract what we can
            claims = []
            raw_claims = raw.get("claims", [])
            if isinstance(raw_claims, list):
                for claim_data in raw_claims:
                    try:
                        claim = Claim(**claim_data)
                        claims.append(claim)
                    except ValidationError:
                        # Skip invalid claims
                        continue

            # Return partial capsule
            return CapsuleEnvelope(
                claims=claims,
                summary=str(raw.get("summary", ""))[:2000],
                status="partial" if claims else "error",
                metadata={"validation_error": str(e), "recovered_claims": len(claims)}
            )


class TokenBudgetEnforcer:
    """
    Enforces token budgets at component boundaries.

    Prevents cascading budget overruns by truncating content
    before it's passed to LLMs.
    """

    def __init__(self, budget: Optional[TokenBudget] = None):
        self.budget = budget or TokenBudget()
        self.usage = {}  # Track actual usage per component

    def check_budget(self, component: str, tokens_used: int) -> bool:
        """
        Check if component is within budget.

        Returns:
            True if within budget, False if over
        """
        allocated = getattr(self.budget, component.replace('-', '_'), 500)

        # Record usage
        self.usage[component] = tokens_used

        if tokens_used > allocated:
            logger.warning(
                f"[Budget] {component} over budget: {tokens_used}/{allocated} tokens "
                f"({tokens_used - allocated} over)"
            )
            return False

        return True

    def enforce_limit(
        self,
        component: str,
        text: str,
        max_tokens: Optional[int] = None
    ) -> str:
        """
        Truncate text to fit within component's budget.

        Args:
            component: Component name (maps to budget field)
            text: Text to potentially truncate
            max_tokens: Optional override for token limit

        Returns:
            Truncated text if needed
        """
        limit = max_tokens or getattr(self.budget, component.replace('-', '_'), 500)

        # Rough estimate: 1 token ≈ 4 characters for English text
        # This is conservative (actual is ~3.5 chars/token for GPT models)
        max_chars = limit * 4

        if len(text) <= max_chars:
            return text

        # Truncate and add marker
        logger.info(
            f"[Budget] Truncating {component} from {len(text)} to {max_chars} chars "
            f"({limit} token limit)"
        )

        # Try to truncate at sentence boundary if possible
        truncated = text[:max_chars]
        last_period = truncated.rfind('.')
        last_newline = truncated.rfind('\n')
        last_break = max(last_period, last_newline)

        if last_break > max_chars * 0.8:  # If we're within 20% of limit, use sentence boundary
            truncated = text[:last_break + 1]

        return truncated + "\n\n... [truncated to fit token budget]"

    def get_usage_report(self) -> Dict[str, Any]:
        """Get usage report for debugging"""
        total_used = sum(self.usage.values())
        total_allocated = sum(
            getattr(self.budget, field, 0)
            for field in ['system_prompt', 'user_query', 'guide_response',
                         'coordinator_plan', 'tool_outputs', 'capsule', 'context', 'buffer']
        )

        return {
            "total_budget": self.budget.total,
            "total_allocated": total_allocated,
            "total_used": total_used,
            "remaining": self.budget.total - total_used,
            "utilization": round(total_used / self.budget.total * 100, 1),
            "per_component": self.usage,
            "over_budget": {
                comp: used for comp, used in self.usage.items()
                if used > getattr(self.budget, comp.replace('-', '_'), 500)
            }
        }


class ContractMonitor:
    """
    Monitors contract violations for debugging and improvement.

    Tracks violations to identify problematic patterns.
    """

    def __init__(self):
        self.violations: List[Dict[str, Any]] = []
        self.repair_attempts: Dict[str, int] = {}  # component -> count
        self.repair_successes: Dict[str, int] = {}  # component -> count

    def record_violation(
        self,
        component: str,
        contract: str,
        error: str,
        raw_data: Any,
        repaired: bool,
        repair_strategy: Optional[str] = None
    ):
        """Record a contract violation"""
        self.violations.append({
            "component": component,
            "contract": contract,
            "error": str(error),
            "timestamp": __import__('time').time(),
            "repaired": repaired,
            "repair_strategy": repair_strategy,
            "raw_data_type": type(raw_data).__name__,
            "raw_data_preview": str(raw_data)[:200]
        })

        # Update counters
        self.repair_attempts[component] = self.repair_attempts.get(component, 0) + 1
        if repaired:
            self.repair_successes[component] = self.repair_successes.get(component, 0) + 1

        # Keep only recent violations (last 100)
        if len(self.violations) > 100:
            self.violations = self.violations[-100:]

    def get_summary(self) -> Dict[str, Any]:
        """Get violation summary for debugging"""
        if not self.violations:
            return {
                "total_violations": 0,
                "components": {},
                "recent": []
            }

        # Aggregate by component
        by_component = {}
        for v in self.violations:
            comp = v["component"]
            if comp not in by_component:
                by_component[comp] = {
                    "total": 0,
                    "repaired": 0,
                    "failed": 0,
                    "common_errors": {}
                }

            by_component[comp]["total"] += 1
            if v["repaired"]:
                by_component[comp]["repaired"] += 1
            else:
                by_component[comp]["failed"] += 1

            # Track common error patterns
            error_key = v["error"][:100]  # First 100 chars
            by_component[comp]["common_errors"][error_key] = \
                by_component[comp]["common_errors"].get(error_key, 0) + 1

        return {
            "total_violations": len(self.violations),
            "components": by_component,
            "repair_success_rate": {
                comp: round(self.repair_successes.get(comp, 0) / self.repair_attempts.get(comp, 1) * 100, 1)
                for comp in self.repair_attempts.keys()
            },
            "recent": self.violations[-10:]  # Last 10 violations
        }

    def clear(self):
        """Clear all violations (useful for testing)"""
        self.violations.clear()
        self.repair_attempts.clear()
        self.repair_successes.clear()


# Global instances
CONTRACT_ENFORCER = ContractEnforcer()
CONTRACT_MONITOR = ContractMonitor()
