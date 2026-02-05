"""
Cache System Configuration

Centralized configuration for all cache layers and hybrid search.
All settings are environment-variable driven for easy tuning.
"""
import os
import hashlib
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# Cache Manager Gate Settings
# ============================================================================

CACHE_MANAGER_MULTI_GOAL_BYPASS = bool(
    int(os.getenv("CACHE_MANAGER_MULTI_GOAL_BYPASS", "1"))
)
"""Skip cache for multi-goal queries (e.g., 'find hamsters AND show care guides')"""

CACHE_MANAGER_INTENT_CONFIDENCE_THRESHOLD = float(
    os.getenv("CACHE_MANAGER_INTENT_THRESHOLD", "0.3")
)
"""Skip cache if intent confidence below this threshold"""

CACHE_MANAGER_LLM_VERIFY_MULTI_GOAL = bool(
    int(os.getenv("CACHE_MANAGER_LLM_VERIFY", "1"))
)
"""Use LLM to verify multi-goal detection (reduces false positives)"""

# ============================================================================
# Response Cache Settings (Layer 1 - User-Specific)
# ============================================================================

RESPONSE_CACHE_SIMILARITY_THRESHOLD = float(
    os.getenv("RESPONSE_CACHE_SIMILARITY", "0.85")
)
"""Minimum hybrid similarity for response cache match"""

RESPONSE_CACHE_ENABLED = bool(
    int(os.getenv("RESPONSE_CACHE_ENABLED", "0"))  # Disabled by default during development
)
"""Enable/disable response cache (set to 0 to disable during development)"""

RESPONSE_CACHE_USER_SCOPED = bool(
    int(os.getenv("RESPONSE_CACHE_USER_SCOPED", "1"))
)
"""Keep response cache user-specific (intentional design for token efficiency)"""

RESPONSE_CACHE_MAX_SIZE_GB = int(
    os.getenv("MAX_RESPONSE_CACHE_SIZE_GB", "5")
)
"""Maximum response cache size (LRU eviction when exceeded)"""

# ============================================================================
# Claims Cache Settings (Layer 2 - Shared, Domain-Scoped)
# ============================================================================

CLAIMS_CACHE_SIMILARITY_THRESHOLD = float(
    os.getenv("CLAIMS_CACHE_SIMILARITY", "0.50")
)
"""Minimum semantic similarity for claims match (START: 0.50, tune with A/B testing)"""

CLAIMS_KEYWORD_THRESHOLD = float(
    os.getenv("CLAIMS_KEYWORD_THRESHOLD", "0.1")
)
"""Minimum BM25 keyword score for claims match (prevents semantic drift)"""

CLAIMS_HIGH_COVERAGE_THRESHOLD = float(
    os.getenv("CLAIMS_HIGH_COVERAGE", "0.80")
)
"""Coverage score threshold to skip fresh search (0.8+ = high confidence)"""

# Domain-specific TTLs for claims (in hours)
DOMAIN_TTL_HOURS = {
    "pricing": 6,       # Prices change frequently
    "availability": 4,  # Stock changes very frequently
    "care": 720,        # Care guides stable (30 days)
    "breeding": 720,    # Breeding info stable (30 days)
    "products": 168,    # Product reviews moderately stable (7 days)
    "reviews": 168,     # Reviews moderately stable (7 days)
    "vendors": 168,     # Vendor info moderately stable (7 days)
    "health": 720,      # Health info stable (30 days)
    "default": 24       # Default TTL (1 day)
}

# ============================================================================
# Tool Cache Settings (Layer 3 - Shared, Query-Scoped)
# ============================================================================

TOOL_CACHE_MAX_SIZE_GB = int(
    os.getenv("MAX_TOOL_CACHE_SIZE_GB", "10")
)
"""Maximum tool cache size (LRU eviction when exceeded)"""

