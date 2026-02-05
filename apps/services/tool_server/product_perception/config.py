"""
Configuration for product perception pipeline.
"""

import os
from dataclasses import dataclass


@dataclass
class PerceptionConfig:
    """Configuration for hybrid product extraction."""

    # Feature flags
    enable_hybrid: bool = True
    enable_click_resolve: bool = True
    enable_json_ld: bool = True
    enable_url_patterns: bool = True
    enable_dom_heuristics: bool = True

    # Limits
    max_click_resolves: int = 5
    max_products_per_retailer: int = 20
    max_ocr_groups: int = 25

    # OCR settings
    ocr_use_gpu: bool = False  # Use CPU to save VRAM for vLLM
    ocr_confidence_min: float = 0.5
    ocr_lang: str = "en"

    # Fusion settings
    similarity_threshold: float = 0.40  # Min similarity for fusion match (lowered from 0.55)
    boost_on_match: float = 0.1  # Confidence boost when fusion matches

    # Spatial grouping for OCR
    # Note: Keep tight grouping to avoid merging different products
    y_group_threshold: int = 80   # Pixels - vertical proximity for grouping (reverted from 150)
    x_group_threshold: int = 400  # Pixels - horizontal proximity (reverted from 500)

    # Price pattern filtering
    # If False, send ALL spatial groups to LLM (don't filter by price pattern)
    require_price_pattern: bool = False  # Changed: let LLM decide what's a product

    # Timeouts (milliseconds)
    # Note: CPU OCR can take 20-30s for complex screenshots, increase if needed
    ocr_timeout_ms: int = 30000
    llm_timeout_ms: int = 30000
    click_resolve_timeout_ms: int = 5000

    # Fallback behavior
    fallback_to_html_only: bool = True

    # PDP (Product Detail Page) Verification settings
    enable_pdp_verification: bool = True       # Master switch for PDP verification
    pdp_verification_timeout_ms: int = 3000    # Max time per PDP extraction
    pdp_max_verify_per_retailer: int = 5       # Limit verifications per retailer
    pdp_track_discrepancies: bool = True       # Log price mismatches for monitoring
    pdp_discrepancy_threshold: float = 0.10    # Log if price differs by more than 10%

    # Schema Build Mode settings (proactive calibration)
    enable_proactive_calibration: bool = True   # Build schema BEFORE extraction, not after
    calibration_timeout_ms: int = 15000         # Max time for schema calibration
    calibration_min_confidence: float = 0.5     # Below this, skip schema and use vision

    # Debug
    save_debug_screenshots: bool = False
    debug_output_dir: str = "/tmp/product_perception_debug"

    @classmethod
    def from_env(cls) -> 'PerceptionConfig':
        """Load configuration from environment variables."""
        return cls(
            enable_hybrid=os.getenv("PERCEPTION_ENABLE_HYBRID", "true").lower() == "true",
            enable_click_resolve=os.getenv("PERCEPTION_ENABLE_CLICK_RESOLVE", "true").lower() == "true",
            max_click_resolves=int(os.getenv("PERCEPTION_MAX_CLICK_RESOLVES", "5")),
            max_products_per_retailer=int(os.getenv("PERCEPTION_MAX_PRODUCTS", "20")),
            ocr_use_gpu=os.getenv("PERCEPTION_OCR_USE_GPU", "false").lower() == "true",
            ocr_confidence_min=float(os.getenv("PERCEPTION_OCR_CONFIDENCE_MIN", "0.5")),
            similarity_threshold=float(os.getenv("PERCEPTION_SIMILARITY_THRESHOLD", "0.40")),
            fallback_to_html_only=os.getenv("PERCEPTION_FALLBACK_HTML", "true").lower() == "true",
            # Spatial grouping
            y_group_threshold=int(os.getenv("PERCEPTION_Y_GROUP_THRESHOLD", "80")),
            require_price_pattern=os.getenv("PERCEPTION_REQUIRE_PRICE_PATTERN", "false").lower() == "true",
            # PDP verification settings
            enable_pdp_verification=os.getenv("PERCEPTION_ENABLE_PDP_VERIFY", "true").lower() == "true",
            pdp_verification_timeout_ms=int(os.getenv("PERCEPTION_PDP_TIMEOUT_MS", "3000")),
            pdp_max_verify_per_retailer=int(os.getenv("PERCEPTION_PDP_MAX_VERIFY", "5")),
            pdp_track_discrepancies=os.getenv("PERCEPTION_PDP_TRACK_DISCREPANCY", "true").lower() == "true",
            pdp_discrepancy_threshold=float(os.getenv("PERCEPTION_PDP_DISCREPANCY_THRESHOLD", "0.10")),
            # Schema Build Mode
            enable_proactive_calibration=os.getenv("PERCEPTION_PROACTIVE_CALIBRATION", "true").lower() == "true",
            calibration_timeout_ms=int(os.getenv("PERCEPTION_CALIBRATION_TIMEOUT_MS", "15000")),
            calibration_min_confidence=float(os.getenv("PERCEPTION_CALIBRATION_MIN_CONFIDENCE", "0.5")),
            # Debug
            save_debug_screenshots=os.getenv("PERCEPTION_DEBUG", "false").lower() == "true",
        )


# Global config instance
_config: PerceptionConfig = None


def get_config() -> PerceptionConfig:
    """Get global perception config (lazy-loaded from env)."""
    global _config
    if _config is None:
        _config = PerceptionConfig.from_env()
    return _config


def set_config(config: PerceptionConfig) -> None:
    """Set global perception config (for testing)."""
    global _config
    _config = config
