from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ToolParameter:
    """Schema definition for a single tool parameter."""
    name: str
    type: str  # "string", "integer", "number", "boolean", "array", "object"
    required: bool = False
    default: Any = None
    description: str = ""


@dataclass
class ToolMetadata:
    name: str
    auto_args: Dict[str, str] = field(default_factory=dict)
    keywords: List[str] = field(default_factory=list)
    regex: List[str] = field(default_factory=list)
    min_score: float = 0.5
    critical: bool = False
    intents: List[str] = field(default_factory=list)  # NEW: Allowed intent types
    schema: List[ToolParameter] = field(default_factory=list)  # NEW: Parameter schema

    def match_score(self, text: str, intent: Optional[str] = None) -> float:
        """
        Calculate match score with optional intent filtering.

        Args:
            text: Text to match against
            intent: Optional intent type (e.g., "informational", "transactional")
                   If provided and this tool doesn't support it, score is penalized
        """
        text_lower = text.lower()
        score = 0.0

        # Base keyword and regex matching
        if self.keywords and any(k in text_lower for k in self.keywords):
            # keywords carry most of the signal
            score += 0.6
        if self.regex and any(re.search(pattern, text_lower) for pattern in self.regex):
            score += 0.2

        # Intent filtering: penalize if tool doesn't support the detected intent
        if intent and self.intents:
            if intent not in self.intents:
                score *= 0.3  # Heavy penalty for wrong intent
            else:
                score += 0.2  # Bonus for matching intent

        return min(score, 1.0)

    def validate_args(self, args: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate tool arguments against schema.

        Returns:
            (is_valid, error_message)
        """
        if not self.schema:
            # No schema = no validation
            return True, None

        # Check for unknown parameters
        schema_param_names = {param.name for param in self.schema}
        for arg_name in args:
            if arg_name not in schema_param_names:
                return False, f"Parameter '{arg_name}' not in schema for {self.name}"

        # Check for missing required parameters
        for param in self.schema:
            if param.required and param.name not in args:
                return False, f"Required parameter '{param.name}' missing for {self.name}"

        # Type validation (basic)
        for param in self.schema:
            if param.name in args:
                value = args[param.name]
                expected_type = param.type

                # Basic type checking
                if expected_type == "string" and not isinstance(value, str):
                    return False, f"Parameter '{param.name}' should be string, got {type(value).__name__}"
                elif expected_type == "integer" and not isinstance(value, int):
                    return False, f"Parameter '{param.name}' should be integer, got {type(value).__name__}"
                elif expected_type == "number" and not isinstance(value, (int, float)):
                    return False, f"Parameter '{param.name}' should be number, got {type(value).__name__}"
                elif expected_type == "boolean" and not isinstance(value, bool):
                    return False, f"Parameter '{param.name}' should be boolean, got {type(value).__name__}"
                elif expected_type == "array" and not isinstance(value, list):
                    return False, f"Parameter '{param.name}' should be array, got {type(value).__name__}"
                elif expected_type == "object" and not isinstance(value, dict):
                    return False, f"Parameter '{param.name}' should be object, got {type(value).__name__}"

        return True, None


@dataclass
class ToolCatalog:
    tools: List[ToolMetadata]

    @classmethod
    def load(cls, path: Path) -> "ToolCatalog":
        raw = json.loads(path.read_text(encoding="utf-8"))
        tools = [ToolMetadata(**entry) for entry in raw]
        catalog = cls(tools=tools)

        # Add hardcoded schemas for key tools (until schemas are in JSON)
        catalog._add_builtin_schemas()

        return catalog

    def _add_builtin_schemas(self):
        """Add hardcoded schemas for key tools to prevent parameter hallucination."""

        # internet.research schema (NEW unified endpoint)
        internet_research_tool = self.get("internet.research")
        if internet_research_tool:
            internet_research_tool.schema = [
                ToolParameter("query", "string", required=True, description="SIMPLE keyword search query. Use 2-5 keywords maximum. GOOD: 'Syrian hamster breeders', 'hamster care guide'. BAD: 'Find current Syrian hamster listings from reputable sellers' (too verbose, will return 0 results). Search engines work best with concise keyword queries."),
                ToolParameter("intent", "string", required=False, default="informational", description="Query intent: transactional (buying), informational (learning), navigational (finding places/people)"),
                ToolParameter("mode", "string", required=False, default="standard", description="Research mode: 'standard' (1-pass, 60-120s, ~4-8k tokens) or 'deep' (multi-pass until satisfied, 120-240s, ~10-15k tokens). Use 'deep' for comprehensive research, rare items, or when user requests thorough search."),
                ToolParameter("max_results", "integer", required=False, default=5, description="Maximum verified results to return"),
                ToolParameter("min_quality", "number", required=False, default=0.5, description="Minimum quality score (0.0-1.0) to accept"),
                ToolParameter("max_candidates", "integer", required=False, default=15, description="Maximum candidates to check before verification"),
                ToolParameter("human_assist_allowed", "boolean", required=False, default=False, description="Enable human intervention for CAPTCHAs/blockers. RECOMMENDED for transactional queries - significantly improves success rate when sites are protected."),
                ToolParameter("session_id", "string", required=False, default="default", description="Session identifier for browser context persistence (24h). Same session_id reuses cookies from previous CAPTCHA solves."),
                ToolParameter("remaining_token_budget", "integer", required=False, default=8000, description="Token budget from gateway governance for strategy selection (QUICK=2k, STANDARD=4k, DEEP=8k)"),
                ToolParameter("force_strategy", "string", required=False, default=None, description="DEPRECATED: Use 'mode' parameter instead. Force specific strategy mode for testing/coordination: 'standard' (1-pass) or 'deep' (multi-pass until satisfied). If None, Research Role auto-selects based on query complexity and user keywords like 'thorough', 'comprehensive'."),
                ToolParameter("force_refresh", "boolean", required=False, default=False, description="Force fresh research by bypassing intelligence cache. Fresh results replace cached entry. Use when data might be stale or for testing. Normal requests use cache for speed."),
            ]
            logger.info("Added schema for internet.research (unified)")

        # commerce.search_offers schema
        commerce_tool = self.get("commerce.search_offers")
        if commerce_tool:
            commerce_tool.schema = [
                ToolParameter("query", "string", required=True, description="Search query for products (e.g. 'Syrian hamster', 'hamster cage'). Keep it simple - just the item name."),
                ToolParameter("user_id", "string", required=False, description="User identifier"),
                ToolParameter("max_results", "integer", required=False, default=5, description="Maximum results"),
                ToolParameter("extra_query", "string", required=False, default="", description="Additional query terms"),
                ToolParameter("country", "string", required=False, default="us", description="Country code"),
                ToolParameter("language", "string", required=False, default="en", description="Language code"),
                ToolParameter("pause", "number", required=False, default=1.0, description="Rate limit pause"),
            ]
            logger.info("Added schema for commerce.search_offers")

        # purchasing.lookup schema
        purchasing_tool = self.get("purchasing.lookup")
        if purchasing_tool:
            purchasing_tool.schema = [
                ToolParameter("query", "string", required=True, description="Search query"),
                ToolParameter("max_results", "integer", required=False, default=6, description="Maximum results"),
                ToolParameter("extra_query", "string", required=False, default="", description="Additional query terms"),
                ToolParameter("country", "string", required=False, default="us", description="Country code"),
                ToolParameter("language", "string", required=False, default="en", description="Language code"),
                ToolParameter("pause", "number", required=False, default=0.6, description="Rate limit pause"),
                ToolParameter("user_id", "string", required=False, description="User identifier"),
            ]
            logger.info("Added schema for purchasing.lookup")

        # search.orchestrate schema
        search_orch_tool = self.get("search.orchestrate")
        if search_orch_tool:
            search_orch_tool.schema = [
                ToolParameter("query", "string", required=True, description="High-level search query"),
                ToolParameter("intent", "string", required=False, description="Intent hint (transactional, informational, navigational)"),
                ToolParameter("max_results", "integer", required=False, default=10, description="Maximum total results"),
                ToolParameter("use_cache", "boolean", required=False, default=True, description="Whether to use cache"),
                ToolParameter("profile_id", "string", required=False, default="default", description="User profile"),
            ]
            logger.info("Added schema for search.orchestrate")

        # source.aggregate schema (create tool entry if not in catalog)
        source_aggregate_tool = self.get("source.aggregate")
        if not source_aggregate_tool:
            # Create the tool entry
            source_aggregate_tool = ToolMetadata(
                name="source.aggregate",
                keywords=["github", "youtube", "arxiv", "repo", "transcript", "paper", "aggregate"],
                intents=["informational", "navigational"],
            )
            self.tools.append(source_aggregate_tool)
            logger.info("Created source.aggregate tool entry")

        source_aggregate_tool.schema = [
            ToolParameter("source_url", "string", required=True,
                description="URL to aggregate: GitHub repo, YouTube video, arXiv paper, or web page"),
            ToolParameter("source_type", "string", required=False, default="auto",
                description="Source type: auto, github, youtube, arxiv, web"),
            ToolParameter("include_issues", "boolean", required=False, default=False,
                description="GitHub only: include repository issues"),
            ToolParameter("include_prs", "boolean", required=False, default=False,
                description="GitHub only: include pull requests"),
            ToolParameter("max_tokens", "integer", required=False, default=8000,
                description="Maximum output tokens (truncates if larger)"),
        ]
        logger.info("Added schema for source.aggregate")

    def get(self, name: str) -> Optional[ToolMetadata]:
        for tool in self.tools:
            if tool.name == name:
                return tool
        return None

    def validate_tool_call(self, tool_name: str, args: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate a tool call against its schema.

        Returns:
            (is_valid, error_message)
        """
        tool = self.get(tool_name)
        if not tool:
            logger.warning(f"Tool '{tool_name}' not found in catalog, skipping validation")
            return True, None  # Unknown tool = no validation

        return tool.validate_args(args)

