"""
Validation Handler - Price/URL verification and retry logic.

Extracted from UnifiedFlow to provide:
- Response validation (prices, URLs)
- Retry context management
- Claim invalidation on failure
- Archive management for failed attempts

Architecture Reference:
- architecture/main-system-patterns/phase7-validation.md

Price Priority (per spec):
1. toolresults.md - Exact prices (authoritative)
2. section 4 claims table - LLM-summarized
3. section 2 gathered context - Prior research (may be stale)
"""

import asyncio
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from libs.gateway.validation.validation_result import (
    ValidationResult,
    ValidationFailureContext,
    GoalStatus,
    MAX_VALIDATION_RETRIES,
)

if TYPE_CHECKING:
    from libs.gateway.context.context_document import ContextDocument
    from libs.gateway.persistence.turn_manager import TurnDirectory

logger = logging.getLogger(__name__)

# Configuration
ENABLE_URL_VERIFICATION = os.getenv("VALIDATION_ENABLE_URL_CHECK", "true").lower() == "true"
ENABLE_PRICE_CROSSCHECK = True
VALIDATION_URL_TIMEOUT = int(os.getenv("VALIDATION_URL_TIMEOUT", "5"))
MAX_VALIDATION_REVISIONS = 2


# =============================================================================
# URL/Price Extraction Helpers
# =============================================================================

def extract_prices_from_text(text: str) -> List[str]:
    """
    Extract price values from text (e.g., $624.99, $1,299.00).

    Returns normalized prices in $X.XX format.
    """
    pattern = r'\$[\d,]+(?:\.\d{2})?'
    matches = re.findall(pattern, text)

    normalized = []
    for m in matches:
        clean = m.replace('$', '').replace(',', '')
        try:
            val = float(clean)
            normalized.append(f"${val:.2f}")
        except ValueError:
            pass
    return normalized


def prices_match(
    response_prices: List[str],
    research_prices: List[str],
    tolerance: float = 0.01
) -> Tuple[bool, List[str]]:
    """
    Check if response prices exist in research prices.

    Args:
        response_prices: Prices found in the response
        research_prices: Prices from research/tool results
        tolerance: Float tolerance for comparison

    Returns:
        (all_matched, missing_prices)
    """
    if not response_prices:
        return True, []

    def to_float(p: str) -> float:
        return float(p.replace('$', '').replace(',', ''))

    research_values = set()
    for p in research_prices:
        try:
            research_values.add(to_float(p))
        except ValueError:
            pass

    missing = []
    for rp in response_prices:
        try:
            rv = to_float(rp)
            found = any(abs(rv - rv2) < tolerance for rv2 in research_values)
            if not found:
                missing.append(rp)
        except ValueError:
            pass

    return len(missing) == 0, missing


def extract_urls_from_text(text: str) -> List[str]:
    """
    Extract URLs from text.

    Returns deduplicated list of cleaned URLs.
    """
    url_pattern = r'https?://[^\s\)\]\>\"\'<]+'
    matches = re.findall(url_pattern, text)

    cleaned = []
    for url in matches:
        url = url.rstrip('.,;:!?)')
        if url and len(url) > 10:
            cleaned.append(url)
    return list(set(cleaned))


