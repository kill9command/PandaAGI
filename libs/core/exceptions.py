"""Custom exceptions for PandaAI v2."""

from typing import Any, Optional


class PandaAIError(Exception):
    """Base exception for PandaAI v2."""

    def __init__(self, message: str, context: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.context = context or {}


class LLMError(PandaAIError):
    """LLM-related errors."""

    pass


class DocumentIOError(PandaAIError):
    """Document IO errors."""

    pass


class PhaseError(PandaAIError):
    """Pipeline phase errors."""

    def __init__(
        self,
        message: str,
        phase: int,
        context: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message, context)
        self.phase = phase


class ToolError(PandaAIError):
    """MCP tool errors."""

    def __init__(
        self,
        message: str,
        tool: str,
        context: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message, context)
        self.tool = tool


class ValidationError(PandaAIError):
    """Validation errors (not Pydantic)."""

    pass


class InterventionRequired(PandaAIError):
    """
    Error requiring human intervention.

    In fail-fast mode, this halts execution and notifies human.
    """

    def __init__(
        self,
        component: str,
        error: str,
        context: Optional[dict[str, Any]] = None,
        severity: str = "HIGH",
    ):
        message = f"[{severity}] Intervention required in {component}: {error}"
        super().__init__(message, context)
        self.component = component
        self.error = error
        self.severity = severity


class BudgetExceededError(PandaAIError):
    """Token budget exceeded."""

    def __init__(
        self,
        phase: int,
        budget: int,
        actual: int,
        context: Optional[dict[str, Any]] = None,
    ):
        message = f"Phase {phase} exceeded token budget: {actual}/{budget}"
        super().__init__(message, context)
        self.phase = phase
        self.budget = budget
        self.actual = actual


class ResearchError(PandaAIError):
    """Research-related errors."""

    pass


class CaptchaDetectedError(PandaAIError):
    """CAPTCHA detected during navigation."""

    def __init__(
        self,
        url: str,
        captcha_type: str,
        context: Optional[dict[str, Any]] = None,
    ):
        message = f"CAPTCHA detected ({captcha_type}) at {url}"
        super().__init__(message, context)
        self.url = url
        self.captcha_type = captcha_type