# Tool-specific TTLs (in hours)
TOOL_TTL_HOURS = {
    # Search & Research Tools (moderate freshness)
    "research.orchestrate": 12,
    "research_mcp.orchestrate": 12,
    "serpapi.search": 12,

    # Commerce Tools (vendor info is stable, prices updated via freshness checks)
    "commerce.search_offers": 168,  # 7 days - vendor/breeder listings are stable
    "purchasing.lookup": 168,  # 7 days - vendor discovery is stable

    # Web Scraping (stable content)
    "playwright.fetch": 24,
    "playwright.discover": 24,

    # Internal Tools (very stable)
    "doc.search": 168,  # 7 days
    "file.read": 72,    # 3 days

    # Memory Tools (never cache - user-specific)
    "memory.query": 0,
    "memory.create": 0,

    # Spreadsheet Tools
    "docs.read_spreadsheet": 24,
    "docs.write_spreadsheet": 0,  # Never cache writes

    # Default
    "default": 24
}

# ============================================================================
# Hybrid Search Settings
# ============================================================================

HYBRID_SEARCH_EMBEDDING_WEIGHT = float(
    os.getenv("HYBRID_EMBEDDING_WEIGHT", "0.7")
)
"""Embedding weight in hybrid search (0.7 = 70% semantic, 30% keyword)

Tuning guidance:
- High false negatives → Decrease weight (favor keyword recall)
- High false positives → Increase weight (favor semantic precision)
"""

HYBRID_SEARCH_DOMAIN_FILTER = bool(
    int(os.getenv("HYBRID_DOMAIN_FILTER", "1"))
)
"""Enable domain filtering in hybrid search (prevent cross-domain contamination)"""

# ============================================================================
# Quality Thresholds
# ============================================================================

QUALITY_MIN_FOR_CACHE = float(
    os.getenv("QUALITY_MIN_FOR_CACHE", "0.60")
)
"""Minimum quality score to cache response (0.60 = poor but acceptable)"""

QUALITY_SCORING_ASYNC = bool(
    int(os.getenv("QUALITY_SCORING_ASYNC", "1"))
)
"""Run quality scoring in background (don't block user response)"""

# ============================================================================
# A/B Testing Configuration
# ============================================================================

CACHE_AB_TEST_ENABLED = bool(
    int(os.getenv("CACHE_AB_TEST", "0"))
)
"""Enable A/B testing for similarity thresholds"""

CACHE_AB_TEST_VARIANTS = {
    "control": 0.50,    # Baseline (current)
    "variant_a": 0.55,  # Slightly stricter
    "variant_b": 0.60,  # Moderately stricter
    "variant_c": 0.65,  # Original v2.0 proposal
}


def get_similarity_threshold(session_id: str) -> float:
    """
    Get similarity threshold for this session (A/B testing).

    If AB testing disabled, return control (0.50).
    Otherwise, assign variant based on session_id hash.
    """
    if not CACHE_AB_TEST_ENABLED:
        return CLAIMS_CACHE_SIMILARITY_THRESHOLD  # Control

    # Deterministic variant assignment
    variant_hash = int(hashlib.md5(session_id.encode()).hexdigest()[:8], 16)
    variant_index = variant_hash % len(CACHE_AB_TEST_VARIANTS)
    variant_name = list(CACHE_AB_TEST_VARIANTS.keys())[variant_index]
    threshold = CACHE_AB_TEST_VARIANTS[variant_name]

    logger.info(f"[AB-Test] session={session_id[:8]}, variant={variant_name}, threshold={threshold}")
    return threshold


def get_ttl_for_domain(domain: str, intent: str) -> int:
    """
    Get TTL for domain and intent combination.

    Transactional queries need fresher data than informational queries.
    """
    base_ttl = DOMAIN_TTL_HOURS.get(domain, DOMAIN_TTL_HOURS["default"])

    # Transactional queries need fresher data
    if intent == "transactional":
        return min(base_ttl, 6)  # Max 6 hours for purchasing

    return base_ttl


def get_tool_ttl(tool_name: str) -> int:
    """Get TTL for tool cache"""
    return TOOL_TTL_HOURS.get(tool_name, TOOL_TTL_HOURS["default"])


# ============================================================================
# Cache Storage Paths
# ============================================================================

import sys
from pathlib import Path

# Get project root
if hasattr(sys, '_MEIPASS'):
    # PyInstaller bundle
    PROJECT_ROOT = Path(sys._MEIPASS)
