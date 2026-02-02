from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Import ClaimRow from claims.py to avoid circular dependency
if TYPE_CHECKING:
    from .claims import ClaimRow


class TaskTicket(BaseModel):
    """Guide-issued ticket that the Coordinator executes."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    type_: Literal["TICKET"] = Field(default="TICKET", alias="_type")
    ticket_id: Optional[str] = None
    user_turn_id: Optional[str] = None
    goal: str
    micro_plan: List[str] = Field(default_factory=list)
    subtasks: List[Dict[str, Any]] = Field(default_factory=list)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    verification: Dict[str, Any] = Field(default_factory=dict)
    return_: Dict[str, Any] = Field(default_factory=dict, alias="return")

    @field_validator("ticket_id", "user_turn_id")
    def _require_non_empty(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not str(value).strip():
            raise ValueError("ticket_id and user_turn_id must be non-empty if provided")
        return str(value).strip()


class BundleUsage(BaseModel):
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    latency_ms: Optional[int] = None

    model_config = ConfigDict(extra="forbid")


class RawBundleItem(BaseModel):
    """
    A single element in the Raw Bundle that the Context Manager receives.

    - handle: Stable reference that the Context Manager can cite in `evidence`.
    - kind:   Simple tag (e.g., "doc_excerpt", "memory", "tool_output").
    - summary:Short synopsis for quick filtering.
    - blob_id:Content-addressed handle (blob://<sha>) pointing to the artifact.
    - preview:Short inline preview (<=400 chars) to avoid re-fetching large blobs.
    """

    handle: str
    kind: str
    summary: Optional[str] = None
    blob_id: Optional[str] = None
    preview: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @field_validator("handle", "kind")
    def _no_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("handle/kind cannot be blank")
        return value.strip()

    @field_validator("blob_id")
    def _validate_blob(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if not value.startswith("blob://"):
            raise ValueError("blob_id must use blob:// prefix")
        return value


class RawBundle(BaseModel):
    """Coordinator output after tool execution, pre-context-manager."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type_: Literal["BUNDLE"] = Field(default="BUNDLE", alias="_type")
    ticket_id: str
    status: Literal["ok", "empty", "error", "conflict"] = "ok"
    items: List[RawBundleItem] = Field(default_factory=list)
    notes: Dict[str, Any] = Field(default_factory=dict)
    usage: Optional[BundleUsage] = None

    @field_validator("ticket_id")
    def _ticket_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("ticket_id is required")
        return value.strip()


class CapsuleArtifact(BaseModel):
    label: str
    blob_id: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("blob_id")
    def _validate_blob(cls, value: str) -> str:
        if not value.startswith("blob://"):
            raise ValueError("artifact.blob_id must use blob:// prefix")
        return value


class CapsuleClaim(BaseModel):
    claim: str
    topic: Optional[str] = None
    evidence: List[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    last_verified: Optional[str] = None
    claim_id: Optional[str] = None
    ttl_seconds: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @field_validator("claim")
    def _claim_required(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("claim text cannot be empty")
        return value.strip()

    @field_validator("evidence")
    def _at_least_one_evidence(cls, value: List[str]) -> List[str]:
        if not value:
            raise ValueError("claims must cite at least one evidence handle")
        return value


class DistilledCapsule(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type_: Literal["CAPSULE"] = Field(default="CAPSULE", alias="_type")
    ticket_id: str
    status: Literal["ok", "empty", "conflict", "error"] = "ok"
    claims: List[CapsuleClaim] = Field(default_factory=list)
    caveats: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    artifacts: List[CapsuleArtifact] = Field(default_factory=list)
    recommended_answer_shape: Optional[str] = None
    budget_report: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticket_id")
    def _ticket_required(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("ticket_id is required for capsules")
        return value.strip()


class CapsuleDelta(BaseModel):
    """Returned to the Guide: only the claims/artifacts that are new or updated."""

    base: DistilledCapsule
    claims: List[CapsuleClaim] = Field(default_factory=list)
    artifacts: List[CapsuleArtifact] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class WorkingMemoryState(BaseModel):
    """Represents the capped, ranked state of working memory."""

    max_claims: int = 15
    max_open_questions: int = 5
    max_artifacts: int = 10

    claims: List[CapsuleClaim] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    artifacts: List[CapsuleArtifact] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


@dataclass(slots=True)
class WorkingMemoryConfig:
    max_claims: int = 15
    max_open_questions: int = 5
    max_artifacts: int = 5
    capsule_claim_limit: int = 10
    top_history_claim_ids: int = 4
    default_confidence: str = "medium"
    domain_ttl_days: Dict[str, int] = field(
        default_factory=lambda: {
            "pricing": 5,
            "news": 7,
            "api": 7,
            "spec": 60,
            "law": 120,
        }
    )


@dataclass(slots=True)
class WorkingMemorySnapshot:
    claims: List[ClaimRow]
    claim_ids: List[str]
    fingerprint_map: Dict[str, ClaimRow]


class QualityReport(BaseModel):
    """
    Quality diagnostics for search/retrieval operations with retry logic.
    Used by Context Manager to track verification success and suggest refinements.
    """

    total_fetched: int = 0
    verified: int = 0
    rejected: int = 0
    rejection_breakdown: Dict[str, int] = Field(default_factory=dict)
    quality_score: float = 0.0  # verified / total_fetched
    meets_threshold: bool = True
    suggested_refinement: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("quality_score")
    def _validate_score(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("quality_score must be between 0.0 and 1.0")
        return value


class CapsuleEnvelope(BaseModel):
    """Final payload sent to the Guide, including WM deltas and budget info."""

    ticket_id: str
    status: str
    claims_topk: List[str]
    claim_summaries: Dict[str, str]
    caveats: List[str]
    open_questions: List[str]
    artifacts: List[CapsuleArtifact]
    delta: bool
    budget_report: Dict[str, Any]
    quality_report: Optional[QualityReport] = None  # NEW: for retry logic

    model_config = ConfigDict(extra="forbid")


@dataclass(slots=True)
class CapsuleCompileResult:
    capsule: DistilledCapsule
    delta: CapsuleDelta
    envelope: CapsuleEnvelope
    working_memory: WorkingMemorySnapshot
