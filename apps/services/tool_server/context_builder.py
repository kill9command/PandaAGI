from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, TYPE_CHECKING

from apps.services.tool_server.shared_state import (
    ArtifactStore,
    CapsuleArtifact,
    CapsuleClaim,
    CapsuleDelta,
    ClaimRegistry,
    ClaimRow,
    DistilledCapsule,
    FreshnessOracle,
    QualityReport,
    RawBundle,
    RawBundleItem,
)
from apps.services.tool_server.shared_state.schema import TaskTicket
from apps.services.tool_server.claim_quality import ClaimQualityScorer

# PHASE 5: TYPE_CHECKING import to avoid circular dependency
if TYPE_CHECKING:
    from apps.services.gateway.session_context import LiveSessionContext


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
            "pricing": 1,  # Reduced from 5 to 1 day - prices change frequently
            "commerce": 1,  # Commerce claims (products, offers) expire quickly
            "news": 7,
            "research": 3,  # Reduced from 7 to 3 days - research results can get stale
            "api": 7,
            "spec": 60,
            "law": 120,
        }
    )


@dataclass(slots=True)
class Candidate:
    text: str
    evidence: List[str]
    source_tool: str
    confidence: str
    domain: Optional[str]
    topics: List[str]
    artifact: Optional[CapsuleArtifact]
    metadata: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    fingerprint: Optional[str] = None
    ttl_seconds: Optional[int] = None


@dataclass(slots=True)
class WorkingMemorySnapshot:
    claims: List[ClaimRow]
    claim_ids: List[str]
    fingerprint_map: Dict[str, ClaimRow]


@dataclass(slots=True)
class CapsuleEnvelope:
    ticket_id: str
    status: str
    claims_topk: List[str]
    claim_summaries: Dict[str, str]
    caveats: List[str]
    open_questions: List[str]
    artifacts: List[CapsuleArtifact]
    delta: bool
    budget_report: Dict[str, Any]
    quality_report: Optional[QualityReport] = None  # NEW: for thinking loops retry logic
    # PHASE 6: Context compression fields
    compressed_context: Optional[str] = None
    context_tokens_saved: int = 0
    context_compression_applied: bool = False
    # Code Mode Phase 2: Outline caching
    outline_cache: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def cache_outline(self, file_path: str, outline_result: Dict[str, Any]) -> None:
        """Cache file outline for reuse (TTL: 1 hour)."""
        self.outline_cache[file_path] = {
            **outline_result,
            "timestamp": time.time(),
            "ttl_seconds": 3600
        }

    def get_cached_outline(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached outline if fresh."""
        cached = self.outline_cache.get(file_path)
        if cached:
            age = time.time() - cached["timestamp"]
            if age < cached["ttl_seconds"]:
                # Return without timestamp and ttl_seconds
                result = {k: v for k, v in cached.items() if k not in ("timestamp", "ttl_seconds")}
                return result
        return None


@dataclass(slots=True)
class CapsuleCompileResult:
    capsule: DistilledCapsule
    delta: CapsuleDelta
    envelope: CapsuleEnvelope
    working_memory: WorkingMemorySnapshot


logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[A-Za-z0-9_\-]+")
_NUMERIC_RE = re.compile(r"\d+")
_CURRENCY_RE = re.compile(r"\$\d|\d+\s?(USD|EUR|GBP|CAD|AUD|JPY)")
_OFFER_SKIP_KEYWORDS = (
    "book",
    "guide",
    "manual",
    "poster",
    "print",
    "plush",
    "toy",
    "video",
    "dvd",
    "shirt",
    "set",
    "figurine",
    "calendar",
    "sticker",
    "vitalsource",
    "barnes",
    "ebook",
    "walmart",
)


async def evaluate_claim_with_llm(
    claim: ClaimRow,
    session_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Phase 3: Let LLM decide: keep, archive, or delete this claim?

    Returns:
    {
        "decision": "keep_active|archive_cold|delete",
        "quality_score": 0-100,
        "confidence": 0.0-1.0,
        "reasoning": "..."
    }
    """
    try:
        import httpx
    except ImportError:
        logger.warning("httpx not available, using fallback heuristics for claim evaluation")
        # Fallback: Simple heuristics
        days_old = session_context.get("days_since_created", 0)
        if days_old > 7:
            return {
                "decision": "archive_cold",
                "quality_score": 40,
                "confidence": 0.5,
                "reasoning": "Fallback: older than 7 days"
            }
        else:
            return {
                "decision": "keep_active",
                "quality_score": 60,
                "confidence": 0.6,
                "reasoning": "Fallback: recent claim"
            }

    solver_url = os.getenv("SOLVER_URL", "http://localhost:8000/v1/chat/completions")
    solver_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

    # Extract claim metadata
    metadata = claim.metadata if isinstance(claim.metadata, dict) else {}
    domain = metadata.get("domain", "unknown")

    # Calculate days since created
    days_since_created = 0
    try:
        created_dt = datetime.fromisoformat(claim.created_at.replace('Z', '+00:00'))
        now_dt = datetime.now(timezone.utc)
        days_since_created = (now_dt - created_dt).days
    except Exception:
        pass

    # Load CLAIM_EVALUATION prompt from context_manager.md
    prompt_text = _load_claim_evaluation_prompt()
    prompt = f"""{prompt_text}

## Claim to Evaluate:

Claim ID: {claim.claim_id}
Claim Text: {claim.statement}
Evidence: {claim.evidence}
Current Confidence: {claim.confidence}
Domain: {domain}
Days Old: {days_since_created}

## Session Context:

- Recent Queries: {session_context.get("recent_queries", [])}
- Active Topics: {session_context.get("active_topics", [])}

Output your evaluation as JSON only:
{{
  "_type": "CLAIM_EVALUATION",
  "claim_id": "{claim.claim_id}",
  "claim_text": "{claim.statement[:100]}...",
  "quality_score": 0-100,
  "decision": "keep_active|archive_cold|delete",
  "confidence": 0.0-1.0,
  "reasoning": "..."
}}"""

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                solver_url,
                headers={
                    "Authorization": f"Bearer {solver_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": os.getenv("SOLVER_MODEL_ID", "qwen3-coder"),
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 200
                }
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]

            # Parse JSON from response
            decision_data = _extract_json_from_text(content)
            if not decision_data:
                raise ValueError("No JSON in LLM response")

            return decision_data

    except Exception as e:
        logger.warning(f"LLM claim evaluation failed: {e}, using fallback heuristics")
        # Fallback: Simple heuristics
        if days_since_created > 7:
            return {
                "decision": "archive_cold",
                "quality_score": 40,
                "confidence": 0.5,
                "reasoning": f"Fallback: older than 7 days ({e})"
            }
        else:
            return {
                "decision": "keep_active",
                "quality_score": 60,
                "confidence": 0.6,
                "reasoning": f"Fallback: recent claim ({e})"
            }