def normalize_url_for_comparison(url: str) -> str:
    """
    Normalize URL for comparison purposes.

    Handles:
    - www. prefix (remove for comparison)
    - Trailing slashes
    - Case sensitivity in domain
    - Query parameters (remove for domain matching)
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url.lower())
        domain = parsed.netloc
        path = parsed.path

        # Remove www. prefix
        if domain.startswith('www.'):
            domain = domain[4:]

        # Remove trailing slash from path
        path = path.rstrip('/')

        return f"{domain}{path}"
    except Exception:
        return url.lower()


def url_matches_any(url: str, known_urls: List[str]) -> bool:
    """
    Check if URL matches any of the known URLs (with normalization).

    Uses progressive matching:
    1. Exact match (after normalization)
    2. Domain match (same site, different path is OK)
    """
    normalized = normalize_url_for_comparison(url)
    url_domain = normalized.split('/')[0] if '/' in normalized else normalized

    for known in known_urls:
        known_norm = normalize_url_for_comparison(known)
        known_domain = known_norm.split('/')[0] if '/' in known_norm else known_norm

        # Exact path match
        if normalized == known_norm:
            return True

        # Domain match (we visited this site, paths may differ slightly)
        if url_domain == known_domain:
            return True

    return False


# =============================================================================
# Validation Handler Class
# =============================================================================

class ValidationHandler:
    """
    Handles response validation and retry logic.

    Responsibilities:
    - Cross-check prices against toolresults.md
    - Verify URLs against research.json
    - Archive failed attempts
    - Write retry context for context gatherer
    - Invalidate failed claims
    - Run the full Phase 7 validation loop (extracted 2026-02-03)
    """

    def __init__(self, llm_client: Any = None):
        """Initialize the validation handler."""
        self.llm_client = llm_client

        # Callbacks for UnifiedFlow methods
        self._write_context_md: Optional[Callable] = None
        self._call_validator_llm: Optional[Callable] = None
        self._parse_json_response: Optional[Callable] = None
        self._check_budget: Optional[Callable] = None
        self._revise_synthesis: Optional[Callable] = None
        self._get_unhealthy_urls: Optional[Callable] = None
        self._principle_extractor: Any = None

    def set_callbacks(
        self,
        write_context_md: Callable,
        call_validator_llm: Callable,
        parse_json_response: Callable,
        check_budget: Callable,
        revise_synthesis: Callable,
        get_unhealthy_urls: Callable,
        principle_extractor: Any = None,
    ):
        """Set callbacks to UnifiedFlow methods."""
        self._write_context_md = write_context_md
        self._call_validator_llm = call_validator_llm
        self._parse_json_response = parse_json_response
        self._check_budget = check_budget
        self._revise_synthesis = revise_synthesis
        self._get_unhealthy_urls = get_unhealthy_urls
        self._principle_extractor = principle_extractor

    async def run_validation(
        self,
        context_doc: "ContextDocument",
        turn_dir: "TurnDirectory",
        response: str,
        mode: str,
        loop_count: int = 0,
    ) -> Tuple["ContextDocument", str, ValidationResult]:
        """
        Run the Phase 7 validation loop.

        Args:
            context_doc: Context document
            turn_dir: Turn directory
            response: Synthesized response to validate
            mode: Current mode (chat, research, commerce)
            loop_count: Current validation retry count

        Returns:
            (context_doc, response, ValidationResult)
        """
        logger.info(f"[ValidationHandler] Phase 7: Validation (loop={loop_count})")

        checks_performed = []
        all_issues = []
        revision_count = 0
        confidence = 0.8

        # Initialize URL tracking variables
        valid_urls: List[str] = []
        invalid_urls: List[str] = []

        # Track original response and hints for principle extraction
        original_response_for_principle = response
        revision_hints_for_principle = ""
        revision_focus_for_principle = ""

        # PROGRAMMATIC URL CHECK (defense in depth)
        unhealthy_urls, url_issues = self._get_unhealthy_urls(response)
        if unhealthy_urls:
            logger.warning(f"[ValidationHandler] Programmatic URL check failed: {url_issues}")
            checks_performed.append("programmatic_url_check_failed")

            # For commerce queries with fake URLs, we need to RETRY
            original_query = context_doc.get_original_query() if hasattr(context_doc, 'get_original_query') else ""
            is_commerce = any(kw in original_query.lower() for kw in [
                "buy", "purchase", "for sale", "cheapest", "price", "cost", "order"
            ])

            if is_commerce:
                logger.warning(f"[ValidationHandler] Commerce query with fake URLs - triggering RETRY")
                failure_context = ValidationFailureContext(
                    reason="FAKE_URL_DETECTED",
                    failed_claims=[],
                    failed_urls=unhealthy_urls,
                    mismatches=[],
                    retry_count=loop_count + 1,
                    suggested_fixes=["Evidence contains fake/corrupted URLs - re-research needed to get real product links"]
                )

                self.write_validation_section(
                    context_doc, "RETRY", 0.3, 0,
                    ["Programmatic URL check: " + "; ".join(url_issues)],
                    ["Re-research needed - URLs appear to be placeholders or corrupted"]
                )

                return context_doc, response, ValidationResult(
                    decision="RETRY",
                    confidence=0.3,
                    issues=["Programmatic URL check failed: " + "; ".join(url_issues)],
                    failure_context=failure_context,
                    checks_performed=checks_performed,
                    retry_count=loop_count + 1
                )
            else:
                all_issues.append(f"Programmatic URL check warning: {'; '.join(url_issues)}")
                logger.info(f"[ValidationHandler] Non-commerce query - continuing to LLM validation despite URL issues")
        else:
            checks_performed.append("programmatic_url_check_passed")
            logger.debug("[ValidationHandler] Programmatic URL check passed")

        # === VALIDATION LOOP ===
        while revision_count <= MAX_VALIDATION_REVISIONS:
            # Write current context.md
            self._write_context_md(turn_dir, context_doc)

            llm_response = ""
            try:
                # Call validator LLM (callback handles recipe loading, budget check, etc.)
                result = await self._call_validator_llm(context_doc, turn_dir, revision_count)
                decision = result.get("decision")
                if decision is None:
                    raise ValueError(f"Validator LLM response missing 'decision' field: {result}")
                issues_raw = result.get("issues", [])
                issues = [issues_raw] if isinstance(issues_raw, str) else (issues_raw or [])
                confidence = result.get("confidence", 0.8)
                revision_hints = result.get("revision_hints", "")
                suggested_fixes_raw = result.get("suggested_fixes", [])
                suggested_fixes = [suggested_fixes_raw] if isinstance(suggested_fixes_raw, str) else (suggested_fixes_raw or [])
                checks = result.get("checks", {})
                checks_performed.append("llm_validation")

                # Parse goal statuses for multi-goal queries
                goal_statuses_raw = result.get("goal_statuses", [])
                goal_statuses = []
                for gs in goal_statuses_raw:
                    goal_statuses.append(GoalStatus(
                        goal_id=gs.get("goal_id", "unknown"),
                        description=gs.get("description", ""),
                        score=gs.get("score", 0.0),
                        status=gs.get("status", "unfulfilled"),
                        evidence=gs.get("evidence")
                    ))

                # Handle RETRY from LLM validator
                if decision == "RETRY":
                    logger.info(f"[ValidationHandler] LLM Validator returned RETRY: {issues}")
                    failure_context = ValidationFailureContext(
                        reason="LLM_VALIDATION_RETRY",
                        failed_claims=[],
                        failed_urls=[],
                        mismatches=[],
                        retry_count=loop_count + 1,
                        suggested_fixes=suggested_fixes
                    )
                    self.write_validation_section(context_doc, "RETRY", confidence, revision_count, issues, suggested_fixes)
                    return context_doc, response, ValidationResult(
                        decision="RETRY",
                        confidence=confidence,
                        issues=issues,
                        failure_context=failure_context,
                        checks_performed=checks_performed,
                        retry_count=loop_count + 1
                    )

            except Exception as e:
                logger.error(f"[ValidationHandler] Validator failed: {e}")
                raise

            # Constraint validation check — run unconditionally regardless of decision
            constraints_ok, constraint_violations = self._check_constraint_violations(turn_dir)
            checks_performed.append("constraint_check")
            if not constraints_ok:
                logger.warning(f"[ValidationHandler] Constraint violations detected: {constraint_violations}")
                all_issues.append(f"Constraint violations: {len(constraint_violations)}")
                checks["constraints_respected"] = False
                checks["constraint_violations"] = constraint_violations
            else:
                checks["constraints_respected"] = True

            if decision == "APPROVE":
                urls_ok = True
                valid_urls = []
                invalid_urls = []

                # Price cross-check
                price_ok, missing_prices, price_hint = self.cross_check_prices(response, turn_dir)
                checks_performed.append("price_crosscheck")

                if not price_ok:
                    all_issues.append(f"Price mismatch: {missing_prices}")
                    if loop_count < MAX_VALIDATION_RETRIES - 1:
                        logger.warning(f"[ValidationHandler] Price mismatch detected, triggering RETRY")
                        failure_context = ValidationFailureContext(
                            reason="PRICE_STALE",
                            failed_claims=[],
                            failed_urls=[],
                            mismatches=[{"field": "price", "expected": p, "actual": "unknown"} for p in missing_prices],
                            retry_count=loop_count + 1
                        )
                        self.write_validation_section(context_doc, "RETRY", confidence, revision_count, all_issues)
                        return context_doc, response, ValidationResult(
                            decision="RETRY",
                            confidence=0.0,
                            issues=all_issues,
                            failure_context=failure_context,
                            checks_performed=checks_performed,
                            prices_checked=len(missing_prices),
                            retry_count=loop_count + 1
                        )

                    if revision_count < MAX_VALIDATION_REVISIONS:
                        decision = "REVISE"
                        issues.append(f"Stale prices detected: {missing_prices}")
                        revision_hints = price_hint
                        logger.warning(f"[ValidationHandler] Max loops reached, trying REVISE")

                # URL verification (advisory only)
                if decision == "APPROVE":
                    urls_ok, valid_urls, invalid_urls = await self.verify_urls_in_response(response, turn_dir)
                    checks_performed.append("url_verification")
                    if not urls_ok:
                        logger.warning(f"[ValidationHandler] Some URLs not in research.json (advisory): {[u[:50] for u in invalid_urls]}")

                # All checks passed - APPROVE or APPROVE_PARTIAL
                if decision == "APPROVE":
                    partial_message = None
                    final_decision = "APPROVE"

                    if goal_statuses:
                        fulfilled = [g for g in goal_statuses if g.status == "fulfilled"]
                        unfulfilled = [g for g in goal_statuses if g.status in ("unfulfilled", "partial")]
                        if fulfilled and unfulfilled:
                            final_decision = "APPROVE_PARTIAL"
                            fulfilled_desc = ", ".join(g.description[:50] for g in fulfilled)
                            unfulfilled_desc = ", ".join(g.description[:50] for g in unfulfilled)
                            partial_message = (
                                f"I found information about: {fulfilled_desc}. "
                                f"However, I couldn't find reliable information about: {unfulfilled_desc} - "
                                f"would you like me to search specifically for that?"
                            )
                            logger.info(f"[ValidationHandler] APPROVE_PARTIAL - {len(fulfilled)} fulfilled, {len(unfulfilled)} unfulfilled")

                    logger.info(f"[ValidationHandler] Validation {final_decision} (confidence={confidence:.2f})")

                    # Extract improvement principle if this APPROVE followed a REVISE
                    if revision_count > 0 and revision_hints_for_principle and self._principle_extractor:
                        try:
                            turn_id = turn_dir.name if hasattr(turn_dir, 'name') else str(turn_dir)
                            query_section = context_doc.get_section(0) or ""
                            asyncio.create_task(
                                self._principle_extractor.extract_and_store(
                                    original_response=original_response_for_principle,
                                    revised_response=response,
                                    revision_hints=revision_hints_for_principle,
                                    query=query_section[:500],
                                    turn_id=turn_id,
                                    revision_focus=revision_focus_for_principle,
                                )
                            )
                            logger.info(f"[ValidationHandler] Triggered async principle extraction")
                        except Exception as e:
                            logger.warning(f"[ValidationHandler] Principle extraction failed (non-fatal): {e}")

                    self.write_validation_section(
                        context_doc, final_decision, confidence, revision_count, [],
                        checks=checks, urls_ok=urls_ok, price_ok=price_ok
                    )

                    term_analysis = result.get("term_analysis", {}) if 'result' in dir() else {}
                    unsourced_claims = result.get("unsourced_claims", []) if 'result' in dir() else []

                    return context_doc, response, ValidationResult(
                        decision=final_decision,
                        confidence=confidence,
                        issues=[],
                        checks_performed=checks_performed,
                        urls_verified=len(valid_urls),
                        retry_count=loop_count,
                        goal_statuses=goal_statuses,
                        partial_message=partial_message,
                        checks=checks,
                        term_analysis=term_analysis,
                        unsourced_claims=unsourced_claims
                    )

            if decision == "REVISE" and revision_count < MAX_VALIDATION_REVISIONS:
                revision_count += 1
                logger.info(f"[ValidationHandler] REVISE requested (attempt {revision_count})")
                logger.info(f"[ValidationHandler] Issues: {issues}")
                logger.info(f"[ValidationHandler] Hints: {revision_hints}")

                revision_hints_for_principle = revision_hints
                revision_focus_for_principle = result.get("revision_focus", "") if 'result' in dir() else ""

                # Re-synthesize with hints
                response = await self._revise_synthesis(context_doc, turn_dir, response, revision_hints, mode)

                revised_section = f"""**Draft Response (Revision {revision_count}):**
{response}
"""
                context_doc.update_section(6, revised_section)
                all_issues.extend(issues)

            else:
                # FAIL or max revisions reached
                logger.warning(f"[ValidationHandler] Validation FAILED - {issues}")
                all_issues.extend(issues)
                self.write_validation_section(context_doc, "FAIL", confidence, revision_count, all_issues)
                return context_doc, response, ValidationResult(
                    decision="FAIL",
                    confidence=0.0,
                    issues=all_issues,
                    checks_performed=checks_performed,
                    retry_count=loop_count
                )

        # Should not reach here
        self.write_validation_section(context_doc, "FAIL", confidence, revision_count, all_issues)
        return context_doc, response, ValidationResult(
            decision="FAIL",
            confidence=0.0,
            issues=all_issues + ["Max revision attempts reached"],
            checks_performed=checks_performed,
            retry_count=loop_count
        )

    def _check_constraint_violations(
        self,
        turn_dir: "TurnDirectory"
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Check if any constraint violations were recorded during execution.

        Reads violations from plan_state.json written by PlanStateManager
        when tool execution is blocked due to constraint violations.

        Args:
            turn_dir: Turn directory containing plan_state.json

        Returns:
            (passed, violations_list)
            - passed: True if no violations, False otherwise
            - violations_list: List of violation dicts if any
        """
        from libs.gateway.planning.plan_state import get_plan_state_manager
        psm = get_plan_state_manager()
        plan_state = psm.load_plan_state(turn_dir)

        if not plan_state:
            return True, []

        violations = plan_state.get("violations", [])
        if violations:
            logger.warning(
                f"[ValidationHandler] Found {len(violations)} constraint violations"
            )
            return False, violations
        return True, []

    def cross_check_prices(
        self,
        response: str,
        turn_dir: "TurnDirectory"
    ) -> Tuple[bool, List[str], str]:
        """
        Cross-check response prices against authoritative tool results.

        Uses toolresults.md as the authoritative source for exact prices.
        Per architecture spec (phase7-validation.md), price priority is:
        1. toolresults.md - Exact prices (authoritative)
        2. section 4 claims table - LLM-summarized
        3. section 2 gathered context - Prior research (may be stale)

        Args:
            response: The synthesized response text
            turn_dir: Turn directory to find toolresults.md

        Returns:
            (passed, missing_prices, hint_message)
        """
        if not ENABLE_PRICE_CROSSCHECK:
            return True, [], ""

        # Extract prices from response
        response_prices = extract_prices_from_text(response)
        if not response_prices:
            logger.debug("[ValidationHandler] No prices in response, skipping cross-check")
            return True, [], ""

        # Load toolresults.md for this turn (authoritative source per spec)
        toolresults_path = turn_dir.path / "toolresults.md"
        if not toolresults_path.exists():
            # Fallback to research.md if toolresults.md doesn't exist
            research_path = turn_dir.path / "research.md"
            if not research_path.exists():
                logger.debug("[ValidationHandler] No toolresults.md or research.md, skipping")
                return True, [], ""
            source_path = research_path
            source_name = "research.md"
        else:
            source_path = toolresults_path
            source_name = "toolresults.md"

        try:
            source_content = source_path.read_text()
            source_prices = extract_prices_from_text(source_content)

            if not source_prices:
                logger.debug(f"[ValidationHandler] No prices in {source_name}, skipping")
                return True, [], ""

            # Compare prices
            all_matched, missing = prices_match(response_prices, source_prices)

            if not all_matched:
                hint = (
                    f"PRICE MISMATCH: Response contains prices {missing} not found in "
                    f"{source_name}. Tool results found these prices: {source_prices[:5]}. "
                    f"Please use only prices from the current tool execution data."
                )
                logger.warning(f"[ValidationHandler] Price cross-check failed: {missing}")
                return False, missing, hint

            logger.info(
                f"[ValidationHandler] Price cross-check passed "
                f"({len(response_prices)} prices verified against {source_name})"
            )
            return True, [], ""

        except Exception as e:
            logger.error(f"[ValidationHandler] Price cross-check error: {e}")
            return True, [], ""  # Don't fail on errors, just skip

    async def verify_urls_in_response(
        self,
        response: str,
        turn_dir: Optional["TurnDirectory"] = None
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Verify URLs mentioned in response against research results.

        Cross-references URLs in the response against source_urls from research.json.
        This avoids redundant network requests since research already verified these URLs.

        Args:
            response: The synthesized response text
            turn_dir: Turn directory containing research.json

        Returns:
            (all_valid, valid_urls, invalid_urls)
            - valid_urls: URLs that exist in research.json source_urls
            - invalid_urls: URLs NOT found in research (potentially hallucinated)
        """
        if not ENABLE_URL_VERIFICATION:
            return True, [], []

        urls = extract_urls_from_text(response)
        if not urls:
            return True, [], []

        # Load research.json to get source_urls (URLs that were actually visited)
        research_urls = []
        vendor_urls = []

        if turn_dir:
            research_json_path = turn_dir.path / "research.json"
            if research_json_path.exists():
                try:
                    with open(research_json_path, 'r') as f:
                        research_data = json.load(f)

                    research_urls = research_data.get("source_urls", [])

                    for vendor in research_data.get("vendors", []):
                        if vendor.get("url"):
                            vendor_urls.append(vendor["url"])
                    for listing in research_data.get("listings", []):
                        if listing.get("url"):
                            vendor_urls.append(listing["url"])

                    logger.info(
                        f"[ValidationHandler] URL verification: Loaded {len(research_urls)} "
                        f"source URLs, {len(vendor_urls)} vendor/listing URLs"
                    )
                except Exception as e:
                    logger.warning(f"[ValidationHandler] Failed to load research.json: {e}")

        # Combine all known URLs from research
        all_known_urls = list(set(research_urls + vendor_urls))

        if not all_known_urls:
            logger.info("[ValidationHandler] No research URLs to cross-reference, passing")
            return True, urls, []

        # Cross-reference each response URL
        valid_urls = []
        invalid_urls = []

        for url in urls:
            if url_matches_any(url, all_known_urls):
                valid_urls.append(url)
                logger.debug(f"[ValidationHandler] URL verified: {url[:60]}")
            else:
                invalid_urls.append(url)
                logger.warning(f"[ValidationHandler] URL not in research: {url[:60]}")

        logger.info(
            f"[ValidationHandler] URL cross-reference: {len(valid_urls)} verified, "
            f"{len(invalid_urls)} not in research"
        )

        return len(invalid_urls) == 0, valid_urls, invalid_urls

    async def archive_attempt(
        self,
        turn_dir: "TurnDirectory",
        attempt: int
    ) -> None:
        """
        Archive current turn docs to attempt_N/ subfolder.

        This clears the turn directory for a fresh retry while preserving
        the failed attempt for debugging.
        """
        attempt_dir = turn_dir.path / f"attempt_{attempt}"
        attempt_dir.mkdir(exist_ok=True)

        doc_files = [
            "context.md", "research.md", "ticket.md", "response.md",
            "scan_result.md", "reflection.md", "toolresults.md"
        ]

        archived_count = 0
        for filename in doc_files:
            src = turn_dir.path / filename
            if src.exists():
                dst = attempt_dir / filename
                shutil.move(str(src), str(dst))
                archived_count += 1
                logger.debug(f"[ValidationHandler] Archived {filename}")

        logger.info(f"[ValidationHandler] Archived attempt {attempt} ({archived_count} files)")

    async def write_retry_context(
        self,
        turn_dir: "TurnDirectory",
        failure_context: ValidationFailureContext,
        session_id: str,
        turn_number: int
    ) -> None:
        """
        Write retry_context.json for Context Gatherer to read.

        This tells Context Gatherer:
        - This is a retry (not first attempt)
        - What failed (PRICE_STALE, URL_INVALID, etc.)
        - What to filter out (specific URLs, prices)
        - To use stricter TTL filtering
        - Session/turn ID for race condition protection

        IMPORTANT: Merges failed_urls from previous attempts.
        """
        if not failure_context:
            return

        retry_path = turn_dir.path / "retry_context.json"

        # Load existing retry_context to merge
        existing_failed_urls = []
        existing_failed_claims = []
        existing_mismatches = []
        if retry_path.exists():
            try:
                with open(retry_path, "r") as f:
                    existing = json.load(f)
                existing_failed_urls = existing.get("failed_urls", [])
                existing_failed_claims = existing.get("failed_claims", [])
                existing_mismatches = existing.get("mismatches", [])
                logger.info(
                    f"[ValidationHandler] Merging with {len(existing_failed_urls)} "
                    f"existing failed URLs"
                )
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[ValidationHandler] Could not read existing retry_context: {e}")

        # Merge (deduplicate URLs)
        all_failed_urls = list(set(existing_failed_urls + failure_context.failed_urls))
        all_failed_claims = existing_failed_claims + failure_context.failed_claims
        all_mismatches = existing_mismatches + failure_context.mismatches

        # Build merged failure context for instructions
        merged_failure = ValidationFailureContext(
            reason=failure_context.reason,
            failed_urls=all_failed_urls,
            failed_claims=all_failed_claims,
            mismatches=all_mismatches,
            retry_count=failure_context.retry_count
        )

        retry_context = {
            "is_retry": True,
            "session_id": session_id,
            "turn_number": turn_number,
            "attempt": failure_context.retry_count,
            "reason": failure_context.reason,
            "failed_urls": all_failed_urls,
            "failed_claims": all_failed_claims,
            "mismatches": all_mismatches,
            "instructions": self.get_retry_instructions(merged_failure)
        }

        retry_path.write_text(json.dumps(retry_context, indent=2, default=str))
        logger.info(
            f"[ValidationHandler] Wrote retry_context.json: reason={failure_context.reason}, "
            f"total_failed_urls={len(all_failed_urls)}"
        )

    def get_retry_instructions(
        self,
        failure_context: ValidationFailureContext
    ) -> List[str]:
        """
        Generate instructions for Context Gatherer based on failure reason.

        Args:
            failure_context: The validation failure context

        Returns:
            List of instruction strings
        """
        instructions = []

        if failure_context.reason == "PRICE_STALE":
            instructions.append("SKIP all price data from prior turns - prices are stale")
            instructions.append("Only use fresh prices from new research")
            for mismatch in failure_context.mismatches:
                if mismatch.get("field") == "price":
                    instructions.append(f"AVOID price: {mismatch.get('expected')}")

        elif failure_context.reason in ("URL_INVALID", "URL_NOT_IN_RESEARCH"):
            instructions.append("SKIP these URLs - they were not found in research results:")
            for url in failure_context.failed_urls:
                instructions.append(f"  - {url}")
            instructions.append("Only use URLs from the research.json source_urls")
            instructions.append("Do NOT include URLs that were not visited during research")

        elif failure_context.reason == "SPEC_MISMATCH":
            instructions.append("Product specifications have changed")
            instructions.append("SKIP cached product data from prior turns")
            instructions.append("Only use fresh research data")

        elif failure_context.reason == "STOCK_UNAVAILABLE":
            instructions.append("Stock/availability data is stale")
            instructions.append("SKIP stock info from prior turns")
            instructions.append("Only use fresh availability data")

        return instructions

    async def invalidate_claims(
        self,
        failure_context: ValidationFailureContext
    ) -> int:
        """
        Invalidate failed claims so they won't be reused on retry.

        Args:
            failure_context: The validation failure context

        Returns:
            Number of claims invalidated
        """
        if not failure_context:
            return 0

        invalidated = 0

        try:
            from libs.gateway.research.research_index_db import get_research_index_db
            research_index = get_research_index_db()

            # Invalidate by URL
            for url in failure_context.failed_urls:
                research_index.invalidate_by_url(url)
                invalidated += 1
                logger.info(f"[ValidationHandler] Invalidated claims for URL: {url[:50]}...")

            # Invalidate specific claims
            for claim in failure_context.failed_claims:
                claim_id = claim.get("id") or claim.get("source", "")
                if claim_id:
                    research_index.invalidate_by_id(claim_id)
                    invalidated += 1

            logger.info(f"[ValidationHandler] Invalidated {invalidated} claims/entries")

        except Exception as e:
            logger.error(f"[ValidationHandler] Claim invalidation error: {e}")

        return invalidated

    def write_validation_section(
        self,
        context_doc: Any,
        result: str,
        confidence: float,
        revision_count: int,
        issues: List[str],
        suggested_fixes: Optional[List[str]] = None,
        checks: Optional[Dict[str, bool]] = None,
        urls_ok: bool = True,
        price_ok: bool = True
    ) -> None:
        """
        Write §7 Validation section to context document.

        For RETRY decisions, includes suggested_fixes so Planner can read them
        and adjust the plan accordingly.

        Args:
            context_doc: Context document to update
            result: Validation result (APPROVE, APPROVE_PARTIAL, REVISE, RETRY, FAIL)
            confidence: Confidence score
            revision_count: Number of revision attempts
            issues: List of issues found
            suggested_fixes: Fixes for RETRY decisions
            checks: LLM validator's individual check results
            urls_ok: Result of URL verification check
            price_ok: Result of price cross-check
        """
        passed = result in ("APPROVE", "APPROVE_PARTIAL")

        # Use individual checks if provided, otherwise fall back to overall passed status
        if checks is None:
            checks = {}

        # Build section content
        section_content = f"""**Decision:** {result}
**Confidence:** {confidence:.2f}
**Revision Attempts:** {revision_count}
**Issues Found:** {", ".join(issues) if issues else "None"}
"""

        # Add suggested fixes for RETRY decisions (Planner reads these)
        if result == "RETRY" and suggested_fixes:
            section_content += f"""
**Decision:** RETRY
**Suggested Fixes for Planner:**
{chr(10).join(f"- {fix}" for fix in suggested_fixes)}
"""

        # Build checklist with granular check results
        section_content += f"""
**Validation Checklist:**
- [{"x" if checks.get("claims_supported", passed) else " "}] Claims supported by evidence
- [{"x" if checks.get("no_hallucinations", passed) else " "}] No hallucinations
- [{"x" if checks.get("query_addressed", passed) else " "}] Query addressed
- [{"x" if checks.get("coherent_format", passed) else " "}] Coherent format
- [{"x" if checks.get("source_metadata_present", passed) else " "}] Source metadata present
"""

        # Use append_to_section to preserve retry history
        if context_doc.has_section(7):
            # Add attempt header for retry history preservation
            attempt_header = f"\n\n---\n\n#### Attempt {revision_count + 1}\n"
            context_doc.append_to_section(7, attempt_header + section_content)
        else:
            # First validation - create section with attempt 1 header
            section_with_header = f"#### Attempt 1\n{section_content}"
            context_doc.append_section(7, "Validation", section_with_header)

        logger.info(f"[ValidationHandler] Validation section written: {result} (attempt {revision_count + 1})")


# Module-level instance for convenience
_handler: Optional[ValidationHandler] = None


def get_validation_handler(llm_client: Any = None) -> ValidationHandler:
    """Get or create a ValidationHandler instance."""
    global _handler
    if _handler is None or llm_client is not None:
        _handler = ValidationHandler(llm_client=llm_client)
    return _handler
