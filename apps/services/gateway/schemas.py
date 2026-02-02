from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


class Subtask(BaseModel):
    kind: str
    q: Optional[str] = None
    why: Optional[str] = None
    keys: Optional[List[str]] = None
    cmd: Optional[str] = None
    inputs: Optional[Dict[str, Any]] = None
    params: Optional[Dict[str, Any]] = None


class Constraints(BaseModel):
    latency_ms: Optional[int] = None
    budget_tokens: Optional[int] = None
    privacy: Optional[str] = Field(default="allow_external")


class Verification(BaseModel):
    required: List[str] = Field(default_factory=list)


class ReturnSpec(BaseModel):
    format: Literal["raw_bundle"] = "raw_bundle"
    max_items: Optional[int] = None
    notes: Optional[str] = None


class TaskTicket(BaseModel):
    type_: Literal["TICKET"] = Field(alias="_type")
    ticket_id: Optional[str] = None  # Optional: Gateway will inject if missing
    user_turn_id: Optional[str] = None  # Optional: Gateway will inject if missing
    goal: str = Field(..., max_length=200)
    micro_plan: List[str] = Field(default_factory=list)
    subtasks: List[Subtask] = Field(default_factory=list)
    constraints: Constraints = Field(default_factory=Constraints)
    verification: Verification = Field(default_factory=Verification)
    return_spec: ReturnSpec = Field(default_factory=ReturnSpec, alias="return")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("ticket_id", "user_turn_id", mode="before")
    def strip_ws(cls, v: Optional[str]) -> str:
        return (v or "").strip() or "pending"

    @field_validator("goal", mode="before")
    def validate_goal(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="before")
    def ensure_subtasks(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        subtasks = values.get("subtasks") or []
        if not isinstance(subtasks, list):
            raise ValueError("subtasks must be an array")
        return values


class GuideResponse(BaseModel):
    type_: Literal["TICKET", "ANSWER"] = Field(alias="_type")
    analysis: str
    micro_plan: List[str] = Field(default_factory=list)
    needs_more_context: bool = False
    requests: List[TaskTicket] = Field(default_factory=list)
    tool_intent: Optional[Dict[str, Any]] = None
    answer: Optional[str] = None
    cycle: int = 1
    solver_self_history: Optional[List[str]] = None
    suggest_memory_save: Optional[Dict[str, Any]] = None

    @field_validator("analysis", mode="before")
    def ensure_analysis(cls, v: Any) -> str:
        return (v or "").strip()

    @model_validator(mode="after")
    def ensure_answer_for_answer_type(cls, model: "GuideResponse") -> "GuideResponse":
        if model.type_ == "ANSWER":
            answer = model.answer or ""
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("ANSWER responses must include non-empty 'answer'")
        return model


class TraceEntry(BaseModel):
    tool: str
    cost: Optional[Dict[str, Any]] = None


class RawItem(BaseModel):
    type: str
    handle: str
    text: Optional[str] = None
    data: Optional[List[List[Any]]] = None
    source: Optional[str] = None
    freshness: Optional[str] = None
    blob_id: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class Usage(BaseModel):
    tokens: Optional[int] = None
    latency_ms: Optional[int] = None


class RawBundle(BaseModel):
    type_: Literal["BUNDLE"] = Field(alias="_type")
    ticket_id: str
    status: Literal["ok", "partial", "empty", "error"]
    traces: List[TraceEntry] = Field(default_factory=list)
    items: List[RawItem] = Field(default_factory=list)
    notes: Optional[str] = None
    usage: Optional[Usage] = None

    model_config = ConfigDict(populate_by_name=True)


class Claim(BaseModel):
    claim: str
    evidence: List[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    last_verified: Optional[str] = None

    @field_validator("claim", mode="before")
    def strip_claim(cls, v: str) -> str:
        return v.strip()


class Capsule(BaseModel):
    type_: Literal["CAPSULE"] = Field(alias="_type")
    ticket_id: str
    status: Literal["ok", "empty", "conflict", "error"]
    claims: List[Claim] = Field(default_factory=list)
    caveats: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    recommended_answer_shape: Optional[str] = None
    budget_report: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)
