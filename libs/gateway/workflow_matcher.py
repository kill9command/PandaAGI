"""
Workflow Matcher - Matches commands to workflows.

Uses multiple strategies to match a natural language command
or intent to the appropriate workflow.

Usage:
    matcher = WorkflowMatcher(registry)
    match = matcher.match(command, context_doc)
    if match and match.confidence > 0.7:
        # Execute the workflow
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from libs.gateway.workflow_registry import WorkflowRegistry, Workflow

logger = logging.getLogger(__name__)


@dataclass
class WorkflowMatch:
    """Result of workflow matching."""
    workflow: Workflow
    confidence: float
    matched_trigger: str
    extracted_params: Dict[str, Any] = field(default_factory=dict)
    match_strategy: str = ""  # "intent", "trigger", "semantic"


class WorkflowMatcher:
    """
    Matches natural language commands to workflows.

    Matching strategies (in order):
    1. Intent-based match (from Phase 0 action_needed)
    2. Trigger pattern match
    3. Semantic similarity (optional, LLM-based)
    """

    def __init__(
        self,
        registry: WorkflowRegistry,
        llm_client: Optional[Any] = None,
    ):
        self.registry = registry
        self.llm_client = llm_client

    def match(
        self,
        command: str,
        context_doc: Optional[Any] = None,
    ) -> Optional[WorkflowMatch]:
        """
        Match a command to a workflow.

        Args:
            command: Natural language command or need
            context_doc: Context document with intent info

        Returns:
            WorkflowMatch if found, None otherwise
        """
        # Strategy 1: Intent-based match
        intent = self._get_intent(context_doc)
        if intent:
            intent_matches = self.registry.get_by_intent(intent)
            logger.debug(f"[WorkflowMatcher] Intent '{intent}' matches: {[w.name for w in intent_matches]}")

            if len(intent_matches) == 1:
                workflow = intent_matches[0]
                params = self._extract_params(command, workflow)
                return WorkflowMatch(
                    workflow=workflow,
                    confidence=0.9,
                    matched_trigger=f"intent:{intent}",
                    extracted_params=params,
                    match_strategy="intent",
                )

        # Strategy 2: Trigger pattern match
        for workflow in self.registry.all():
            for trigger in workflow.triggers:
                # Skip dict-style triggers (intent: X) and string intent triggers
                if isinstance(trigger, dict):
                    continue
                if not isinstance(trigger, str):
                    continue
                if trigger.startswith("intent:"):
                    continue  # Already handled above

                match_result = self._matches_trigger(command, trigger)
                if match_result:
                    params = {**match_result, **self._extract_params(command, workflow)}
                    return WorkflowMatch(
                        workflow=workflow,
                        confidence=0.85,
                        matched_trigger=trigger,
                        extracted_params=params,
                        match_strategy="trigger",
                    )

        # Strategy 3: Semantic match (if multiple intent matches or no match)
        if intent and len(intent_matches) > 1:
            best = self._semantic_match(command, intent_matches)
            if best:
                return best

        # Strategy 4: Best-effort keyword match
        keyword_match = self._keyword_match(command)
        if keyword_match:
            return keyword_match

        logger.debug(f"[WorkflowMatcher] No match for: {command[:50]}...")
        return None

    def match_by_intent(
        self,
        intent: str,
        action_needed: Optional[str] = None,
    ) -> Optional[WorkflowMatch]:
        """
        Match directly by intent without parsing command.

        Useful when Phase 0 has already determined intent.
        """
        # Check action_needed first (more specific)
        if action_needed:
            workflows = self.registry.get_by_intent(action_needed)
            if len(workflows) == 1:
                return WorkflowMatch(
                    workflow=workflows[0],
                    confidence=0.95,
                    matched_trigger=f"intent:{action_needed}",
                    match_strategy="intent",
                )

        # Fall back to intent
        workflows = self.registry.get_by_intent(intent)
        if len(workflows) == 1:
            return WorkflowMatch(
                workflow=workflows[0],
                confidence=0.9,
                matched_trigger=f"intent:{intent}",
                match_strategy="intent",
            )
        elif len(workflows) > 1:
            # Multiple matches - pick first (research types)
            logger.info(f"[WorkflowMatcher] Multiple workflows for intent '{intent}', using first")
            return WorkflowMatch(
                workflow=workflows[0],
                confidence=0.75,
                matched_trigger=f"intent:{intent}",
                match_strategy="intent",
            )

        return None

    def _get_intent(self, context_doc: Optional[Any]) -> Optional[str]:
        """Extract intent from context document."""
        if context_doc is None:
            return None

        # Try different attribute names
        for attr in ["action_needed", "intent", "content_type"]:
            if hasattr(context_doc, attr):
                val = getattr(context_doc, attr)
                if val:
                    return val

        # Try nested in analysis
        if hasattr(context_doc, "analysis"):
            analysis = context_doc.analysis
            if isinstance(analysis, dict):
                return analysis.get("action_needed") or analysis.get("intent")

        return None

    def _matches_trigger(
        self,
        command: str,
        trigger: str
    ) -> Optional[Dict[str, str]]:
        """
        Check if command matches trigger pattern.

        Returns:
            Dict of extracted params if matched, None otherwise
        """
        command_lower = command.lower().strip()
        trigger_lower = trigger.lower().strip()

        # Pattern with placeholder: "research {topic}"
        if "{" in trigger:
            pattern = self._trigger_to_regex(trigger_lower)
            match = re.match(pattern, command_lower, re.IGNORECASE)
            if match:
                return match.groupdict()

        # Literal substring match
        if trigger_lower in command_lower:
            return {}

        # Word-boundary match for short triggers
        if len(trigger_lower.split()) <= 2:
            pattern = rf'\b{re.escape(trigger_lower)}\b'
            if re.search(pattern, command_lower, re.IGNORECASE):
                return {}

        return None

    def _trigger_to_regex(self, trigger: str) -> str:
        """Convert trigger pattern to regex."""
        # Escape special chars but preserve {placeholder}
        pattern = re.escape(trigger)
        # Convert \{name\} back to (?P<name>.+)
        pattern = re.sub(r'\\{(\w+)\\}', r'(?P<\1>.+)', pattern)
        return f"^{pattern}$"

    def _extract_params(
        self,
        command: str,
        workflow: Workflow
    ) -> Dict[str, Any]:
        """Extract parameters from command using workflow triggers."""
        params = {}

        for trigger in workflow.triggers:
            # Skip non-string triggers
            if not isinstance(trigger, str):
                continue
            if trigger.startswith("intent:"):
                continue

            if "{" in trigger:
                pattern = self._trigger_to_regex(trigger.lower())
                match = re.match(pattern, command.lower())
                if match:
                    params.update(match.groupdict())

        # Also try to extract common parameters
        params.update(self._extract_common_params(command))

        return params

    def _extract_common_params(self, command: str) -> Dict[str, str]:
        """Extract commonly needed parameters from command."""
        params = {}

        # Extract quoted strings as potential topics
        quoted = re.findall(r'"([^"]+)"', command)
        if quoted:
            params["quoted_topic"] = quoted[0]

        # Extract "for X" patterns
        for_match = re.search(r'\bfor\s+(.+?)(?:\s+(?:under|less|more|with|that)\b|$)', command, re.IGNORECASE)
        if for_match:
            params["for_subject"] = for_match.group(1).strip()

        # Extract price constraints
        price_match = re.search(r'(?:under|less than|below)\s*\$?(\d+)', command, re.IGNORECASE)
        if price_match:
            params["max_price"] = int(price_match.group(1))

        price_match = re.search(r'(?:over|more than|above)\s*\$?(\d+)', command, re.IGNORECASE)
        if price_match:
            params["min_price"] = int(price_match.group(1))

        return params

    def _semantic_match(
        self,
        command: str,
        candidates: List[Workflow]
    ) -> Optional[WorkflowMatch]:
        """Use LLM to pick best workflow from candidates."""
        if not self.llm_client:
            return None

        # Build prompt
        descriptions = "\n".join([
            f"{i+1}. {w.name}: {w.description[:100]}"
            for i, w in enumerate(candidates)
        ])

        prompt = f"""Given this command: "{command}"

