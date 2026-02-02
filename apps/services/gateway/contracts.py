"""
Component contracts for Pandora Gateway.

Defines explicit interfaces between components using Pydantic models.
Each component MUST conform to its contract, or the ContractEnforcer
will attempt to repair the response.

This prevents cascading failures when one component changes its output format.
"""

from pydantic import BaseModel, Field, validator, field_validator, model_validator
from typing import Optional, List, Dict, Any, Literal, Union
from enum import Enum
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# Guide Contract: What Guide MUST return
# ============================================================================

class GuideRequestType(str, Enum):
    """Types of requests Guide can make"""
    DELEGATE = "delegate"  # Needs Coordinator to plan tools
    ANSWER_DIRECTLY = "answer_directly"  # Can answer without tools
    NEED_MORE_INFO = "need_more_info"  # Needs clarification from user


class GuideRequest(BaseModel):
    """What Guide asks for when it needs help"""
    type: GuideRequestType
    goal: str = Field(..., min_length=1, max_length=500)
    context_needed: List[str] = Field(default_factory=list)
    urgency: Literal["low", "medium", "high"] = "medium"

    class Config:
        use_enum_values = True


class GuideResponse(BaseModel):
    """What Guide returns to user (final answer)"""
    answer: str = Field(..., min_length=1, description="The response text to show the user")
    confidence: float = Field(ge=0.0, le=1.0, default=0.8, description="Guide's confidence in this answer")
    sources: List[str] = Field(default_factory=list, description="Source citations if applicable")
    needs_more_context: bool = Field(default=False, description="Whether Guide needs another cycle")

    @validator('answer')
    def answer_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Answer cannot be empty")
        return v.strip()


# ============================================================================
# Coordinator Contract: What Coordinator MUST return
# ============================================================================

class ToolCall(BaseModel):
    """Single tool invocation"""
    tool: str = Field(..., min_length=1, description="Tool name from catalog")
    args: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    required: bool = Field(default=True, description="Can system skip if this tool fails?")

    @validator('tool')
    def tool_format(cls, v):
        # Basic validation: tool name should be lowercase with optional dots
        if not v or not v.strip():
            raise ValueError("Tool name cannot be empty")
        return v.strip()


class CoordinatorReflection(BaseModel):
    """Coordinator's internal reflection"""
    task_understanding: str = Field(default="", max_length=300)
    tool_selection_reasoning: str = Field(default="", max_length=300)
    expected_challenges: List[str] = Field(default_factory=list, max_items=5)
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)


class CoordinatorPlan(BaseModel):
    """Validated plan from Coordinator"""
    plan: List[ToolCall] = Field(default_factory=list, max_items=15, description="Ordered list of tool calls")
    reflection: Optional[CoordinatorReflection] = None
    notes: Dict[str, Any] = Field(default_factory=dict, description="Additional context for Guide")
    estimated_tokens: int = Field(ge=0, le=10000, default=0, description="Estimated token usage")

    @validator('plan')
    def plan_reasonable(cls, v):
        if len(v) > 15:
            logger.warning(f"Plan has {len(v)} tools, truncating to 15")
            return v[:15]
        return v


class CoordinatorResponse(BaseModel):
    """What Coordinator returns to Gateway"""
    reflection: Optional[Union[str, CoordinatorReflection]] = Field(default="")  # Accept both string and dict
    plan: List[ToolCall] = Field(default_factory=list)
    notes: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)

    @model_validator(mode='after')
    def ensure_plan_or_error(self):
        if not self.plan and not self.notes.get('error'):
            # Empty plan without error note is suspicious
            logger.warning("Coordinator returned empty plan without error note")
            if not self.notes:
                self.notes = {}
            self.notes['warning'] = 'empty_plan'
        return self


# ============================================================================
# Tool Output Contract: What tools MUST return
# ============================================================================

class ToolOutput(BaseModel):
    """Standardized tool response"""
    success: bool = Field(..., description="Whether tool executed successfully")
    data: Any = Field(default=None, description="Tool result data")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    tokens_used: int = Field(ge=0, default=0, description="Tokens consumed by this tool")

    @model_validator(mode='after')
    def validate_success_error_consistency(self):
        if not self.success and not self.error:
            # Failed but no error message
            self.error = 'Unknown error (tool failed without message)'

        if self.success and self.error:
            # Success but has error message (inconsistent)
            logger.warning(f"Tool marked success=True but has error: {self.error}")
            self.success = False

        return self


# ============================================================================
# Context Manager Contract: What Context Manager MUST return
# ============================================================================

