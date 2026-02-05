"""
orchestrator/shared_state/site_schema_registry.py

Site Schema Registry for storing learned extraction patterns per domain.

This implements the calibration-based extraction system where:
1. First visit to a site: Learn and store extraction selectors
2. Subsequent visits: Use cached selectors for fast, reliable extraction
3. Schema drift: Detect failures and trigger re-calibration

Similar pattern to lesson_store.py but for site-specific extraction knowledge.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Default storage location
SCHEMA_DIR = Path("panda_system_docs/schemas")
SCHEMA_FILE = SCHEMA_DIR / "site_schemas.jsonl"


@dataclass
class SiteSchema:
    """
    Learned extraction schema for a specific domain + page type.

    Contains CSS selectors, visual hints, and navigation patterns
    discovered during calibration.
    """

    # Identity
    domain: str                              # "bestbuy.com"
    page_type: str                           # "listing" | "pdp" | "search_results" | "article"

    # Versioning
    version: int = 1                         # Increment on re-calibration
    created_at: str = ""                     # ISO timestamp
    updated_at: str = ""                     # ISO timestamp

    # DOM Selectors (learned from calibration)
    product_card_selector: Optional[str] = None      # ".sku-item", "[data-sku-id]"
    product_link_selector: Optional[str] = None      # "a.sku-title", ".product-title a"
    price_selector: Optional[str] = None             # ".priceView-customer-price span"
    title_selector: Optional[str] = None             # "h4.sku-header", ".product-title"
    image_selector: Optional[str] = None             # "img.product-image"

    # Additional selectors for specific sites
    json_ld_available: bool = False                  # Site has JSON-LD structured data

    # Visual Hints (for OCR fallback)
    product_area_y_start: Optional[int] = None       # Y pixel where products start
    product_area_y_end: Optional[int] = None         # Y pixel where products end
    filter_area_x_end: Optional[int] = None          # X pixel where left filter ends

    # Navigation
    pagination_method: Optional[str] = None          # "click_next" | "scroll_infinite" | "url_param"
    next_button_selector: Optional[str] = None       # ".pagination-next", "a[aria-label='Next']"

    # Anti-patterns (elements to avoid clicking)
    filter_selectors: List[str] = field(default_factory=list)  # Selectors for filter links
    nav_selectors: List[str] = field(default_factory=list)     # Selectors for nav links

    # Statistics
    total_uses: int = 0
    successful_extractions: int = 0
    failed_extractions: int = 0
    consecutive_failures: int = 0
    last_success: Optional[str] = None
    last_failure: Optional[str] = None

    # Method success tracking
    method_stats: Dict[str, Dict[str, int]] = field(default_factory=dict)
    # e.g., {"dom_schema": {"success": 50, "fail": 2}, "vision": {"success": 10, "fail": 5}}

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at
        if not self.method_stats:
            self.method_stats = {}

    @property
    def success_rate(self) -> float:
        """Calculate overall success rate."""
        total = self.successful_extractions + self.failed_extractions
        if total == 0:
            return 0.0
        return self.successful_extractions / total

    @property
    def needs_recalibration(self) -> bool:
        """Check if schema should be recalibrated."""
        # Recalibrate after 1 consecutive failure - fail fast, recalibrate quickly
        if self.consecutive_failures >= 1:
            return True
        # Recalibrate if overall success rate drops below 50% (with enough data)
        total = self.successful_extractions + self.failed_extractions
        if total >= 5 and self.success_rate < 0.5:
            return True
        # Recalibrate if "schema" method specifically is failing
        # This catches cases where vision is succeeding but the schema selector is broken
        schema_stats = self.method_stats.get("schema", {})
        schema_success = schema_stats.get("success", 0)
        schema_fail = schema_stats.get("fail", 0)
        if schema_fail >= 1 and schema_success == 0:
            # Schema method has 0% success rate - recalibrate immediately
            return True
        return False

    @property
    def is_reliable(self) -> bool:
        """Check if schema has proven reliable."""
        total = self.successful_extractions + self.failed_extractions
        return total >= 5 and self.success_rate >= 0.8

    def record_success(self, method: str = "dom_schema") -> None:
        """Record a successful extraction."""
        self.total_uses += 1
        self.successful_extractions += 1
        self.consecutive_failures = 0
        self.last_success = datetime.now(timezone.utc).isoformat()
        self.updated_at = self.last_success

        # Update method stats
        if method not in self.method_stats:
            self.method_stats[method] = {"success": 0, "fail": 0}
        self.method_stats[method]["success"] += 1

    def record_failure(self, method: str = "dom_schema") -> None:
        """Record a failed extraction."""
        self.total_uses += 1
        self.failed_extractions += 1
        self.consecutive_failures += 1
        self.last_failure = datetime.now(timezone.utc).isoformat()
        self.updated_at = self.last_failure

        # Update method stats
        if method not in self.method_stats:
            self.method_stats[method] = {"success": 0, "fail": 0}
        self.method_stats[method]["fail"] += 1

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SiteSchema:
        """Create from dictionary."""
        # Handle missing fields gracefully
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)

    def get_key(self) -> str:
        """Get unique key for this schema."""
        return f"{self.domain}:{self.page_type}"


class SiteSchemaRegistry:
    """
    Registry for storing and retrieving site schemas.

    Provides:
    - Schema storage/retrieval by domain + page_type
    - Automatic persistence to JSONL file
    - Statistics tracking
    - Staleness detection
    """

    def __init__(self, schema_dir: Path = None):
        self.schema_dir = schema_dir or SCHEMA_DIR
        self.schema_file = self.schema_dir / "site_schemas.jsonl"
        self._schemas: Dict[str, SiteSchema] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """Lazy-load schemas from disk."""
        if self._loaded:
            return

        self.schema_dir.mkdir(parents=True, exist_ok=True)

        if self.schema_file.exists():
            try:
                with open(self.schema_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            schema = SiteSchema.from_dict(data)
                            self._schemas[schema.get_key()] = schema
                        except (json.JSONDecodeError, TypeError) as e:
                            logger.warning(f"[SchemaRegistry] Failed to parse schema line: {e}")

                logger.info(f"[SchemaRegistry] Loaded {len(self._schemas)} schemas from {self.schema_file}")
            except Exception as e:
                logger.error(f"[SchemaRegistry] Failed to load schemas: {e}")

        self._loaded = True

    def _save_all(self) -> None:
        """Save all schemas to disk using atomic write (temp file + rename)."""
        import tempfile
        import shutil

        self.schema_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Write to temp file first, then atomic rename
            # This prevents corruption if process crashes mid-write
            with tempfile.NamedTemporaryFile(
                mode='w',
                dir=self.schema_dir,
                suffix='.tmp',
                delete=False
            ) as f:
                for schema in self._schemas.values():
                    f.write(json.dumps(schema.to_dict()) + '\n')
                temp_path = f.name

            # Atomic rename (on POSIX systems)
            shutil.move(temp_path, self.schema_file)

            logger.debug(f"[SchemaRegistry] Saved {len(self._schemas)} schemas to {self.schema_file}")
        except Exception as e:
            logger.error(f"[SchemaRegistry] Failed to save schemas: {e}")
            # Clean up temp file if it exists
            try:
                if 'temp_path' in locals():
                    os.unlink(temp_path)
            except:
                pass

    def get(self, domain: str, page_type: str) -> Optional[SiteSchema]:
        """
        Get schema for a domain + page type.

        Args:
            domain: Domain name (e.g., "bestbuy.com")
            page_type: Page type (e.g., "listing", "pdp", "search_results")

        Returns:
            SiteSchema if found, None otherwise
        """
        self._ensure_loaded()

        # Normalize domain (remove www.)
        domain = self._normalize_domain(domain)
        key = f"{domain}:{page_type}"

        schema = self._schemas.get(key)

        if schema:
            logger.debug(f"[SchemaRegistry] Found schema for {key} (v{schema.version}, {schema.success_rate:.0%} success)")
        else:
            logger.debug(f"[SchemaRegistry] No schema found for {key}")

        return schema

    def get_for_url(self, url: str, page_type: str) -> Optional[SiteSchema]:
        """
        Get schema for a URL.

        Args:
            url: Full URL
            page_type: Page type

        Returns:
            SiteSchema if found, None otherwise
        """
        domain = self._extract_domain(url)
        return self.get(domain, page_type)

    def save(self, schema: SiteSchema) -> None:
        """
        Save or update a schema.

        Args:
            schema: Schema to save
        """
        self._ensure_loaded()

        key = schema.get_key()
        existing = self._schemas.get(key)

        if existing:
            # Update version on re-calibration
            if schema.version <= existing.version:
                schema.version = existing.version + 1
            logger.info(f"[SchemaRegistry] Updating schema for {key} (v{existing.version} → v{schema.version})")
        else:
            logger.info(f"[SchemaRegistry] Saving new schema for {key}")

        schema.updated_at = datetime.now(timezone.utc).isoformat()
        self._schemas[key] = schema
        self._save_all()

    def record_extraction(
        self,
        domain: str,
        page_type: str,
        success: bool,
        method: str = "dom_schema"
    ) -> None:
        """
        Record an extraction attempt result.

        Args:
            domain: Domain name
            page_type: Page type
            success: Whether extraction succeeded
            method: Extraction method used
        """
        self._ensure_loaded()

        domain = self._normalize_domain(domain)
        key = f"{domain}:{page_type}"
        schema = self._schemas.get(key)

        if not schema:
            logger.warning(f"[SchemaRegistry] Cannot record stats - no schema for {key}")
            return

        if success:
            schema.record_success(method)
            logger.debug(f"[SchemaRegistry] Recorded success for {key} via {method}")
        else:
            schema.record_failure(method)
            logger.debug(f"[SchemaRegistry] Recorded failure for {key} via {method}")

            if schema.needs_recalibration:
                logger.warning(f"[SchemaRegistry] Schema {key} needs recalibration (consecutive_failures={schema.consecutive_failures})")

        self._save_all()

    def needs_calibration(self, domain: str, page_type: str) -> bool:
        """
        Check if a domain + page_type needs (re)calibration.

        Returns True if:
        - No schema exists
        - Existing schema has too many failures
        """
        self._ensure_loaded()

        domain = self._normalize_domain(domain)
        key = f"{domain}:{page_type}"
        schema = self._schemas.get(key)

        if not schema:
            return True

        return schema.needs_recalibration

    def mark_stale(self, domain: str, page_type: str) -> None:
        """Mark a schema as needing recalibration."""
        self._ensure_loaded()

        domain = self._normalize_domain(domain)
        key = f"{domain}:{page_type}"
        schema = self._schemas.get(key)

        if schema:
            # Force recalibration by setting consecutive failures high
            schema.consecutive_failures = 10
            schema.updated_at = datetime.now(timezone.utc).isoformat()
            self._save_all()
            logger.info(f"[SchemaRegistry] Marked {key} as stale")

    def delete(self, domain: str, page_type: str) -> bool:
        """Delete a schema."""
        self._ensure_loaded()

        domain = self._normalize_domain(domain)
        key = f"{domain}:{page_type}"

        if key in self._schemas:
            del self._schemas[key]
            self._save_all()
            logger.info(f"[SchemaRegistry] Deleted schema for {key}")
            return True

        return False

    def delete_schema(self, domain: str) -> bool:
        """
        Delete all schemas for a domain.

        Used by recovery to force recalibration on next visit.

        Args:
            domain: Domain to delete all schemas for

        Returns:
            True if any schemas deleted, False if none found
        """
        self._ensure_loaded()
        domain = self._normalize_domain(domain)

        # Find all keys for this domain
        keys_to_delete = [k for k in self._schemas.keys() if k.startswith(f"{domain}:")]

        if not keys_to_delete:
            return False

        for key in keys_to_delete:
            del self._schemas[key]

        self._save_all()
        logger.info(f"[SchemaRegistry] Deleted {len(keys_to_delete)} schemas for {domain}")
        return True

    def list_all(self) -> List[SiteSchema]:
        """List all schemas."""
        self._ensure_loaded()
        return list(self._schemas.values())

    def list_by_domain(self, domain: str) -> List[SiteSchema]:
        """List all schemas for a domain."""
        self._ensure_loaded()
        domain = self._normalize_domain(domain)
        return [s for s in self._schemas.values() if s.domain == domain]

    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        self._ensure_loaded()

        schemas = list(self._schemas.values())

        if not schemas:
            return {
                "total_schemas": 0,
                "total_domains": 0,
                "avg_success_rate": 0.0,
                "schemas_needing_recalibration": 0
            }

        domains = set(s.domain for s in schemas)
        success_rates = [s.success_rate for s in schemas if s.total_uses > 0]
        needing_recal = sum(1 for s in schemas if s.needs_recalibration)

        return {
            "total_schemas": len(schemas),
            "total_domains": len(domains),
            "avg_success_rate": sum(success_rates) / len(success_rates) if success_rates else 0.0,
            "schemas_needing_recalibration": needing_recal,
            "reliable_schemas": sum(1 for s in schemas if s.is_reliable),
            "total_extractions": sum(s.total_uses for s in schemas)
        }

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


# Global instance with thread-safe initialization
import threading
_registry: Optional[SiteSchemaRegistry] = None
_registry_lock = threading.Lock()


def get_schema_registry() -> SiteSchemaRegistry:
    """Get global schema registry instance (lazy-loaded, thread-safe)."""
    global _registry
    if _registry is None:
        with _registry_lock:
            # Double-check pattern for thread safety
            if _registry is None:
                _registry = SiteSchemaRegistry()
    return _registry


def reset_registry() -> None:
    """Reset global registry (for testing)."""
    global _registry
    with _registry_lock:
        _registry = None
