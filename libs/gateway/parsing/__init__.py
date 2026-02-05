"""
Pandora Parsing Module - Response parsing and claims extraction.

Provides parsing and extraction utilities for LLM outputs:
- JSON repair and defensive parsing of LLM responses
- Decision parsing for planner/executor/coordinator outputs
- Claim extraction from tool results with provenance
- Reference resolution helpers

Architecture Reference:
    architecture/README.md (Proof-Carrying Outputs)

Design Notes:
- ClaimsManager includes tool-specific extraction logic; this could be
  refactored to workflow-embedded claim semantics if workflows become
  the sole execution path
- Decision parsers support both legacy direct-tool-selection schemas
  and newer workflow/strategic-plan outputs
- QueryResolver functionality overlaps with Phase 1 reference resolution;
  kept for backward compatibility with pre-Phase-1 integration patterns
- ForgivingParser is essential safety net for malformed JSON output

Contains:
- ResponseParser: LLM response parsing with JSON repair
- ClaimsManager: Claims extraction with TTL and confidence
- ForgivingParser: Defensive JSON parsing utilities
- QueryResolver: Reference resolution helpers (legacy)
"""

from libs.gateway.parsing.response_parser import (
    ResponseParser,
    get_response_parser,
    parse_json_response,
    parse_planner_decision,
    parse_executor_decision,
    parse_tool_selection,
    parse_agent_decision,
)
from libs.gateway.parsing.claims_manager import ClaimsManager, get_claims_manager
from libs.gateway.parsing.forgiving_parser import (
    ForgivingParser,
    ParseResult,
)
from libs.gateway.parsing.query_resolver import QueryResolver, get_query_resolver

__all__ = [
    "ResponseParser",
    "get_response_parser",
    "parse_json_response",
    "parse_planner_decision",
    "parse_executor_decision",
    "parse_tool_selection",
    "parse_agent_decision",
    "ClaimsManager",
    "get_claims_manager",
    "ForgivingParser",
    "ParseResult",
    "QueryResolver",
    "get_query_resolver",
]
