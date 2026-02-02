"""Pipeline phases for PandaAI v2.

This package implements the 8-phase pipeline:

Phase 0: Query Analyzer - Resolve references, classify query (REFLEX role)
Phase 1: Reflection - Binary PROCEED/CLARIFY gate (REFLEX role)
Phase 2: Context Gatherer - Retrieve relevant context (MIND role)
Phase 3: Planner - Create task plan, route decision (MIND role)
Phase 4: Coordinator - Execute tools via Orchestrator (MIND role)
Phase 5: Synthesis - Generate user-facing response (VOICE role)
Phase 6: Validation - Quality gate, APPROVE/REVISE/RETRY (MIND role)
Phase 7: Save - Persist turn data (procedural, no LLM)

Architecture Reference:
    architecture/Implementation/05-PIPELINE-PHASES.md
    architecture/main-system-patterns/phase*.md

Usage:
    from apps.phases import (
        QueryAnalyzer,
        Reflection,
        ContextGatherer,
        Planner,
        Coordinator,
        Synthesis,
        Validation,
        Save,
    )

    # Or use factory functions
    from apps.phases import (
        create_query_analyzer,
        create_reflection,
        create_context_gatherer,
        create_planner,
        create_coordinator,
        create_synthesis,
        create_validation,
        create_save,
    )
"""

# Base class
from apps.phases.base_phase import BasePhase

# Phase implementations
from apps.phases.phase0_query_analyzer import QueryAnalyzer, create_query_analyzer
from apps.phases.phase1_reflection import Reflection, create_reflection
from apps.phases.phase2_context_gatherer import ContextGatherer, create_context_gatherer
from apps.phases.phase3_planner import Planner, create_planner
from apps.phases.phase4_coordinator import Coordinator, create_coordinator
from apps.phases.phase5_synthesis import Synthesis, create_synthesis
from apps.phases.phase6_validation import Validation, create_validation
from apps.phases.phase7_save import Save, create_save

__all__ = [
    # Base class
    "BasePhase",
    # Phase classes
    "QueryAnalyzer",
    "Reflection",
    "ContextGatherer",
    "Planner",
    "Coordinator",
    "Synthesis",
    "Validation",
    "Save",
    # Factory functions
    "create_query_analyzer",
    "create_reflection",
    "create_context_gatherer",
    "create_planner",
    "create_coordinator",
    "create_synthesis",
    "create_validation",
    "create_save",
]

# Phase number mapping for convenience
PHASE_CLASSES = {
    0: QueryAnalyzer,
    1: Reflection,
    2: ContextGatherer,
    3: Planner,
    4: Coordinator,
    5: Synthesis,
    6: Validation,
    7: Save,
}

# Phase name mapping
PHASE_NAMES = {
    0: "query_analyzer",
    1: "reflection",
    2: "context_gatherer",
    3: "planner",
    4: "coordinator",
    5: "synthesis",
    6: "validation",
    7: "save",
}


def get_phase_class(phase_number: int):
    """Get the phase class for a given phase number."""
    if phase_number not in PHASE_CLASSES:
        raise ValueError(f"Invalid phase number: {phase_number}")
    return PHASE_CLASSES[phase_number]


def get_phase_name(phase_number: int) -> str:
    """Get the phase name for a given phase number."""
    if phase_number not in PHASE_NAMES:
        raise ValueError(f"Invalid phase number: {phase_number}")
    return PHASE_NAMES[phase_number]
