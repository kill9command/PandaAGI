"""
Panda Gateway Archive - Legacy modules preserved for reference.

WARNING: This code is archived and should NOT be used in production.

These modules represent pre-workflow logic and heuristic routing that has been
superseded by the current architecture. They are preserved for historical reference
and debugging purposes.

Architecture Reference:
    architecture/README.md (Workflow System + Context Discipline)

Design Notes:
- Intent classification and tool routing have been replaced by workflow-first routing
- Context scoring and assembly are now handled by Phase 2.1/2.2 gatherers
- Plan linting heuristics conflict with LLM-driven validation in Phase 7
- Do not import these modules in active code paths

If you find yourself importing from this module, consider:
1. Is there a workflow-based solution in libs/gateway/execution/?
2. Is this logic covered by Phase 1 query analysis or Phase 7 validation?
3. Should this be an LLM-driven decision rather than hardcoded rules?

Contents (DO NOT USE):
- context_scorer.py: Legacy relevance scoring
- intent_classifier.py: Pre-LLM intent classification
- intent_weights.py: Hardcoded intent scoring weights
- plan_linter.py: Rule-based plan validation (replaced by Phase 7)
- tool_router.py: Direct tool routing (replaced by workflows)
- unified_context.py: Legacy context assembly (replaced by Phase 2)
"""

import warnings

warnings.warn(
    "apps.services.gateway.archive is deprecated legacy code. "
    "Do not import in production. See architecture/README.md for current patterns.",
    DeprecationWarning,
    stacklevel=2
)
