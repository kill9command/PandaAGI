"""
Panda Constraints Package - Constraint extraction, enforcement, and validation.

This package implements constraint handling across the pipeline:
1. Extraction: Extract constraints from natural language queries
2. Enforcement: Block tool executions that violate constraints
3. Validation: Verify no constraint violations in final response

Architecture Reference:
    architecture/README.md (Requirement-aware + Validation)

Design Notes:
- The current ConstraintExtractor uses regex patterns for budget/time/size
  constraints. Per architecture guidelines, LLM-driven interpretation of
  requirements is preferred over brittle pattern matching.
- Constraint types are currently fixed (budget, time, file_size). For
  extensibility, consider modeling constraints as workflow-aware schemas.
- The original query in context.md §0 carries all user requirements; each
  phase can interpret requirements naturally without explicit extraction.
- This module may be a legacy path if constraint handling moves to
  LLM-based interpretation within Phase 1 and workflow enforcement.

Contains:
- ConstraintExtractor: Regex-based constraint extraction from queries
- extract_constraints_from_query: Convenience function for extraction
"""

from libs.gateway.constraints.constraint_extractor import (
    ConstraintExtractor,
    get_constraint_extractor,
    extract_constraints_from_query,
)

__all__ = [
    "ConstraintExtractor",
    "get_constraint_extractor",
    "extract_constraints_from_query",
]