def _load_claim_evaluation_prompt() -> str:
    """Load claim evaluation prompt from recipe system."""
    try:
        from libs.gateway.llm.recipe_loader import load_recipe
        recipe = load_recipe("tools/claim_evaluator")
        prompt = recipe.get_prompt()
        logger.info("[ClaimEvaluator] Loaded prompt from recipe system")
        return prompt
    except Exception as e:
        logger.warning(f"[ClaimEvaluator] Recipe load failed: {e}, using fallback")
        return _get_fallback_claim_evaluation_prompt()


def _get_fallback_claim_evaluation_prompt() -> str:
    """Fallback prompt if recipe can't be loaded"""
    return """## Claim Lifecycle Evaluation

Evaluate this memory claim for quality and relevance.

Based on quality, relevance, and freshness, decide:
- keep_active: Still relevant, high quality, user needs it now (score >=60)
- archive_cold: Potentially useful later, not currently needed (score 40-60)
- delete: Obsolete, low quality, or superseded (score < 40)

Quality Scoring Factors:
- Source credibility (verified > unverified) - 30%
- Evidence strength (multiple sources > single) - 25%
- Recency (fresh > stale) - 20%
- Relevance to current session - 25%"""


def _extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON object from text that may contain markdown code blocks."""
    # Try to find JSON in code blocks first
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find raw JSON
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _detect_result_type_from_candidate(cand: Candidate) -> str:
    """Detect result type from candidate metadata and content."""
    # Check domain first
    if cand.domain == "commerce" or cand.domain == "pricing":
        return "shopping_listings"
    if cand.domain == "research":
        return "care_guides"
    if cand.domain == "navigation":
        return "navigation"

    # Check source tool
    if "commerce" in cand.source_tool.lower() or "purchasing" in cand.source_tool.lower():
        return "shopping_listings"
    if "doc.search" in cand.source_tool.lower() or "web.fetch" in cand.source_tool.lower():
        # Check content to distinguish care guides from specs
        text_lower = cand.text.lower()
        if any(word in text_lower for word in ["housing", "diet", "behavior", "care", "health", "requirements"]):
            return "care_guides"
        if any(word in text_lower for word in ["dimensions", "features", "specs", "specifications"]):
            return "product_specs"
        return "general_info"
    if "file." in cand.source_tool.lower() or "git." in cand.source_tool.lower():
        return "code_output"

    # Default
    return "unknown"


async def compile_capsule(
    session_id: str,
    ticket: TaskTicket,
    raw_bundle: RawBundle,
    *,
    claim_registry: ClaimRegistry,
    artifact_store: ArtifactStore,
    freshness: Optional[FreshnessOracle] = None,
    now: Optional[datetime] = None,
    config: Optional[WorkingMemoryConfig] = None,
    tool_records: Optional[Sequence[Dict[str, Any]]] = None,
    excluded_domains: Optional[List[str]] = None,
    intent_type: Optional[str] = None,
    session_context: Optional[Dict[str, Any]] = None,
    live_context: Optional['LiveSessionContext'] = None,  # PHASE 5: NEW parameter
) -> CapsuleCompileResult:
    """
    Reduce a RawBundle into a distilled capsule and working-memory snapshot.

    PHASE 5+6: Now accepts live_context for context compression.
    Context Manager compresses session context WITHOUT mutating live_context.
    """
    config = config or WorkingMemoryConfig()
    freshness = freshness or claim_registry.freshness
    now_dt = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    quality_scorer = ClaimQualityScorer()  # Initialize quality scorer

    existing_claims = list(claim_registry.list_active_claims(session_id=session_id))
    existing_fingerprints = {row.fingerprint for row in existing_claims}

    candidates = list(
        _extract_candidates(
            raw_bundle,
            tool_records=tool_records or [],
            artifact_store=artifact_store,
        )
    )

    if not candidates:
        empty_capsule = DistilledCapsule(
            ticket_id=ticket.ticket_id,
            status="empty",
            claims=[],
            caveats=[],
            open_questions=[],
            artifacts=[],
            recommended_answer_shape=None,
            budget_report={"raw_tokens": 0, "reduced_tokens": 0},
        )
        delta = claim_registry.record_capsule(
            session_id=session_id,
            turn_id=ticket.user_turn_id,
            ticket_id=ticket.ticket_id,
            capsule=empty_capsule,
        )
        snapshot = await update_working_memory(
            claim_registry,
            session_id=session_id,
            config=config,
            excluded_domains=excluded_domains,
            session_context=session_context
        )
        # Compute quality report even for empty capsules (to catch zero-result cases)
        quality_report = _compute_quality_report(tool_records or [])
        
        envelope = CapsuleEnvelope(
            ticket_id=empty_capsule.ticket_id,
            status=empty_capsule.status,
            claims_topk=[],
            claim_summaries={},
            caveats=[],
            open_questions=[],
            artifacts=[],
            delta=False,
            budget_report=empty_capsule.budget_report,
            quality_report=quality_report,
        )
        return CapsuleCompileResult(
            capsule=delta.base,
            delta=delta,
            envelope=envelope,
            working_memory=snapshot,
        )

    scored_candidates = _score_candidates(
        candidates,
        ticket=ticket,
        config=config,
        existing_fingerprints=existing_fingerprints,
        freshness=freshness,
        now=now_dt,
    )

    scored_candidates.sort(key=lambda cand: cand.score, reverse=True)
    top_candidates = scored_candidates[: config.capsule_claim_limit]

    capsule_claims: List[CapsuleClaim] = []
    capsule_artifacts: List[CapsuleArtifact] = []
    claim_summaries: Dict[str, str] = {}

    for cand in top_candidates:
        ttl_seconds = cand.ttl_seconds or _ttl_for_candidate(cand, freshness, config)
        metadata = dict(cand.metadata)
        metadata.update(
            {
                "score": round(cand.score, 3),
                "source_tool": cand.source_tool,
                "domain": cand.domain,
                "topics": cand.topics,
            }
        )
        # Store intent type for cache isolation
        if intent_type:
            metadata["matched_intent"] = intent_type

        # QUALITY TRACKING: Score claim quality based on intent alignment
        result_type = _detect_result_type_from_candidate(cand)
        tool_status = "success"  # We assume success if we got candidates

        # Estimate data quality from candidate score and confidence
        data_quality = {
            "structured": 0.8 if cand.confidence in ["high", "verified"] else 0.5,
            "completeness": min(cand.score, 1.0),  # Use candidate score as completeness proxy
            "source_confidence": 0.8 if cand.confidence in ["high", "verified"] else 0.6,
        }

        # Calculate claim specificity based on text length and detail
        claim_text_len = len(cand.text)
        claim_specificity = min(claim_text_len / 200.0, 1.0)  # Longer claims more specific (up to 200 chars)

        # Score the claim
        claim_quality = quality_scorer.score_claim(
            query_intent=intent_type or "informational",
            result_type=result_type,
            tool_status=tool_status,
            tool_metadata={"data_quality": data_quality},
            claim_specificity=claim_specificity,
            source_count=len(cand.evidence) if cand.evidence else 1,
        )

        # Calculate quality-based TTL
        ttl_hours = quality_scorer.calculate_claim_ttl(claim_quality["overall_score"])
        ttl_seconds = ttl_hours * 3600

        # Add quality metrics to metadata
        metadata.update({
            "result_type": result_type,
            "intent_alignment": claim_quality["intent_alignment"],
            "evidence_strength": claim_quality["evidence_strength"],
            "quality_score": claim_quality["overall_score"],
        })

        claim_obj = CapsuleClaim(
            claim=cand.text.strip(),
            evidence=list(cand.evidence),
            confidence=cand.confidence,
            last_verified=now_dt.isoformat(),
            ttl_seconds=ttl_seconds,
            metadata=metadata,
        )
        cand.fingerprint = ClaimRegistry.fingerprint(claim_obj)
        capsule_claims.append(claim_obj)
        if cand.artifact and cand.artifact.blob_id:
            capsule_artifacts.append(cand.artifact)

    capsule_artifacts = capsule_artifacts[: config.max_artifacts]

    budget_report = _estimate_budget(raw_bundle, capsule_claims, capsule_artifacts)
    distilled_capsule = DistilledCapsule(
        ticket_id=ticket.ticket_id,
        status="ok" if capsule_claims else "empty",
        claims=capsule_claims,
        caveats=[],
        open_questions=[],
        artifacts=capsule_artifacts,
        recommended_answer_shape="bullets",
        budget_report=budget_report,
    )

    delta = claim_registry.record_capsule(
        session_id=session_id,
        turn_id=ticket.user_turn_id,
        ticket_id=ticket.ticket_id,
        capsule=distilled_capsule,
    )
    normalized_capsule = delta.base
    for claim in normalized_capsule.claims or []:
        if claim.claim_id:
            claim_summaries[claim.claim_id] = _format_claim_summary(claim)

    snapshot = await update_working_memory(
        claim_registry,
        session_id=session_id,
        config=config,
        excluded_domains=excluded_domains,
        session_context=session_context
    )

    claims_topk = [
        claim.claim_id for claim in normalized_capsule.claims or [] if claim.claim_id
    ][: config.capsule_claim_limit]
    
    # Compute quality report for commerce/pricing operations
    quality_report = _compute_quality_report(tool_records or [])
    
    envelope = CapsuleEnvelope(
        ticket_id=normalized_capsule.ticket_id,
        status=normalized_capsule.status,
        claims_topk=claims_topk,
        claim_summaries={cid: claim_summaries[cid] for cid in claims_topk if cid in claim_summaries},
        caveats=list(normalized_capsule.caveats or [])[: config.max_open_questions],
        open_questions=list(normalized_capsule.open_questions or [])[: config.max_open_questions],
        artifacts=list(normalized_capsule.artifacts or [])[: config.max_artifacts],
        delta=bool(delta.claims or delta.artifacts),
        budget_report=normalized_capsule.budget_report,
        quality_report=quality_report,  # NEW: for thinking loops retry logic
    )

    # PHASE 6: Context compression (read-only, does NOT mutate live_context)
    # ========================================================================
    if live_context and live_context.turn_count > 0:
        try:
            # Build compressed context (READ-ONLY operation - no mutation!)
            compressed_ctx = live_context.to_context_block(max_tokens=200)

            if not compressed_ctx or len(compressed_ctx.strip()) == 0:
                logger.warning("[ContextManager] Context compression produced empty result")
                envelope.compressed_context = None
                envelope.context_compression_applied = False
            else:
                # Estimate tokens saved (use conservative baseline estimate)
                compressed_estimate = len(compressed_ctx) // 4  # 1 token ≈ 4 chars
                original_estimate = 450  # Conservative estimate of pre-compression context

                if compressed_estimate > 200:
                    logger.warning(
                        f"[ContextManager] Compressed context exceeds budget: {compressed_estimate} > 200 tokens"
                    )
                    # Quality Agent recommendation: Use word-boundary truncation instead of hard slice
                    max_chars = 200 * 4  # 800 chars
                    if len(compressed_ctx) > max_chars:
                        # Try to truncate at sentence boundary
                        truncated = compressed_ctx[:max_chars]
                        last_sentence = max(truncated.rfind('.'), truncated.rfind('!'), truncated.rfind('?'))
                        if last_sentence > max_chars * 0.6:
                            compressed_ctx = compressed_ctx[:last_sentence+1]
                        else:
                            # Fall back to word boundary
                            last_space = truncated.rfind(' ')
                            if last_space > max_chars * 0.8:
                                compressed_ctx = compressed_ctx[:last_space] + "..."
                            else:
                                # Hard truncate but add ellipsis
                                compressed_ctx = compressed_ctx[:max_chars-3] + "..."
                    compressed_estimate = len(compressed_ctx) // 4  # Recalculate after truncation

                tokens_saved = max(0, original_estimate - compressed_estimate)

                envelope.compressed_context = compressed_ctx
                envelope.context_tokens_saved = tokens_saved
                envelope.context_compression_applied = True

                logger.info(
                    f"[ContextManager] Context compressed: {original_estimate} → {compressed_estimate} tokens "
                    f"(saved {tokens_saved}, {tokens_saved/original_estimate*100:.0f}%)"
                )
        except Exception as e:
            logger.error(f"[ContextManager] Context compression failed: {e}", exc_info=True)
            envelope.compressed_context = None
            envelope.context_compression_applied = False
            # Non-fatal - continue without compressed context
    elif live_context is None:
        logger.debug("[ContextManager] No live_context provided, skipping compression")
    else:
        logger.debug(f"[ContextManager] Fresh session (turn_count={live_context.turn_count}), skipping compression")

    return CapsuleCompileResult(
        capsule=normalized_capsule,
        delta=delta,
        envelope=envelope,
        working_memory=snapshot,
    )


async def update_working_memory(
    claim_registry: ClaimRegistry,
    *,
    session_id: str,
    config: Optional[WorkingMemoryConfig] = None,
    excluded_domains: Optional[Sequence[str]] = None,
    check_expiry: bool = True,
    use_llm_evaluation: bool = False,
    session_context: Optional[Dict[str, Any]] = None,
) -> WorkingMemorySnapshot:
    """Enforce working-memory caps and return the current snapshot.

    Args:
        claim_registry: The claim registry to query
        session_id: Session identifier
        config: Working memory configuration
        excluded_domains: Optional list of domains to exclude (e.g., ['pricing', 'commerce'])
        check_expiry: If True, filter out expired claims (default: True)
        use_llm_evaluation: If True, use LLM to evaluate claims (Phase 3) (default: False)
        session_context: Context for LLM evaluation (recent queries, topics)
    """
    config = config or WorkingMemoryConfig()
    claims = list(claim_registry.list_active_claims(session_id=session_id))

    # Filter by expiry if requested
    if check_expiry:
        now = datetime.now(timezone.utc)
        valid_claims = []
        expired_ids = []
        for claim in claims:
            try:
                expires_dt = datetime.fromisoformat(claim.expires_at.replace('Z', '+00:00'))
                if expires_dt > now:
                    valid_claims.append(claim)
                else:
                    expired_ids.append(claim.claim_id)
            except Exception:
                # If we can't parse expiry, keep the claim
                valid_claims.append(claim)

        # Delete expired claims
        if expired_ids:
            claim_registry.delete_claims(expired_ids)

        claims = valid_claims

    # Filter by domain if excluded_domains provided
    if excluded_domains:
        excluded_set = set(excluded_domains)
        filtered_claims = []
        for claim in claims:
            metadata = claim.metadata if isinstance(claim.metadata, dict) else {}
            domain = metadata.get('domain')
            if domain not in excluded_set:
                filtered_claims.append(claim)
        claims = filtered_claims

    # Phase 3: LLM-based claim lifecycle evaluation (keep/archive/delete)
    # Can be enabled via environment variable or parameter
    phase3_enabled = use_llm_evaluation or os.getenv("PHASE3_LLM_EVALUATION", "false").lower() == "true"

    if phase3_enabled and claims and session_context:
        logger.info(f"[Phase 3] Evaluating {len(claims)} claims with LLM")
        evaluated_claims = []
        archive_ids = []
        delete_ids = []

        for claim in claims:
            try:
                decision = await evaluate_claim_with_llm(claim, session_context)

                logger.debug(f"[Phase 3] Claim {claim.claim_id}: {decision['decision']} (score={decision['quality_score']}, confidence={decision['confidence']})")

                if decision["decision"] == "keep_active":
                    evaluated_claims.append(claim)
                elif decision["decision"] == "archive_cold":
                    archive_ids.append(claim.claim_id)
                    # Archive claim (mark as archived, don't delete)
                    logger.info(f"[Phase 3] Archiving claim {claim.claim_id} (score={decision['quality_score']}, reason={decision['reasoning'][:100]})")
                elif decision["decision"] == "delete":
                    delete_ids.append(claim.claim_id)
                    logger.info(f"[Phase 3] Deleting claim {claim.claim_id} (score={decision['quality_score']}, reason={decision['reasoning'][:100]})")
            except Exception as e:
                logger.warning(f"[Phase 3] Failed to evaluate claim {claim.claim_id}: {e}, keeping by default")
                evaluated_claims.append(claim)

        # Archive claims (mark as archived instead of deleting)
        if archive_ids:
            logger.info(f"[Phase 3] Archiving {len(archive_ids)} claims based on LLM evaluation")
            try:
                claim_registry.archive_claims(archive_ids)
            except AttributeError:
                # Fallback if archive_claims method doesn't exist yet
                logger.warning(f"[Phase 3] archive_claims() not implemented, keeping archived claims active for now")
                evaluated_claims.extend([c for c in claims if c.claim_id in archive_ids])

        # Delete low-quality claims
        if delete_ids:
            logger.info(f"[Phase 3] Deleting {len(delete_ids)} low-quality claims based on LLM evaluation")
            claim_registry.delete_claims(delete_ids)

        claims = evaluated_claims

    sorted_claims = _sort_claims(claims)
    keep = sorted_claims[: config.max_claims]
    drop = sorted_claims[config.max_claims :]
    drop_ids = [c.claim_id for c in drop]
    if drop_ids:
        claim_registry.delete_claims(drop_ids)
        keep = [c for c in keep if c.claim_id not in drop_ids]
    fingerprint_map = {claim.fingerprint: claim for claim in keep if claim.fingerprint}
    claim_ids = [claim.claim_id for claim in keep]
    return WorkingMemorySnapshot(claims=keep, claim_ids=claim_ids, fingerprint_map=fingerprint_map)


def _extract_candidates(
    raw_bundle: RawBundle,
    *,
    tool_records: Sequence[Dict[str, Any]],
    artifact_store: ArtifactStore,
) -> Iterable[Candidate]:
    records_by_handle = {rec.get("handle"): rec for rec in tool_records if rec.get("handle")}
    for item in raw_bundle.items or []:
        record = records_by_handle.get(item.handle)
        tool = (item.metadata or {}).get("tool") or (record or {}).get("tool") or "tool"
        blob_id = item.blob_id or (record or {}).get("blob_id")
        payload = _resolve_payload(record, blob_id, artifact_store)
        if tool in {"purchasing.lookup", "commerce.search_offers"}:
            yield from _candidates_from_offers(item, payload, tool)
        elif tool == "research.orchestrate":
            yield from _candidates_from_research_orchestrate(item, payload)
        elif tool == "doc.search":
            yield from _candidates_from_docsearch(item, payload)
        elif tool == "bom.build":
            yield from _candidates_from_bom(item, payload)
        elif tool == "docs.write_spreadsheet":
            candidate = _candidate_from_spreadsheet(item)
            if candidate:
                yield candidate
        elif tool in {"file.create", "file.write", "file.edit", "file.delete", "code.apply_patch"}:
            # Track file creation/modification/deletion as code_change claims
            candidate = _candidate_from_file_operation(item, payload, tool)
            if candidate:
                yield candidate
        elif tool == "web.fetch_text":
            # Track web research as research claims
            candidate = _candidate_from_web_fetch(item, payload)
            if candidate:
                yield candidate
        else:
            candidate = _candidate_from_generic(item, payload, tool)
            if candidate:
                yield candidate


def _resolve_payload(
    record: Optional[Dict[str, Any]],
    blob_id: Optional[str],
    store: ArtifactStore,
) -> Any:
    if record and record.get("response") is not None:
        return record.get("response")
    if blob_id:
        try:
            data = store.read_text(blob_id)
            return json.loads(data)
        except Exception:
            try:
                return data  # type: ignore[misc]
            except UnboundLocalError:
                return None
    preview = record.get("resp_preview") if record else None
    if isinstance(preview, str):
        try:
            return json.loads(preview)
        except Exception:
            return preview
    return None


def _candidates_from_offers(item: RawBundleItem, payload: Any, tool: str) -> Iterable[Candidate]:
    offers = []
    if isinstance(payload, dict):
        offers = payload.get("offers") or payload.get("results") or []
    if not isinstance(offers, list):
        offers = []

    # NEGATIVE CLAIM: Create diagnostic claim when zero offers found
    if len(offers) == 0 and isinstance(payload, dict):
        query = payload.get("query", "unknown query")
        issues = payload.get("issues", [])
        suggested_refinement = payload.get("suggested_refinement")

        text_parts = [f"No offers found for '{query}'"]
        if issues:
            text_parts.append(f"Issues: {', '.join(issues[:2])}")  # Limit to 2 issues
        if suggested_refinement and isinstance(suggested_refinement, dict):
            rationale = suggested_refinement.get("rationale", "")
            if rationale:
                text_parts.append(f"Suggestion: {rationale[:100]}")  # Truncate to 100 chars

        yield Candidate(
            text=" ".join(text_parts),
            evidence=[item.handle],
            source_tool=tool,
            confidence="high",
            domain="search_quality",
            topics=["zero_results", "diagnostics"],
            artifact=None,
            metadata={
                "zero_results": True,
                "query": query,
                "issues": issues,
                "suggested_action": "broaden search parameters or try different query"
            }
        )
        return  # Don't process further

    for idx, offer in enumerate(offers[:6]):
        title = _safe_str(offer.get("title") or offer.get("name") or "offer")
        source = _safe_str(offer.get("source") or offer.get("seller") or offer.get("vendor") or "vendor")
        price_text = _safe_price(offer)
        availability = _safe_str(offer.get("availability") or offer.get("stock") or "")
        link = _safe_str(
            offer.get("link")
            or offer.get("product_link")
            or offer.get("url")
            or offer.get("source_url")
            or ""
        )
        title_lower = title.lower()
        source_lower = source.lower()
        skip = any(keyword in title_lower for keyword in _OFFER_SKIP_KEYWORDS) or any(
            keyword in source_lower for keyword in _OFFER_SKIP_KEYWORDS
        )
        if skip:
            continue
        parts = [title]
        if price_text:
            parts.append(f"priced at {price_text}")
        if source:
            parts.append(f"from {source}")
        if availability:
            parts.append(f"({availability})")
        text = " ".join(parts)
        artifact = None
        if item.blob_id:
            artifact = CapsuleArtifact(label=f"{source or 'offer'} listing", blob_id=item.blob_id)
        yield Candidate(
            text=text.strip(),
            evidence=[item.handle],
            source_tool=tool,
            confidence="high" if price_text else "medium",
            domain="pricing",
            topics=["purchase", "pricing"],
            artifact=artifact,
            metadata={
                "offer_index": idx,
                "price_text": price_text,
                "source": source,
                "availability": availability,
                "link": link,
                "title": title,
            },
        )


def _candidates_from_research_orchestrate(item: RawBundleItem, payload: Any) -> Iterable[Candidate]:
    """Extract candidates from research.orchestrate results."""
    if not isinstance(payload, dict):
        return

    results = payload.get("results", [])
    if not isinstance(results, list):
        return

    quality_metrics = payload.get("quality_metrics", {})
    cache_hit = quality_metrics.get("cache_hit", False)

    # NEGATIVE CLAIM: Create diagnostic claim when zero results found
    if len(results) == 0:
        query = payload.get("query", "unknown query")
        issues = quality_metrics.get("issues", [])
        suggested_refinement = quality_metrics.get("suggested_refinement")

        text = f"Research search returned 0 results for '{query}'"
        if issues:
            text += f". Issues: {', '.join(issues[:2])}"
        if suggested_refinement:
            if isinstance(suggested_refinement, dict):
                rationale = suggested_refinement.get("rationale", "")
                if rationale:
                    text += f". Suggestion: {rationale[:100]}"
            elif isinstance(suggested_refinement, str):
                text += f". Suggestion: {suggested_refinement[:100]}"

        yield Candidate(
            text=text,
            evidence=[item.handle],
            source_tool="research.orchestrate",
            confidence="high",
            domain="search_quality",
            topics=["zero_results", "diagnostics"],
            artifact=None,
            metadata={
                "zero_results": True,
                "query": query,
                "issues": issues,
                "suggested_refinement": suggested_refinement,
                "cache_hit": cache_hit
            }
        )
        return  # Don't process further

    for idx, result in enumerate(results[:8]):  # Limit to top 8 results
        title = _safe_str(result.get("title") or "")
        snippet = _safe_str(result.get("snippet") or "")
        link = _safe_str(result.get("link") or result.get("url") or "")

        if not title and not snippet:
            continue

        # Build claim text
        if snippet:
            text = f"{title}: {snippet[:150]}"
        else:
            text = title

        # Extract metadata
        metadata = {
            "result_index": idx,
            "url": link,
            "title": title,
            "relevance_score": result.get("relevance_score", 0),
            "verified": result.get("verified", False),
            "cache_hit": cache_hit,
        }

        # Include verification status if available
        if result.get("verified"):
            metadata["fetch_status"] = result.get("fetch_status", 200)

        # Determine confidence based on verification and relevance
        relevance = result.get("relevance_score", 0)
        verified = result.get("verified", False)

        if verified and relevance >= 70:
            confidence = "high"
        elif verified or relevance >= 60:
            confidence = "medium"
        else:
            confidence = "low"

        # Extract topics from URL or title
        topics = ["research", "documentation"]
        if link:
            # Try to extract domain as topic
            try:
                from urllib.parse import urlparse
                domain = urlparse(link).netloc
                if domain:
                    topics.append(domain)
            except Exception:
                pass

        # Create artifact if verified
        artifact = None
        if result.get("verified") and item.blob_id:
            artifact = CapsuleArtifact(label=f"{title[:50]}...", blob_id=item.blob_id)

        yield Candidate(
            text=text.strip(),
            evidence=[item.handle],
            source_tool="research.orchestrate",
            confidence=confidence,
            domain="research",
            topics=topics,
            artifact=artifact,
            metadata=metadata,
            ttl_seconds=86400 * 7 if cache_hit else 86400,  # 7 days if cached, 1 day if fresh
        )


def _candidates_from_docsearch(item: RawBundleItem, payload: Any) -> Iterable[Candidate]:
    chunks = []
    if isinstance(payload, dict):
        chunks = payload.get("chunks") or []
    for idx, chunk in enumerate(chunks[:8]):
        excerpt = _safe_str(chunk.get("text_excerpt") or chunk.get("excerpt") or "")
        if not excerpt:
            continue
        summary = " ".join(excerpt.split()[:80]).strip()
        path = chunk.get("path")
        topics = []
        if path:
            topics.append(Path(path).name)
        metadata = {"chunk_index": idx, "path": path}
        yield Candidate(
            text=summary,
            evidence=[item.handle],
            source_tool="doc.search",
            confidence="medium",
            domain="spec",
            topics=topics,
            artifact=None,
            metadata=metadata,
        )


def _candidates_from_bom(item: RawBundleItem, payload: Any) -> Iterable[Candidate]:
    rows = []
    if isinstance(payload, dict):
        rows = payload.get("rows") or []
    if rows:
        head = rows[0]
        vendor = _safe_str(head.get("vendor") or head.get("supplier") or "")
        price = _safe_price(head)
        text = f"{vendor or 'vendor'} pricing rows available {price}".strip()
    else:
        text = item.summary or "Bill of materials generated."
    artifact = CapsuleArtifact(label="BOM spreadsheet", blob_id=item.blob_id) if item.blob_id else None
    yield Candidate(
        text=text,
        evidence=[item.handle],
        source_tool="bom.build",
        confidence="medium",
        domain="pricing",
        topics=["bom", "spreadsheet"],
        artifact=artifact,
        metadata={"rows": len(rows)},
    )


def _candidate_from_spreadsheet(item: RawBundleItem) -> Optional[Candidate]:
    if not item.blob_id:
        return None
    artifact = CapsuleArtifact(label=item.summary or "Spreadsheet", blob_id=item.blob_id)
    text = item.summary or "Spreadsheet generated for user."
    return Candidate(
        text=text,
        evidence=[item.handle],
        source_tool="docs.write_spreadsheet",
        confidence="medium",
        domain="spec",
        topics=["spreadsheet"],
        artifact=artifact,
        metadata={"summary": text},
    )


def _candidate_from_file_operation(item: RawBundleItem, payload: Any, tool: str) -> Optional[Candidate]:
    """Create candidate for file.create, file.write, file.edit, or code.apply_patch operations."""
    if not isinstance(payload, dict):
        return None

    # Handle error responses
    error = payload.get("error")
    if error:
        error_str = str(error)

        # Try to extract file path from error message
        # e.g., "409 Conflict: File /path/to/file already exists"
        path_match = re.search(r'File (.*?) already exists', error_str)
        path = path_match.group(1) if path_match else payload.get("file_path") or payload.get("path") or "target file"

        # Classify error type
        if "already exists" in error_str.lower() or "409" in error_str:
            # File already exists - treat as idempotent success
            text = f"File operation skipped: {path} already exists"
            confidence = "high"
            operation = "conflict"
        elif "permission" in error_str.lower() or "403" in error_str:
            text = f"File operation blocked: insufficient permissions for {path}"
            confidence = "high"
            operation = "error"
        elif "not found" in error_str.lower() or "404" in error_str:
            text = f"File operation failed: {path} not found"
            confidence = "high"
            operation = "error"
        else:
            # Generic error
            text = f"File operation failed: {error_str[:100]}"
            confidence = "medium"
            operation = "error"

        return Candidate(
            text=text.strip(),
            evidence=[item.handle],
            source_tool=tool,
            confidence=confidence,
            domain="code_change",
            topics=["code", "file", operation],
            artifact=None,
            metadata={
                "error": error_str,
                "operation": operation,
                "file": str(path),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            ttl_seconds=300,  # Short TTL for errors (5 minutes)
        )

    # Handle successful operations
    path = _safe_str(payload.get("path") or payload.get("file_path") or "")
    if not path:
        return None

    # Determine operation type
    if tool in {"file.create", "file.write"}:
        operation = "created"
    elif tool in {"file.edit", "code.apply_patch"}:
        operation = "modified"
    elif tool == "file.delete":
        operation = "deleted"
    else:
        operation = "updated"

    text = f"{operation.capitalize()} {path}"

    # Extract file metadata
    metadata = {
        "file": path,
        "operation": operation,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Add file size if available
    if "bytes" in payload:
        metadata["bytes"] = payload.get("bytes")

    # For targeted changes, include target info
    if "target" in payload:
        metadata["target"] = payload.get("target")
        text += f" (target: {payload.get('target')})"

    return Candidate(
        text=text.strip(),
        evidence=[item.handle],
        source_tool=tool,
        confidence="high",
        domain="code_change",
        topics=["code", "file", operation],
        artifact=None,
        metadata=metadata,
        ttl_seconds=86400 * 7,  # 7 days for code changes
    )


def _candidate_from_web_fetch(item: RawBundleItem, payload: Any) -> Optional[Candidate]:
    """Create candidate for web.fetch_text operations."""
    if not isinstance(payload, dict):
        return None
    
    url = _safe_str(payload.get("url") or "")
    title = _safe_str(payload.get("title") or "")
    
    if not url:
        return None
    
    # Create summary text
    if title:
        text = f"Researched: {title}"
    else:
        # Use URL but truncate if too long
        display_url = url if len(url) < 60 else url[:57] + "..."
        text = f"Researched: {display_url}"
    
    metadata = {
        "url": url,
        "title": title,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    # Include content length if available
    if "content" in payload:
        content = payload.get("content") or ""
        metadata["content_length"] = len(content)
    
    return Candidate(
        text=text.strip(),
        evidence=[item.handle],
        source_tool="web.fetch_text",
        confidence="medium",
        domain="research",
        topics=["research", "documentation"],
        artifact=None,
        metadata=metadata,
        ttl_seconds=86400,  # 1 day for research
    )


def _candidate_from_generic(item: RawBundleItem, payload: Any, tool: str) -> Optional[Candidate]:
    summary = item.summary or ""
    if not summary and isinstance(payload, dict):
        summary = json.dumps(payload)[:200]
    text = summary.strip()
    if not text:
        return None
    artifact = CapsuleArtifact(label=f"{tool} artifact", blob_id=item.blob_id) if item.blob_id else None
    return Candidate(
        text=text,
        evidence=[item.handle],
        source_tool=tool,
        confidence="medium",
        domain=None,
        topics=[tool],
        artifact=artifact,
        metadata={"summary": summary},
    )


def _format_claim_summary(claim: CapsuleClaim) -> str:
    text = (claim.claim or "").strip()
    meta = claim.metadata if isinstance(claim.metadata, dict) else {}
    title = _safe_str(meta.get("title") or text)
    price = _safe_str(meta.get("price_text") or "")
    source = _safe_str(meta.get("source") or "")
    availability = _safe_str(meta.get("availability") or "")
    link = _safe_str(meta.get("link") or "")

    detail_parts: list[str] = []
    if price and source:
        detail_parts.append(f"{price} from {source}")
    elif price:
        detail_parts.append(price)
    elif source:
        detail_parts.append(f"from {source}")
    if availability:
        detail_parts.append(f"({availability})")
    detail = " ".join(part for part in detail_parts if part)

    if link:
        head = f"[{title}]({link})"
        tail = detail or text
        return f"{head} — {tail}".strip()
    if detail:
        return f"{title} — {detail}".strip()
    return text or title


def _score_candidates(
    candidates: List[Candidate],
    *,
    ticket: TaskTicket,
    config: WorkingMemoryConfig,
    existing_fingerprints: Iterable[str],
    freshness: FreshnessOracle,
    now: datetime,
) -> List[Candidate]:
    goal_parts = [ticket.goal or ""]
    if ticket.micro_plan:
        goal_parts.extend(str(part) for part in ticket.micro_plan if part)
    goal_text = " ".join(goal_parts)
    goal_tokens = _tokenize(goal_text)
    existing_fp_set = set(existing_fingerprints)

    # URL-based deduplication: Track seen URLs to prevent duplicate offers
    seen_urls: set[str] = set()

    for cand in candidates:
        cand_tokens = _tokenize(cand.text)
        relevance = _cosine(goal_tokens, cand_tokens)
        temp_claim = CapsuleClaim(
            claim=cand.text,
            evidence=cand.evidence,
            confidence=cand.confidence,
            last_verified=now.isoformat(),
        )
        fingerprint = ClaimRegistry.fingerprint(temp_claim)
        cand.fingerprint = fingerprint
        novelty = 0.1 if fingerprint in existing_fp_set else 1.0

        # URL-based deduplication: Heavily penalize duplicate URLs
        if cand.metadata and isinstance(cand.metadata, dict):
            url = cand.metadata.get("link") or cand.metadata.get("url") or cand.metadata.get("source_url")
            if url:
                url_normalized = url.strip().lower()
                if url_normalized in seen_urls:
                    # Duplicate URL - set score to near-zero so it gets filtered out
                    novelty = 0.01  # Very low novelty for duplicates
                else:
                    seen_urls.add(url_normalized)

        decision_impact = 1.0 if (_NUMERIC_RE.search(cand.text) or _CURRENCY_RE.search(cand.text)) else 0.3
        if cand.domain == "pricing":
            decision_impact = 1.0

        ttl_seconds = _ttl_for_candidate(cand, freshness, config)
        cand.ttl_seconds = ttl_seconds
        freshness_score = 1.0 if ttl_seconds >= 0 else 0.5

        cand.score = (
            0.45 * relevance
            + 0.25 * novelty
            + 0.20 * decision_impact
            + 0.10 * freshness_score
        )
    return candidates


def _ttl_for_candidate(cand: Candidate, freshness: FreshnessOracle, config: WorkingMemoryConfig) -> int:
    if cand.domain and cand.domain in config.domain_ttl_days:
        return config.domain_ttl_days[cand.domain] * 86400
    return freshness.suggest_ttl_seconds(cand.confidence)


def _sort_claims(claims: Sequence[ClaimRow]) -> List[ClaimRow]:
    def score(claim: ClaimRow) -> float:
        meta = claim.metadata if isinstance(claim.metadata, dict) else {}
        return float(meta.get("score", 0.0))

    return sorted(claims, key=lambda c: (score(c), c.updated_at), reverse=True)


def _tokenize(text: str) -> Counter[str]:
    tokens = _WORD_RE.findall(text.lower())
    return Counter(tokens)


def _cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a[t] * b[t] for t in set(a) & set(b))
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _estimate_budget(
    raw_bundle: RawBundle,
    claims: Sequence[CapsuleClaim],
    artifacts: Sequence[CapsuleArtifact],
) -> Dict[str, Any]:
    bundle_tokens = sum(len((item.preview or "")[:400]) // 4 for item in raw_bundle.items or [])
    claim_tokens = sum(len(claim.claim) // 4 for claim in claims)
    return {
        "raw_tokens": int(bundle_tokens),
        "reduced_tokens": int(claim_tokens),
        "artifact_handles": len(artifacts),
    }


def _safe_price(obj: Any) -> str:
    if not isinstance(obj, dict):
        return ""
    price_text = obj.get("price_text") or obj.get("priceText")
    if price_text:
        return str(price_text)
    currency = obj.get("currency")
    price = obj.get("price") or obj.get("amount")
    if price is None:
        return ""
    try:
        value = float(price)
    except Exception:
        return str(price)
    prefix = f"{currency} " if currency else ""
    return f"{prefix}{value:.2f}".strip()


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _compute_quality_report(
    tool_records: Sequence[Dict[str, Any]],
    *,
    quality_threshold: float = 0.3,
) -> Optional[QualityReport]:
    """
    Compute quality diagnostics from tool records for retry logic.
    Only applicable to commerce/pricing tools that track verification.
    """
    # Check if any commerce/pricing tools were used
    commerce_tools = ["commerce.search_offers", "purchasing.lookup"]
    commerce_records = [
        rec for rec in tool_records 
        if rec.get("tool") in commerce_tools
    ]
    
    if not commerce_records:
        return None  # Quality report only for commerce searches
    
    # Aggregate stats across all commerce tool calls
    total_fetched = 0
    verified = 0
    rejected = 0
    rejection_counts: Dict[str, int] = {}
    
    for record in commerce_records:
        response = record.get("response", {})
        if not isinstance(response, dict):
            continue
        
        # Check for v2 commerce response format with stats
        stats = response.get("stats", {})
        if stats:
            total_fetched += stats.get("raw_count", 0)
            verified += stats.get("verified_count", 0)
            rejected += stats.get("rejected_count", 0)
        
        # Aggregate rejection reasons
        rejected_items = response.get("rejected", [])
        if isinstance(rejected_items, list):
            for item in rejected_items:
                if isinstance(item, dict):
                    reasons = item.get("rejection_reasons", [])
                    for reason in reasons:
                        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
    
    # If no data collected, return None
    if total_fetched == 0:
        return None
    
    # Compute quality score
    quality_score = verified / max(1, total_fetched)
    meets_threshold = quality_score >= quality_threshold
    
    # Generate refinement suggestion if quality is low
    suggested_refinement = None
    if not meets_threshold and rejection_counts:
        # Find dominant rejection reason
        top_reason, top_count = max(
            rejection_counts.items(),
            key=lambda x: x[1]
        )
        
        refinement = {
            "reason": f"High rejection rate: {top_reason} ({top_count} items)",
            "add_negative_keywords": [],
            "add_positive_keywords": [],
        }
        
        # Map rejection reasons to filter adjustments
        if "educational_resource" in rejection_counts:
            refinement["add_negative_keywords"].extend(["educational", ".edu", "classroom"])
        if "appears_to_be_cage" in rejection_counts:
            refinement["add_negative_keywords"].extend(["cage", "habitat", "enclosure"])
        if "appears_to_be_book" in rejection_counts:
            refinement["add_negative_keywords"].extend(["book", "isbn", "paperback"])
        if "wrong_item_type" in rejection_counts:
            refinement["add_positive_keywords"].append("authentic")
        
        suggested_refinement = refinement
    
    return QualityReport(
        total_fetched=total_fetched,
        verified=verified,
        rejected=rejected,
        rejection_breakdown=rejection_counts,
        quality_score=quality_score,
        meets_threshold=meets_threshold,
        suggested_refinement=suggested_refinement,
    )