else:
    PROJECT_ROOT = Path(__file__).parent.parent.parent

CACHE_BASE_DIR = PROJECT_ROOT / "panda_system_docs" / "shared_state"

RESPONSE_CACHE_DIR = CACHE_BASE_DIR / "response_cache"
TOOL_CACHE_DIR = CACHE_BASE_DIR / "tool_cache"
CLAIMS_DB_PATH = CACHE_BASE_DIR / "claims.db"

# Create directories
RESPONSE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
TOOL_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# Logging Configuration
# ============================================================================

def log_cache_config():
    """Log current cache configuration (for debugging)"""
    logger.info("=" * 60)
    logger.info("[CacheConfig] Cache System Configuration")
    logger.info("=" * 60)
    logger.info(f"[CacheConfig] Response Cache Similarity: {RESPONSE_CACHE_SIMILARITY_THRESHOLD}")
    logger.info(f"[CacheConfig] Claims Cache Similarity: {CLAIMS_CACHE_SIMILARITY_THRESHOLD}")
    logger.info(f"[CacheConfig] Claims Keyword Threshold: {CLAIMS_KEYWORD_THRESHOLD}")
    logger.info(f"[CacheConfig] Hybrid Embedding Weight: {HYBRID_SEARCH_EMBEDDING_WEIGHT}")
    logger.info(f"[CacheConfig] Domain Filtering: {HYBRID_SEARCH_DOMAIN_FILTER}")
    logger.info(f"[CacheConfig] Multi-Goal Bypass: {CACHE_MANAGER_MULTI_GOAL_BYPASS}")
    logger.info(f"[CacheConfig] Intent Confidence Threshold: {CACHE_MANAGER_INTENT_CONFIDENCE_THRESHOLD}")
    logger.info(f"[CacheConfig] Quality Min for Cache: {QUALITY_MIN_FOR_CACHE}")
    logger.info(f"[CacheConfig] A/B Testing Enabled: {CACHE_AB_TEST_ENABLED}")
    logger.info(f"[CacheConfig] Response Cache Dir: {RESPONSE_CACHE_DIR}")
    logger.info(f"[CacheConfig] Tool Cache Dir: {TOOL_CACHE_DIR}")
    logger.info("=" * 60)


# ============================================================================
# Unified Cache Configuration System (Phase 1)
# ============================================================================

import json
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class CacheClassConfig:
    """Configuration for a cache class (short_lived, medium_term, long_term)."""
    ttl_seconds: int
    max_size_mb: int
    eviction_policy: str = "lru"
    compression_enabled: bool = False