Which workflow best matches?
{descriptions}

Reply with just the number (1, 2, etc.) or 0 if none match."""

        try:
            response = self.llm_client.call_sync(
                prompt=prompt,
                role="reflex",
                max_tokens=10,
                temperature=0.1,
            )

            idx = int(response.strip()) - 1
            if 0 <= idx < len(candidates):
                return WorkflowMatch(
                    workflow=candidates[idx],
                    confidence=0.7,
                    matched_trigger="semantic",
                    extracted_params=self._extract_params(command, candidates[idx]),
                    match_strategy="semantic",
                )
        except (ValueError, AttributeError):
            pass

        return None

    def _keyword_match(self, command: str) -> Optional[WorkflowMatch]:
        """
        Best-effort keyword-based matching.

        Falls back to this when other strategies fail.
        """
        command_lower = command.lower()

        # Research keywords
        research_keywords = ["search", "find", "look for", "research", "what", "how", "best"]
        commerce_keywords = ["buy", "purchase", "price", "cheapest", "cost", "shop"]

        is_research = any(kw in command_lower for kw in research_keywords)
        is_commerce = any(kw in command_lower for kw in commerce_keywords)

        if is_commerce:
            workflow = self.registry.get("product_search")
            if workflow:
                return WorkflowMatch(
                    workflow=workflow,
                    confidence=0.6,
                    matched_trigger="keyword:commerce",
                    extracted_params=self._extract_common_params(command),
                    match_strategy="keyword",
                )

        if is_research:
            workflow = self.registry.get("intelligence_search")
            if workflow:
                return WorkflowMatch(
                    workflow=workflow,
                    confidence=0.6,
                    matched_trigger="keyword:research",
                    extracted_params=self._extract_common_params(command),
                    match_strategy="keyword",
                )

        return None

    def get_best_workflow_for_intent(
        self,
        intent: str,
        data_requirements: Optional[Dict] = None,
    ) -> Optional[Workflow]:
        """
        Get best workflow for an intent, considering data requirements.

        Used by the integration layer to route based on Phase 0 analysis.
        """
        workflows = self.registry.get_by_intent(intent)

        if not workflows:
            return None

        if len(workflows) == 1:
            return workflows[0]

        # Multiple workflows - use data_requirements to disambiguate
        if data_requirements:
            needs_prices = data_requirements.get("needs_current_prices", False)
            needs_products = data_requirements.get("needs_product_list", False)

            if needs_prices or needs_products:
                # Prefer product_search
                for w in workflows:
                    if "product" in w.name.lower():
                        return w

            # Prefer intelligence_search for informational
            for w in workflows:
                if "intelligence" in w.name.lower():
                    return w

        # Default to first match
        return workflows[0]
