"""
Track product rejection patterns to improve future searches.

This module implements a global persistent tracker that learns from rejection
patterns across all sessions, enabling continuous improvement of search queries.

Usage:
    from apps.services.tool_server.rejection_tracker import get_rejection_tracker

    tracker = get_rejection_tracker()
    tracker.record_rejections(
        vendor="bestbuy.com",
        query="RTX 4060 laptop",
        rejections=[{"reason": "no dedicated GPU"}],
        total_products=10
    )

    # Get query refinements based on past rejections
    refinements = tracker.get_query_refinements("bestbuy.com", "RTX 4060 laptop")
    # → ["nvidia OR rtx OR geforce"] if >50% rejected for missing GPU
"""

import json
import logging
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# Global persistent storage location
TRACKER_PATH = Path("panda_system_docs/shared_state/rejection_patterns.json")


class RejectionTracker:
    """
    Track and learn from product rejection patterns.

    Records why products are rejected during viability filtering and uses
    this information to suggest query refinements for future searches.
    """

    def __init__(self, tracker_path: Path = TRACKER_PATH):
        """
        Initialize the rejection tracker.

        Args:
            tracker_path: Path to the persistent storage file
        """
        self.tracker_path = tracker_path
        self.patterns: Dict[str, Any] = self._load()

    def record_rejections(
        self,
        vendor: str,
        query: str,
        rejections: List[Dict],
        total_products: int
    ) -> None:
        """
        Record rejection patterns for a vendor/query combination.

        Args:
            vendor: Domain of the vendor (e.g., "bestbuy.com")
            query: The search query used
            rejections: List of rejection dicts with 'reason' field
            total_products: Total number of products evaluated
        """
        if not rejections:
            return

        key = f"{vendor}:{self._normalize_query(query)}"

        if key not in self.patterns:
            self.patterns[key] = {
                "rejection_reasons": {},
                "total_extractions": 0,
                "total_rejections": 0,
                "first_seen": None,
                "last_updated": None
            }

        from datetime import datetime
        now = datetime.utcnow().isoformat()

        entry = self.patterns[key]
        entry["total_extractions"] += total_products
        entry["total_rejections"] += len(rejections)
        entry["last_updated"] = now

        if not entry.get("first_seen"):
            entry["first_seen"] = now

        # Initialize rejection_reasons as dict if it's a defaultdict from old data
        if not isinstance(entry["rejection_reasons"], dict):
            entry["rejection_reasons"] = {}

        # Count rejection reasons by category
        for r in rejections:
            reason = self._categorize_reason(r.get("reason", "unknown"))
            if reason not in entry["rejection_reasons"]:
                entry["rejection_reasons"][reason] = 0
            entry["rejection_reasons"][reason] += 1

        logger.info(
            f"[RejectionTracker] Recorded {len(rejections)}/{total_products} rejections "
            f"for {vendor} (query: {query[:30]}...)"
        )

        self._save()

    def get_query_refinements(
        self,
        vendor: str,
        query: str
    ) -> List[str]:
        """
        Get suggested query refinements based on past rejections.

        Args:
            vendor: Domain of the vendor
            query: The search query

        Returns:
            List of query refinement strings to add
        """
        key = f"{vendor}:{self._normalize_query(query)}"
        entry = self.patterns.get(key, {})

        if not entry:
            return []

        refinements = []
        reasons = entry.get("rejection_reasons", {})
        total = entry.get("total_extractions", 1)

        if total < 5:
            # Not enough data to make refinements
            return []

        # If >50% rejected for "missing_gpu", add GPU keywords
        # Use simple keywords (no OR syntax) for retailer site compatibility
        if reasons.get("missing_gpu", 0) > total * 0.5:
            refinements.append("nvidia rtx gpu")
            logger.info(f"[RejectionTracker] Adding GPU refinement for {vendor}")

        # If >50% rejected for "wrong_category", add positive category terms
        # Avoid exclusion syntax (-) which doesn't work on all search engines
        if reasons.get("wrong_category", 0) > total * 0.5:
            refinements.append("laptop notebook")
            logger.info(f"[RejectionTracker] Adding category refinement for {vendor}")

        # If >50% rejected for "insufficient_ram", add RAM keywords
        if reasons.get("insufficient_ram", 0) > total * 0.5:
            refinements.append("16GB 32GB RAM")
            logger.info(f"[RejectionTracker] Adding RAM refinement for {vendor}")

        # If >50% rejected for "price_mismatch", this needs handling at URL level
        if reasons.get("price_mismatch", 0) > total * 0.5:
            logger.info(f"[RejectionTracker] High price mismatch rate for {vendor}")
            # Price refinements are handled via URL filters, not query

        # If >50% rejected for "out_of_stock", note it (but can't fix via query)
        if reasons.get("out_of_stock", 0) > total * 0.5:
            logger.info(f"[RejectionTracker] High out-of-stock rate for {vendor}")

        return refinements

    def get_vendor_stats(self, vendor: str, query: str = None) -> Dict[str, Any]:
        """
        Get rejection statistics for a vendor (optionally filtered by query).

        Args:
            vendor: Domain of the vendor
            query: Optional query to filter by

        Returns:
            Statistics dict with rejection rates by reason
        """
        stats = {
            "vendor": vendor,
            "total_extractions": 0,
            "total_rejections": 0,
            "rejection_rate": 0.0,
            "top_reasons": []
        }

        for key, entry in self.patterns.items():
            if not key.startswith(f"{vendor}:"):
                continue
            if query and not key.endswith(f":{self._normalize_query(query)}"):
                continue

            stats["total_extractions"] += entry.get("total_extractions", 0)
            stats["total_rejections"] += entry.get("total_rejections", 0)

        if stats["total_extractions"] > 0:
            stats["rejection_rate"] = stats["total_rejections"] / stats["total_extractions"]

        # Aggregate top reasons
        reason_counts = defaultdict(int)
        for key, entry in self.patterns.items():
            if not key.startswith(f"{vendor}:"):
                continue
            for reason, count in entry.get("rejection_reasons", {}).items():
                reason_counts[reason] += count

        stats["top_reasons"] = sorted(
            reason_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]

        return stats

    def _categorize_reason(self, reason: str) -> str:
        """
        Categorize rejection reason into actionable categories.

        Args:
            reason: The raw rejection reason string

        Returns:
            Categorized reason string
        """
        reason_lower = reason.lower()

        # GPU/Graphics related
        if any(x in reason_lower for x in ["gpu", "graphics", "nvidia", "rtx", "geforce", "radeon"]):
            return "missing_gpu"

        # Category mismatch
        if any(x in reason_lower for x in ["desktop", "tower", "not a laptop", "wrong type", "monitor"]):
            return "wrong_category"

        # Price related
        if any(x in reason_lower for x in ["price", "budget", "expensive", "cost"]):
            return "price_mismatch"

        # RAM related
        if any(x in reason_lower for x in ["ram", "memory"]):
            return "insufficient_ram"

        # Storage related
        if any(x in reason_lower for x in ["storage", "ssd", "hdd", "drive"]):
            return "insufficient_storage"

        # Availability
        if any(x in reason_lower for x in ["stock", "available", "sold out"]):
            return "out_of_stock"

        # Brand restrictions
        if any(x in reason_lower for x in ["brand", "manufacturer"]):
            return "brand_mismatch"

        return "other"

    def _normalize_query(self, query: str) -> str:
        """
        Normalize query for consistent key generation.

        Args:
            query: Raw query string

        Returns:
            Normalized query string
        """
        # Take first 5 words, sort them, join with underscore
        words = query.lower().split()[:5]
        return "_".join(sorted(words))

    def _load(self) -> Dict:
        """Load patterns from persistent storage."""
        try:
            if self.tracker_path.exists():
                data = json.loads(self.tracker_path.read_text())
                logger.debug(f"[RejectionTracker] Loaded {len(data)} patterns")
                return data
        except Exception as e:
            logger.warning(f"[RejectionTracker] Failed to load patterns: {e}")
        return {}

    def _save(self) -> None:
        """Save patterns to persistent storage."""
        try:
            self.tracker_path.parent.mkdir(parents=True, exist_ok=True)
            self.tracker_path.write_text(json.dumps(self.patterns, indent=2))
            logger.debug(f"[RejectionTracker] Saved {len(self.patterns)} patterns")
        except Exception as e:
            logger.warning(f"[RejectionTracker] Failed to save patterns: {e}")


# Global singleton instance with thread-safe initialization
import threading

_tracker: Optional[RejectionTracker] = None
_tracker_lock = threading.Lock()


def get_rejection_tracker() -> RejectionTracker:
    """
    Get the global rejection tracker instance (thread-safe).

    Uses double-checked locking pattern to ensure thread safety
    while minimizing lock contention after initialization.

    Returns:
        RejectionTracker singleton instance
    """
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            # Double-check after acquiring lock
            if _tracker is None:
                _tracker = RejectionTracker()
    return _tracker
