"""
Pandora Phase Utilities - Shared base classes and artifact generation.

Provides shared infrastructure for the 8-phase pipeline:
- BasePhase: Abstract base class with metrics and error handling
- PhaseResult: Standard return type for phase outputs
- ArtifactGenerator: Document artifact generation (docx/xlsx/pdf/pptx)

Architecture Reference:
    architecture/README.md (8-Phase Pipeline)

Active phase implementations live in:
- libs/gateway/orchestration/planning_loop.py (Phase 3 Planner)
- libs/gateway/orchestration/executor_loop.py (Phase 4 Executor)
- libs/gateway/orchestration/agent_loop.py (Phase 5 Coordinator)
- libs/gateway/orchestration/synthesis_phase.py (Phase 6 Synthesis)
- libs/gateway/validation/validation_handler.py (Phase 7 Validation)
- libs/gateway/persistence/turn_saver.py (Phase 8 Save)

Design Notes:
- Phase numbering in code (3-7) maps to the 8-phase pipeline but may use
  different indices for historical reasons
- ArtifactGenerator supports direct calls; for workflow-first patterns,
  artifact creation should be triggered via workflow outputs
- BasePhase provides route_to values for phase transitions; these should
  align with the strategic plan flow from Phase 3
"""

from .base import BasePhase, PhaseResult

__all__ = [
    "BasePhase",
    "PhaseResult",
]