@dataclass
class CacheConfig:
    """
    Unified cache configuration system.

    Loads from cache_config.json and supports environment variable overrides.
    Provides backward compatibility with existing configuration constants.
    """
    # Cache class configurations
    cache_classes: Dict[str, CacheClassConfig] = field(default_factory=dict)

    # Similarity thresholds per cache type
    similarity_thresholds: Dict[str, float] = field(default_factory=dict)

    # Eviction settings
    eviction_check_interval_seconds: int = 3600
    eviction_policy: str = "lru"

    # Hybrid search settings
    embedding_weight: float = 0.7
    keyword_weight: float = 0.3

    # Quality settings
    min_quality_for_cache: float = 0.3

    # Base directory
    cache_base_dir: str = "panda_system_docs/shared_state"

    # Feature flags
    cascade_enabled: bool = True
    compression_enabled: bool = False

    @classmethod
    def load_from_file(cls, config_path: Path) -> 'CacheConfig':
        """
        Load configuration from JSON file.

        Args:
            config_path: Path to cache_config.json

        Returns:
            CacheConfig instance
        """
        try:
            with open(config_path, 'r') as f:
                data = json.load(f)

            # Parse cache classes
            cache_classes = {}
            for class_name, class_config in data.get("cache_classes", {}).items():
                cache_classes[class_name] = CacheClassConfig(**class_config)

            return cls(
                cache_classes=cache_classes,
                similarity_thresholds=data.get("similarity_thresholds", {}),
                eviction_check_interval_seconds=data.get("eviction_check_interval_seconds", 3600),
                eviction_policy=data.get("eviction_policy", "lru"),
                embedding_weight=data.get("embedding_weight", 0.7),
                keyword_weight=data.get("keyword_weight", 0.3),
                min_quality_for_cache=data.get("min_quality_for_cache", 0.3),
                cache_base_dir=data.get("cache_base_dir", "panda_system_docs/shared_state"),
                cascade_enabled=data.get("cascade_enabled", True),
                compression_enabled=data.get("compression_enabled", False)
            )
        except Exception as e:
            logger.error(f"[CacheConfig] Error loading config from {config_path}: {e}")
            # Return default config
            return cls()

    def merge_env_overrides(self):
        """
        Merge environment variable overrides.

        This provides backward compatibility with existing env vars.
        """
        # Override base directory
        env_base_dir = os.getenv("CACHE_BASE_DIR")
        if env_base_dir:
            self.cache_base_dir = env_base_dir

        # Override embedding weight
        env_embedding_weight = os.getenv("HYBRID_EMBEDDING_WEIGHT")
        if env_embedding_weight:
            self.embedding_weight = float(env_embedding_weight)
            self.keyword_weight = 1.0 - self.embedding_weight

        # Override similarity thresholds
        env_response_sim = os.getenv("RESPONSE_CACHE_SIMILARITY")
        if env_response_sim:
            self.similarity_thresholds["response"] = float(env_response_sim)

        env_claims_sim = os.getenv("CLAIMS_CACHE_SIMILARITY")
        if env_claims_sim:
            self.similarity_thresholds["claims"] = float(env_claims_sim)

        # Override quality threshold
        env_quality_min = os.getenv("QUALITY_MIN_FOR_CACHE")
        if env_quality_min:
            self.min_quality_for_cache = float(env_quality_min)

    def get_class_config(self, class_name: str) -> Optional[CacheClassConfig]:
        """
        Get configuration for a cache class.

        Args:
            class_name: Name of cache class (short_lived, medium_term, long_term)

        Returns:
            CacheClassConfig if found, None otherwise
        """
        return self.cache_classes.get(class_name)

    def get_similarity_threshold(self, cache_type: str) -> float:
        """
        Get similarity threshold for a cache type.

        Args:
            cache_type: Type of cache (response, claims, tools)

        Returns:
            Similarity threshold (0.0-1.0)
        """
        return self.similarity_thresholds.get(cache_type, 0.85)

    def get_cache_dir(self, cache_type: str) -> Path:
        """
        Get cache directory path for a cache type.

        Args:
            cache_type: Type of cache (response, claims, tools, etc.)

        Returns:
            Path to cache directory
        """
        base = Path(self.cache_base_dir)
        return base / f"{cache_type}_cache"

    def to_dict(self) -> Dict[str, Any]:
        """
        Export configuration to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "cache_classes": {
                name: {
                    "ttl_seconds": cfg.ttl_seconds,
                    "max_size_mb": cfg.max_size_mb,
                    "eviction_policy": cfg.eviction_policy,
                    "compression_enabled": cfg.compression_enabled
                }
                for name, cfg in self.cache_classes.items()
            },
            "similarity_thresholds": self.similarity_thresholds,
            "eviction_check_interval_seconds": self.eviction_check_interval_seconds,
            "eviction_policy": self.eviction_policy,
            "embedding_weight": self.embedding_weight,
            "keyword_weight": self.keyword_weight,
            "min_quality_for_cache": self.min_quality_for_cache,
            "cache_base_dir": self.cache_base_dir,
            "cascade_enabled": self.cascade_enabled,
            "compression_enabled": self.compression_enabled
        }


# Global configuration instance
_cache_config: Optional[CacheConfig] = None


def get_cache_config(reload: bool = False) -> CacheConfig:
    """
    Get global cache configuration instance (singleton).

    Args:
        reload: Force reload from file

    Returns:
        CacheConfig instance
    """
    global _cache_config

    if _cache_config is None or reload:
        config_path = PROJECT_ROOT / "cache_config.json"
        _cache_config = CacheConfig.load_from_file(config_path)
        _cache_config.merge_env_overrides()
        logger.info(f"[CacheConfig] Loaded unified cache configuration from {config_path}")

    return _cache_config
