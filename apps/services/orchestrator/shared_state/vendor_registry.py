"""
orchestrator/shared_state/vendor_registry.py

Living Vendor Registry - Self-maintaining vendor knowledge base.

The system learns which vendors work through experience:
- Discovered vendors are added from Phase 1 intelligence gathering
- Success/failure rates are tracked per vendor
- Vendors that block us (like Walmart) are automatically flagged
- LLM can evaluate and categorize vendors

NO HARDCODED LISTS. The registry learns and adapts.

Persistence: panda_system_docs/schemas/vendor_registry.jsonl
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Storage
VENDOR_REGISTRY_FILE = Path("panda_system_docs/schemas/vendor_registry.jsonl")
VENDOR_REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)


# Recovery strategies the system can try before giving up
RECOVERY_STRATEGIES = [
    "recalibrate_selectors",     # Re-run LLM calibration for this site
    "increase_wait_time",        # Wait longer for page to load
    "use_stealth_mode",          # Enable anti-detection measures
    "try_different_url_pattern", # Try alternative URL patterns
    "use_mobile_viewport",       # Try mobile user-agent/viewport
]

# Thresholds for blocking
CONSECUTIVE_FAILURES_BEFORE_RECOVERY = 2   # Try recovery after 2 failures
CONSECUTIVE_FAILURES_BEFORE_BLOCK = 5      # Only block after 5 consecutive failures
QUARANTINE_HOURS = 24                       # Wait 24h before retrying blocked vendor


@dataclass
class VendorRecord:
    """
    A vendor learned by the system.

    The system discovers and evaluates vendors over time.
    This is NOT hardcoded - it's learned from experience.

    Recovery Philosophy:
    - Don't give up on first failure
    - Try recovery strategies before marking as blocked
    - Only block after exhausting all options
    - Quarantine blocked vendors, don't permanently ban them
    """
    # Identity
    domain: str                              # "bestbuy.com"
    name: str = ""                           # "Best Buy" (LLM-extracted)

    # Categories (LLM-assigned, can have multiple)
    categories: List[str] = field(default_factory=list)  # ["electronics", "computers"]
    vendor_type: str = ""                    # "retailer", "marketplace", "manufacturer"

    # Discovery
    discovered_at: str = ""                  # When first seen
    discovered_via: str = ""                 # "google_search", "phase1_intelligence", "user_query"
    discovery_query: str = ""                # What query led to discovery

    # Health tracking
    total_visits: int = 0
    successful_extractions: int = 0
    failed_extractions: int = 0
    last_visit: Optional[str] = None
    last_success: Optional[str] = None
    last_failure: Optional[str] = None

    # Recovery tracking - try to fix before giving up
    consecutive_failures: int = 0            # Failures in a row (reset on success)
    recovery_strategies_tried: List[str] = field(default_factory=list)  # What we've tried
    last_recovery_strategy: str = ""         # Most recent recovery attempt
    needs_recovery: bool = False             # Flag: should try recovery on next visit

    # Block detection - only after exhausting recovery
    is_blocked: bool = False                 # True if site blocks headless browsers
    block_detected_at: Optional[str] = None
    block_type: str = ""                     # "captcha", "redirect", "403", "bot_detection"
    quarantine_until: Optional[str] = None   # Don't retry until this time

    # Quality signals
    has_json_ld: bool = False                # Site has structured data
    has_good_selectors: bool = False         # Calibration found good selectors
    avg_extraction_time_ms: float = 0        # Average extraction time

    # LLM evaluation
    llm_quality_score: float = 0.0           # 0-1, LLM's assessment of vendor quality
    llm_notes: str = ""                      # LLM's notes about this vendor

    def __post_init__(self):
        if not self.discovered_at:
            self.discovered_at = datetime.now(timezone.utc).isoformat()
        if not self.categories:
            self.categories = []
        if not self.recovery_strategies_tried:
            self.recovery_strategies_tried = []

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        total = self.successful_extractions + self.failed_extractions
        if total == 0:
            return 0.0
        return self.successful_extractions / total

    @property
    def is_in_quarantine(self) -> bool:
        """Check if vendor is currently in quarantine (temporary block)."""
        if not self.quarantine_until:
            return False
        try:
            quarantine_end = datetime.fromisoformat(self.quarantine_until.replace('Z', '+00:00'))
            return datetime.now(timezone.utc) < quarantine_end
        except Exception:
            return False

    @property
    def is_usable(self) -> bool:
        """Check if vendor is usable (not blocked/quarantined, reasonable success rate)."""
        # Check quarantine first - temporary block expires
        if self.is_in_quarantine:
            return False

        # If was blocked but quarantine expired, give another chance
        if self.is_blocked and not self.is_in_quarantine:
            # Auto-clear block after quarantine expires
            self.is_blocked = False
            self.consecutive_failures = 0
            self.recovery_strategies_tried = []
            logger.info(f"[VendorRegistry] Quarantine expired for {self.domain}, giving another chance")

        # New vendors get a chance
        if self.total_visits < 3:
            return True
        # Need at least 30% success rate after 3 visits
        return self.success_rate >= 0.3

    @property
    def next_recovery_strategy(self) -> Optional[str]:
        """Get the next recovery strategy to try."""
        for strategy in RECOVERY_STRATEGIES:
            if strategy not in self.recovery_strategies_tried:
                return strategy
        return None  # All strategies exhausted

    @property
    def is_reliable(self) -> bool:
        """Check if vendor is reliable (proven track record)."""
        if self.is_blocked:
            return False
        if self.total_visits < 5:
            return False
        return self.success_rate >= 0.7

    def record_visit(self, success: bool, extraction_time_ms: float = 0) -> Optional[str]:
        """
        Record a visit to this vendor.

        Returns:
            Recovery strategy to try if failure triggered recovery, None otherwise
        """
        now = datetime.now(timezone.utc).isoformat()
        self.total_visits += 1
        self.last_visit = now

        if success:
            self.successful_extractions += 1
            self.last_success = now
            # SUCCESS: Reset failure tracking
            self.consecutive_failures = 0
            self.needs_recovery = False
            # Clear recovery history on success - strategies worked!
            if self.recovery_strategies_tried:
                logger.info(f"[VendorRegistry] {self.domain} recovered with: {self.last_recovery_strategy}")
                self.recovery_strategies_tried = []
                self.last_recovery_strategy = ""
            return None
        else:
            self.failed_extractions += 1
            self.last_failure = now
            self.consecutive_failures += 1

            # Check if we should try recovery
            if self.consecutive_failures >= CONSECUTIVE_FAILURES_BEFORE_RECOVERY:
                next_strategy = self.next_recovery_strategy
                if next_strategy:
                    self.needs_recovery = True
                    logger.info(
                        f"[VendorRegistry] {self.domain} has {self.consecutive_failures} consecutive failures. "
                        f"Suggesting recovery: {next_strategy}"
                    )
                    return next_strategy

            # Update avg extraction time
            if extraction_time_ms > 0:
                if self.avg_extraction_time_ms == 0:
                    self.avg_extraction_time_ms = extraction_time_ms
                else:
                    self.avg_extraction_time_ms = (
                        0.8 * self.avg_extraction_time_ms + 0.2 * extraction_time_ms
                    )
            return None

    def record_recovery_attempt(self, strategy: str, success: bool) -> None:
        """Record that a recovery strategy was attempted."""
        self.recovery_strategies_tried.append(strategy)
        self.last_recovery_strategy = strategy
        if success:
            self.needs_recovery = False
            self.consecutive_failures = 0
            logger.info(f"[VendorRegistry] {self.domain} recovery succeeded with: {strategy}")
        else:
            logger.warning(f"[VendorRegistry] {self.domain} recovery failed with: {strategy}")

    def mark_blocked(self, block_type: str = "bot_detection") -> bool:
        """
        Try to mark this vendor as blocked - but only if we've exhausted recovery options.

        Returns:
            True if actually blocked, False if should try recovery instead
        """
        # First, check if we have recovery options left
        if self.consecutive_failures < CONSECUTIVE_FAILURES_BEFORE_BLOCK:
            next_strategy = self.next_recovery_strategy
            if next_strategy:
                self.needs_recovery = True
                logger.info(
                    f"[VendorRegistry] {self.domain} block requested but recovery available: {next_strategy}. "
                    f"Consecutive failures: {self.consecutive_failures}/{CONSECUTIVE_FAILURES_BEFORE_BLOCK}"
                )
                return False  # Don't block yet, try recovery

        # All recovery options exhausted OR too many consecutive failures
        self.is_blocked = True
        self.block_detected_at = datetime.now(timezone.utc).isoformat()
        self.block_type = block_type
        # Set quarantine - will auto-retry after period expires
        quarantine_end = datetime.now(timezone.utc) + timedelta(hours=QUARANTINE_HOURS)
        self.quarantine_until = quarantine_end.isoformat()
        logger.warning(
            f"[VendorRegistry] Blocked {self.domain}: {block_type}. "
            f"Quarantine until {self.quarantine_until}. "
            f"Tried strategies: {self.recovery_strategies_tried}"
        )
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VendorRecord:
        """Create from dictionary."""
        # Handle missing fields gracefully
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


class VendorRegistry:
    """
    Living registry of vendors learned by the system.

    Key principles:
    - NO hardcoded lists - everything is learned
    - Persists to disk - survives restarts
    - Self-healing - bad vendors get deprioritized/removed
    - LLM-evaluated - quality assessments are made by LLM
    """

    def __init__(self, registry_file: Path = None):
        self.registry_file = registry_file or VENDOR_REGISTRY_FILE
        self._vendors: Dict[str, VendorRecord] = {}
        self._loaded = False
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        """Lazy-load vendors from disk."""
        if self._loaded:
            return

        with self._lock:
            if self._loaded:
                return

            if self.registry_file.exists():
                try:
                    with open(self.registry_file, 'r') as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                data = json.loads(line)
                                vendor = VendorRecord.from_dict(data)
                                self._vendors[vendor.domain] = vendor
                            except (json.JSONDecodeError, TypeError) as e:
                                logger.warning(f"[VendorRegistry] Failed to parse: {e}")

                    logger.info(f"[VendorRegistry] Loaded {len(self._vendors)} vendors")
                except Exception as e:
                    logger.error(f"[VendorRegistry] Failed to load: {e}")

            self._loaded = True

    def _save_all(self) -> None:
        """Save all vendors to disk."""
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(self.registry_file, 'w') as f:
                for vendor in self._vendors.values():
                    f.write(json.dumps(vendor.to_dict()) + '\n')
            logger.debug(f"[VendorRegistry] Saved {len(self._vendors)} vendors")
        except Exception as e:
            logger.error(f"[VendorRegistry] Failed to save: {e}")

    def _normalize_domain(self, domain: str) -> str:
        """Normalize domain name."""
        domain = domain.lower().strip()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path.split('/')[0]
            return self._normalize_domain(domain)
        except Exception:
            return url

    def get(self, domain: str) -> Optional[VendorRecord]:
        """Get vendor by domain."""
        self._ensure_loaded()
        domain = self._normalize_domain(domain)
        return self._vendors.get(domain)

    def get_for_url(self, url: str) -> Optional[VendorRecord]:
        """Get vendor for a URL."""
        domain = self._extract_domain(url)
        return self.get(domain)

    def add_or_update(
        self,
        domain: str,
        name: str = "",
        categories: List[str] = None,
        vendor_type: str = "",
        discovered_via: str = "",
        discovery_query: str = ""
    ) -> VendorRecord:
        """
        Add a new vendor or update existing.

        Called when:
        - Phase 1 intelligence discovers a vendor
        - Google search returns a new vendor URL
        - User explicitly mentions a vendor
        """
        self._ensure_loaded()
        domain = self._normalize_domain(domain)

        with self._lock:
            if domain in self._vendors:
                vendor = self._vendors[domain]
                # Update fields if provided
                if name and not vendor.name:
                    vendor.name = name
                if categories:
                    # Merge categories
                    vendor.categories = list(set(vendor.categories + categories))
                if vendor_type and not vendor.vendor_type:
                    vendor.vendor_type = vendor_type
            else:
                # Create new vendor
                vendor = VendorRecord(
                    domain=domain,
                    name=name or domain.split('.')[0].title(),
                    categories=categories or [],
                    vendor_type=vendor_type,
                    discovered_via=discovered_via,
                    discovery_query=discovery_query
                )
                self._vendors[domain] = vendor
                logger.info(f"[VendorRegistry] Discovered new vendor: {domain} via {discovered_via}")

            self._save_all()
            return vendor

    def record_visit(
        self,
        domain: str,
        success: bool,
        extraction_time_ms: float = 0,
        blocked: bool = False,
        block_type: str = ""
    ) -> Optional[str]:
        """
        Record a visit result for a vendor.

        Called after each extraction attempt.

        Returns:
            Recovery strategy to try if failure triggered recovery, None otherwise.
            Caller should attempt the suggested recovery before the next visit.
        """
        self._ensure_loaded()
        domain = self._normalize_domain(domain)

        with self._lock:
            if domain not in self._vendors:
                # Auto-create if not exists
                self._vendors[domain] = VendorRecord(
                    domain=domain,
                    discovered_via="extraction_attempt"
                )

            vendor = self._vendors[domain]
            recovery_suggestion = None

            if blocked:
                # Try to mark as blocked - may return False if recovery available
                actually_blocked = vendor.mark_blocked(block_type)
                if not actually_blocked:
                    # Recovery available - get the suggested strategy
                    recovery_suggestion = vendor.next_recovery_strategy
            else:
                # Record normal visit - may return recovery suggestion on failure
                recovery_suggestion = vendor.record_visit(success, extraction_time_ms)

            self._save_all()
            return recovery_suggestion

    def record_recovery_attempt(
        self,
        domain: str,
        strategy: str,
        success: bool
    ) -> None:
        """Record that a recovery strategy was attempted for a vendor."""
        self._ensure_loaded()
        domain = self._normalize_domain(domain)

        with self._lock:
            vendor = self._vendors.get(domain)
            if vendor:
                vendor.record_recovery_attempt(strategy, success)
                self._save_all()

    def get_vendors_needing_recovery(self) -> List[VendorRecord]:
        """Get all vendors that need recovery attempts."""
        self._ensure_loaded()
        return [v for v in self._vendors.values() if v.needs_recovery]

    def is_blocked(self, domain: str) -> bool:
        """Check if a vendor is blocked."""
        vendor = self.get(domain)
        return vendor.is_blocked if vendor else False

    def is_usable(self, domain: str) -> bool:
        """Check if a vendor is usable (not blocked, reasonable success)."""
        vendor = self.get(domain)
        if vendor is None:
            return True  # Unknown vendors get a chance
        return vendor.is_usable

    def get_usable_vendors(
        self,
        category: str = None,
        limit: int = 10,
        min_success_rate: float = 0.0
    ) -> List[VendorRecord]:
        """
        Get usable vendors, optionally filtered by category.

        Returns vendors sorted by reliability (success rate * total visits).
        """
        self._ensure_loaded()

        vendors = []
        for vendor in self._vendors.values():
            if not vendor.is_usable:
                continue
            if vendor.success_rate < min_success_rate:
                continue
            if category and category not in vendor.categories:
                continue
            vendors.append(vendor)

        # Sort by reliability score (success rate weighted by experience)
        def reliability_score(v: VendorRecord) -> float:
            # More visits = more confidence in the success rate
            confidence = min(v.total_visits / 10, 1.0)
            return v.success_rate * confidence + (1 - confidence) * 0.5

        vendors.sort(key=reliability_score, reverse=True)
        return vendors[:limit]

    def get_blocked_vendors(self) -> List[VendorRecord]:
        """Get all blocked vendors."""
        self._ensure_loaded()
        return [v for v in self._vendors.values() if v.is_blocked]

    def get_reliable_vendors(self, category: str = None) -> List[VendorRecord]:
        """Get proven reliable vendors."""
        self._ensure_loaded()
        reliable = [v for v in self._vendors.values() if v.is_reliable]
        if category:
            reliable = [v for v in reliable if category in v.categories]
        return sorted(reliable, key=lambda v: v.success_rate, reverse=True)

    def get_all(self) -> List[VendorRecord]:
        """Get all vendors."""
        self._ensure_loaded()
        return list(self._vendors.values())

    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        self._ensure_loaded()

        vendors = list(self._vendors.values())
        if not vendors:
            return {
                "total_vendors": 0,
                "usable_vendors": 0,
                "blocked_vendors": 0,
                "reliable_vendors": 0,
                "categories": []
            }

        # Collect all categories
        all_categories: Set[str] = set()
        for v in vendors:
            all_categories.update(v.categories)

        return {
            "total_vendors": len(vendors),
            "usable_vendors": sum(1 for v in vendors if v.is_usable),
            "blocked_vendors": sum(1 for v in vendors if v.is_blocked),
            "reliable_vendors": sum(1 for v in vendors if v.is_reliable),
            "categories": list(all_categories),
            "total_visits": sum(v.total_visits for v in vendors),
            "avg_success_rate": (
                sum(v.success_rate for v in vendors if v.total_visits > 0) /
                max(1, sum(1 for v in vendors if v.total_visits > 0))
            )
        }

    def clear_blocked_status(self, domain: str) -> bool:
        """Clear blocked status for a vendor (for retry)."""
        vendor = self.get(domain)
        if vendor and vendor.is_blocked:
            with self._lock:
                vendor.is_blocked = False
                vendor.block_detected_at = None
                vendor.block_type = ""
                self._save_all()
                logger.info(f"[VendorRegistry] Cleared blocked status for {domain}")
                return True
        return False

    def delete(self, domain: str) -> bool:
        """Delete a vendor from registry."""
        self._ensure_loaded()
        domain = self._normalize_domain(domain)

        with self._lock:
            if domain in self._vendors:
                del self._vendors[domain]
                self._save_all()
                logger.info(f"[VendorRegistry] Deleted vendor: {domain}")
                return True
        return False


# Global instance with thread-safe initialization
_registry: Optional[VendorRegistry] = None
_registry_lock = threading.Lock()


def get_vendor_registry() -> VendorRegistry:
    """Get global vendor registry instance (thread-safe)."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = VendorRegistry()
    return _registry


def reset_registry() -> None:
    """Reset global registry (for testing)."""
    global _registry
    with _registry_lock:
        _registry = None