class Claim(BaseModel):
    """Single claim with evidence"""
    text: str = Field(..., min_length=1, max_length=500, description="The claim text")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in this claim")
    evidence: List[str] = Field(default_factory=list, max_items=10, description="Supporting evidence")
    domain: str = Field(default="general", description="Domain categorization")
    topics: List[str] = Field(default_factory=list, max_items=10, description="Relevant topics")
    ttl_seconds: int = Field(ge=0, default=3600, description="Time-to-live for this claim")

    @validator('text')
    def text_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Claim text cannot be empty")
        return v.strip()


class CapsuleStatus(str, Enum):
    """Status of capsule generation"""
    OK = "ok"
    EMPTY = "empty"
    ERROR = "error"
    PARTIAL = "partial"


class CapsuleEnvelope(BaseModel):
    """Validated capsule from Context Manager"""
    claims: List[Claim] = Field(default_factory=list, max_items=100)
    summary: str = Field(default="", max_length=2000, description="Human-readable summary")
    status: CapsuleStatus = "ok"
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        use_enum_values = True

    @validator('claims')
    def claims_reasonable(cls, v):
        if len(v) > 100:
            logger.warning(f"Capsule has {len(v)} claims, truncating to 100")
            return v[:100]
        return v

    @model_validator(mode='after')
    def validate_status_consistency(self):
        # Auto-correct inconsistent status
        if not self.claims and self.status == 'ok':
            self.status = 'empty'
        elif self.claims and self.status == 'empty':
            self.status = 'ok'

        return self


# ============================================================================
# Token Budget Contract
# ============================================================================

class TokenBudget(BaseModel):
    """Token budget allocation for a request"""
    total: int = Field(ge=1000, le=50000, default=12000)
    system_prompt: int = Field(ge=0, default=1200)
    user_query: int = Field(ge=0, default=1500)
    guide_response: int = Field(ge=0, default=800)
    coordinator_plan: int = Field(ge=0, default=1024)
    tool_outputs: int = Field(ge=0, default=2000)
    capsule: int = Field(ge=0, default=1500)
    context: int = Field(ge=0, default=3000)
    buffer: int = Field(ge=0, default=976)

    @model_validator(mode='after')
    def budget_adds_up(self):
        allocated = sum([
            self.system_prompt, self.user_query, self.guide_response, self.coordinator_plan,
            self.tool_outputs, self.capsule, self.context, self.buffer
        ])

        if allocated > self.total:
            logger.warning(f"Budget overallocated: {allocated} > {self.total}, scaling down")
            scale = self.total / allocated
            self.system_prompt = int(self.system_prompt * scale)
            self.user_query = int(self.user_query * scale)
            self.guide_response = int(self.guide_response * scale)
            self.coordinator_plan = int(self.coordinator_plan * scale)
            self.tool_outputs = int(self.tool_outputs * scale)
            self.capsule = int(self.capsule * scale)
            self.context = int(self.context * scale)
            self.buffer = int(self.buffer * scale)

        return self


# ============================================================================
# Decision Contract (for LLM-driven decisions)
# ============================================================================

class DecisionType(str, Enum):
    """Types of strategic decisions"""
    CACHE_STRATEGY = "cache_strategy"
    TOOL_SELECTION = "tool_selection"
    QUALITY_ASSESSMENT = "quality_assessment"
    RETRY_STRATEGY = "retry_strategy"


class Decision(BaseModel):
    """Record of an LLM-driven decision"""
    type: DecisionType
    choice: str = Field(..., min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(default="", max_length=500)
    alternatives: List[str] = Field(default_factory=list, max_items=5)
    timestamp: float = Field(...)

    class Config:
        use_enum_values = True


# ============================================================================
# Health Check Contract
# ============================================================================

class ComponentHealth(BaseModel):
    """Health status of a component"""
    component: str
    status: Literal["healthy", "degraded", "failed"]
    last_success: Optional[float] = None
    failure_count: int = Field(ge=0, default=0)
    error_message: Optional[str] = None


class SystemHealth(BaseModel):
    """Overall system health"""
    status: Literal["healthy", "degraded", "failed"]
    components: List[ComponentHealth]
    timestamp: float

    @validator('status')
    def determine_overall_status(cls, v, values):
        components = values.get('components', [])
        if not components:
            return 'failed'

        statuses = [c.status for c in components]
        if all(s == 'healthy' for s in statuses):
            return 'healthy'
        elif any(s == 'failed' for s in statuses):
            return 'degraded'
        else:
            return 'degraded'
