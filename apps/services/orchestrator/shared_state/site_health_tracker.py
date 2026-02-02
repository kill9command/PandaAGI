"""
orchestrator/shared_state/site_health_tracker.py

Site Health Tracker - Aggregate monitoring of extraction success rates.

Provides:
- Per-domain health summaries
- Identification of problematic sites
- Alerts/triggers for recalibration
- Historical success rate trends

Works with SiteSchemaRegistry but provides higher-level monitoring view.
"""

import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from apps.services.orchestrator.shared_state.site_schema_registry import (
    SiteSchemaRegistry,
    SiteSchema,
    get_schema_registry
)

logger = logging.getLogger(__name__)


@dataclass
class SiteHealth:
    """Health summary for a domain."""
    domain: str
    total_schemas: int                       # Number of page types with schemas
    total_extractions: int                   # Total extraction attempts
    successful_extractions: int              # Successful extractions
    failed_extractions: int                  # Failed extractions
    success_rate: float                      # Overall success rate
    last_success: Optional[str]              # ISO timestamp
    last_failure: Optional[str]              # ISO timestamp
    schemas_needing_recalibration: int       # Count of stale schemas
    reliable_schemas: int                    # Count of reliable schemas
    extraction_methods: Dict[str, int]       # Method usage counts

    @property
    def health_status(self) -> str:
        """Get health status category."""
        if self.total_extractions == 0:
            return "unknown"
        if self.success_rate >= 0.9:
            return "excellent"
        if self.success_rate >= 0.7:
            return "good"
        if self.success_rate >= 0.5:
            return "fair"
        return "poor"

    @property
    def needs_attention(self) -> bool:
        """Check if domain needs attention."""
        return (
            self.success_rate < 0.5 or
            self.schemas_needing_recalibration > 0
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = asdict(self)
        result["health_status"] = self.health_status
        result["needs_attention"] = self.needs_attention
        return result


class SiteHealthTracker:
    """
    Tracks and reports on site extraction health.

    Aggregates data from SiteSchemaRegistry to provide monitoring views.
    """

    def __init__(self, registry: SiteSchemaRegistry = None):
        self.registry = registry or get_schema_registry()

    def get_domain_health(self, domain: str) -> SiteHealth:
        """
        Get health summary for a specific domain.

        Args:
            domain: Domain name (e.g., "bestbuy.com")

        Returns:
            SiteHealth object
        """
        schemas = self.registry.list_by_domain(domain)

        if not schemas:
            return SiteHealth(
                domain=domain,
                total_schemas=0,
                total_extractions=0,
                successful_extractions=0,
                failed_extractions=0,
                success_rate=0.0,
                last_success=None,
                last_failure=None,
                schemas_needing_recalibration=0,
                reliable_schemas=0,
                extraction_methods={}
            )

        # Aggregate stats
        total_extractions = sum(s.total_uses for s in schemas)
        successful = sum(s.successful_extractions for s in schemas)
        failed = sum(s.failed_extractions for s in schemas)
        needing_recal = sum(1 for s in schemas if s.needs_recalibration)
        reliable = sum(1 for s in schemas if s.is_reliable)

        # Find latest timestamps
        successes = [s.last_success for s in schemas if s.last_success]
        failures = [s.last_failure for s in schemas if s.last_failure]
        last_success = max(successes) if successes else None
        last_failure = max(failures) if failures else None

        # Aggregate method stats
        method_counts: Dict[str, int] = {}
        for schema in schemas:
            for method, stats in schema.method_stats.items():
                if method not in method_counts:
                    method_counts[method] = 0
                method_counts[method] += stats.get("success", 0) + stats.get("fail", 0)

        success_rate = successful / total_extractions if total_extractions > 0 else 0.0

        return SiteHealth(
            domain=domain,
            total_schemas=len(schemas),
            total_extractions=total_extractions,
            successful_extractions=successful,
            failed_extractions=failed,
            success_rate=success_rate,
            last_success=last_success,
            last_failure=last_failure,
            schemas_needing_recalibration=needing_recal,
            reliable_schemas=reliable,
            extraction_methods=method_counts
        )

    def get_all_health(self) -> List[SiteHealth]:
        """Get health summaries for all domains."""
        schemas = self.registry.list_all()
        domains = set(s.domain for s in schemas)

        return [self.get_domain_health(domain) for domain in sorted(domains)]

    def get_problematic_sites(self, threshold: float = 0.5) -> List[SiteHealth]:
        """
        Get sites with success rate below threshold.

        Args:
            threshold: Minimum acceptable success rate

        Returns:
            List of SiteHealth for problematic sites
        """
        all_health = self.get_all_health()
        problematic = [
            h for h in all_health
            if h.total_extractions >= 5 and h.success_rate < threshold
        ]
        return sorted(problematic, key=lambda h: h.success_rate)

    def get_sites_needing_recalibration(self) -> List[str]:
        """Get list of domains that need recalibration."""
        all_health = self.get_all_health()
        return [h.domain for h in all_health if h.schemas_needing_recalibration > 0]

    def get_summary(self) -> Dict[str, Any]:
        """Get overall health summary."""
        all_health = self.get_all_health()

        if not all_health:
            return {
                "total_domains": 0,
                "total_extractions": 0,
                "overall_success_rate": 0.0,
                "sites_needing_attention": 0,
                "status": "no_data"
            }

        total_extractions = sum(h.total_extractions for h in all_health)
        total_successful = sum(h.successful_extractions for h in all_health)
        needs_attention = sum(1 for h in all_health if h.needs_attention)

        overall_rate = total_successful / total_extractions if total_extractions > 0 else 0.0

        # Determine overall status
        if overall_rate >= 0.8:
            status = "healthy"
        elif overall_rate >= 0.6:
            status = "degraded"
        else:
            status = "critical"

        return {
            "total_domains": len(all_health),
            "total_extractions": total_extractions,
            "overall_success_rate": overall_rate,
            "sites_needing_attention": needs_attention,
            "status": status,
            "excellent_sites": sum(1 for h in all_health if h.health_status == "excellent"),
            "good_sites": sum(1 for h in all_health if h.health_status == "good"),
            "fair_sites": sum(1 for h in all_health if h.health_status == "fair"),
            "poor_sites": sum(1 for h in all_health if h.health_status == "poor"),
        }

    def record_extraction(
        self,
        url: str,
        page_type: str,
        success: bool,
        method: str = "unknown"
    ) -> None:
        """
        Convenience method to record an extraction attempt.

        Delegates to SiteSchemaRegistry.record_extraction().

        Args:
            url: Full URL (domain will be extracted)
            page_type: Page type
            success: Whether extraction succeeded
            method: Extraction method used
        """
        from urllib.parse import urlparse

        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith("www."):
                domain = domain[4:]

            self.registry.record_extraction(domain, page_type, success, method)

            if not success:
                health = self.get_domain_health(domain)
                if health.needs_attention:
                    logger.warning(
                        f"[HealthTracker] Site {domain} needs attention: "
                        f"success_rate={health.success_rate:.0%}, "
                        f"recal_needed={health.schemas_needing_recalibration}"
                    )

        except Exception as e:
            logger.warning(f"[HealthTracker] Failed to record extraction: {e}")

    def print_report(self) -> str:
        """Generate a printable health report."""
        summary = self.get_summary()
        all_health = self.get_all_health()

        lines = [
            "=" * 60,
            "SITE EXTRACTION HEALTH REPORT",
            "=" * 60,
            f"Status: {summary['status'].upper()}",
            f"Total Domains: {summary['total_domains']}",
            f"Total Extractions: {summary['total_extractions']}",
            f"Overall Success Rate: {summary['overall_success_rate']:.1%}",
            f"Sites Needing Attention: {summary['sites_needing_attention']}",
            "",
            "-" * 60,
            "BY DOMAIN:",
            "-" * 60,
        ]

        for health in sorted(all_health, key=lambda h: h.success_rate):
            status_icon = {
                "excellent": "[OK]",
                "good": "[OK]",
                "fair": "[!!]",
                "poor": "[XX]",
                "unknown": "[??]"
            }.get(health.health_status, "[??]")

            lines.append(
                f"{status_icon} {health.domain:30} | "
                f"{health.success_rate:5.0%} success | "
                f"{health.total_extractions:4} total | "
                f"recal={health.schemas_needing_recalibration}"
            )

        lines.append("=" * 60)

        return "\n".join(lines)

    # ==================== SITE CONFIG FOR RECOVERY ====================
    # These configs store recovery settings per site (wait times, stealth mode, etc.)

    _site_configs: Dict[str, Dict[str, Any]] = {}

    def set_site_config(self, domain: str, key: str, value: Any) -> None:
        """
        Set a configuration value for a site.

        Used by recovery strategies to adjust behavior per-site.
        E.g., wait_multiplier, use_stealth, use_mobile, try_alt_urls

        Args:
            domain: Site domain
            key: Config key
            value: Config value
        """
        domain = domain.lower().strip()
        if domain.startswith("www."):
            domain = domain[4:]

        if domain not in self._site_configs:
            self._site_configs[domain] = {}

        self._site_configs[domain][key] = value
        logger.info(f"[HealthTracker] Set {domain}.{key} = {value}")

    def get_site_config(self, domain: str, key: str, default: Any = None) -> Any:
        """
        Get a configuration value for a site.

        Args:
            domain: Site domain
            key: Config key
            default: Default if not set

        Returns:
            Config value or default
        """
        domain = domain.lower().strip()
        if domain.startswith("www."):
            domain = domain[4:]

        return self._site_configs.get(domain, {}).get(key, default)

    def get_all_site_configs(self, domain: str) -> Dict[str, Any]:
        """Get all configs for a site."""
        domain = domain.lower().strip()
        if domain.startswith("www."):
            domain = domain[4:]

        return self._site_configs.get(domain, {}).copy()

    def clear_site_config(self, domain: str) -> None:
        """Clear all configs for a site."""
        domain = domain.lower().strip()
        if domain.startswith("www."):
            domain = domain[4:]

        if domain in self._site_configs:
            del self._site_configs[domain]
            logger.info(f"[HealthTracker] Cleared configs for {domain}")


# Global instance with thread-safe initialization
import threading
_tracker: Optional[SiteHealthTracker] = None
_tracker_lock = threading.Lock()


def get_health_tracker() -> SiteHealthTracker:
    """Get global health tracker instance (thread-safe)."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            # Double-check pattern for thread safety
            if _tracker is None:
                _tracker = SiteHealthTracker()
    return _tracker
