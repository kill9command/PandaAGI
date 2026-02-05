"""
Pandora Orchestration Module - Loops that coordinate multiple phases.

Implements the runtime orchestration for the 8-phase pipeline:
- Planning → Executor → Coordinator iteration loops
- Synthesis and validation routing
- Request-level flow control across phases

Architecture Reference:
    architecture/README.md (8-Phase Pipeline)
    architecture/concepts/main-system-patterns/phase3-planner.md
    architecture/concepts/main-system-patterns/phase4-executor.md
    architecture/concepts/main-system-patterns/phase5-coordinator.md

Design Notes:
- "ReflectionPhase" uses legacy naming; current architecture has Phase 1.5
  Query Validator instead of a separate reflection gate
- Phase numbers in loop names reflect code organization, not necessarily
  the 8-phase pipeline numbering
- Executor/Coordinator loops support both workflow-based and direct tool
  execution for backward compatibility; workflow-first is preferred
- Loop boundaries (planning/executor/agent) handle different scopes of
  iteration and should be documented as contracts

Contains:
- AgentLoop: Phase 5 Coordinator agent loop (translates plans to tool calls)
- ExecutorLoop: Phase 4 Executor loop (tactical command execution)
- PlanningLoop: Phase 3-4-5 Planner-Executor-Coordinator iteration loop
- RequestHandler: Full request orchestration (Phases 1-8)
- ReflectionPhase: Legacy Phase 1.5 validation (now Query Validator)
- SynthesisPhase: Phase 6 synthesis and revision
"""

from .agent_loop import AgentLoop, AgentLoopConfig, AgentLoopState, get_agent_loop
from .executor_loop import ExecutorLoop, ExecutorLoopConfig, ExecutorLoopState, get_executor_loop
from .planning_loop import PlanningLoop, PlanningLoopConfig, PlanningLoopState, get_planning_loop
from .request_handler import RequestHandler, RequestHandlerConfig, get_request_handler
from .reflection_phase import ReflectionPhase, get_reflection_phase
from .synthesis_phase import SynthesisPhase, get_synthesis_phase

__all__ = [
    "AgentLoop",
    "AgentLoopConfig",
    "AgentLoopState",
    "get_agent_loop",
    "ExecutorLoop",
    "ExecutorLoopConfig",
    "ExecutorLoopState",
    "get_executor_loop",
    "PlanningLoop",
    "PlanningLoopConfig",
    "PlanningLoopState",
    "get_planning_loop",
    "RequestHandler",
    "RequestHandlerConfig",
    "get_request_handler",
    "ReflectionPhase",
    "get_reflection_phase",
    "SynthesisPhase",
    "get_synthesis_phase",
]
