"""Pipeline phases for PandaAI v2.

This package implements the 9-phase pipeline:

Phase 0: Query Analyzer - Resolve references, classify query (REFLEX 0.4)
Phase 1: Reflection - Binary PROCEED/CLARIFY gate (REFLEX 0.4)
Phase 2: Context Gatherer - Retrieve relevant context (MIND 0.6)
Phase 3: Planner - Create task plan, route decision (MIND 0.6)
Phase 4: Executor - Tactical execution via natural language commands (MIND 0.6)
         (lives in libs/gateway/orchestration/executor_loop.py)
Phase 5: Coordinator - Tool Expert, translates commands to tool calls (MIND 0.6)
Phase 6: Synthesis - Generate user-facing response (VOICE 0.7)
Phase 7: Validation - Quality gate, APPROVE/REVISE/RETRY (MIND 0.6)
Phase 8: Save - Persist turn data (procedural, no LLM)

Architecture Reference:
    architecture/main-system-patterns/phase*.md

Usage:
    from apps.phases import (
        QueryAnalyzer,
        Reflection,
        ContextGatherer,
        Planner,
        # Phase 4 (Executor) lives in libs/gateway/orchestration/executor_loop.py
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
        # Phase 4 (Executor) lives in libs/gateway/orchestration/executor_loop.py
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
    # Phase 4 (Executor) lives in libs/gateway/orchestration/executor_loop.py
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
    # Constants
    "PHASE_NAMES",
    "PHASE_CLASSES",
]

# Phase number mapping for convenience
# Note: Phase 4 (Executor) lives in libs/gateway/orchestration/executor_loop.py,
# not in apps/phases/. It is intentionally absent from PHASE_CLASSES.
PHASE_CLASSES = {
    0: QueryAnalyzer,
    1: Reflection,
    2: ContextGatherer,
    3: Planner,
    # 4: Executor — lives in libs/gateway/orchestration/executor_loop.py
    5: Coordinator,
    6: Synthesis,
    7: Validation,
    8: Save,
}

# Phase name mapping — single source of truth for the 9-phase pipeline.
# All other modules should import from here:
#   from apps.phases import PHASE_NAMES
PHASE_NAMES = {
    0: "query_analyzer",
    1: "reflection",
    2: "context_gatherer",
    3: "planner",
    4: "executor",
    5: "coordinator",
    6: "synthesis",
    7: "validation",
    8: "save",
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
