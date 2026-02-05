"""
Product Perception Pipeline - Hybrid Vision+HTML Product Extraction

This module provides a robust, universal product extraction system that
combines HTML extraction (for URLs) with vision/OCR extraction (for product data).

Usage:
    from apps.services.tool_server.product_perception import ProductPerceptionPipeline

    pipeline = ProductPerceptionPipeline()
    products = await pipeline.extract(page, url, query)

Components:
    - HTMLExtractor: Extracts product URLs from HTML (JSON-LD, patterns, heuristics)
    - VisionExtractor: Extracts product data from screenshots (OCR + LLM)
    - ProductFusion: Matches vision products to HTML URLs
    - URLResolver: Click-to-resolve fallback for unmatched products
    - PDPExtractor: Extracts verified data from Product Detail Pages
    - ProductPerceptionPipeline: Main orchestrator combining all components

Data Models:
    - VisualProduct: Product identified by vision/OCR
    - HTMLCandidate: Potential product URL from HTML
    - FusedProduct: Final product combining both sources
    - PDPData: Verified product data from Product Detail Page
    - ExtractionResult: Complete extraction result with stats
"""

from .models import (
    BoundingBox,
    OCRItem,
    VisualProduct,
    HTMLCandidate,
    FusedProduct,
    PDPData,
    ExtractionResult,
)

from .config import (
    PerceptionConfig,
    get_config,
    set_config,
)

from .html_extractor import HTMLExtractor
from .vision_extractor import VisionExtractor
from .fusion import ProductFusion, match_html_only
from .resolver import URLResolver
from .pdp_extractor import PDPExtractor
from .product_verifier import ProductVerifier, VerifiedProduct, verify_products
from .pipeline import ProductPerceptionPipeline, extract_products

__all__ = [
    # Main pipeline
    'ProductPerceptionPipeline',
    'extract_products',

    # Components
    'HTMLExtractor',
    'VisionExtractor',
    'ProductFusion',
    'URLResolver',
    'PDPExtractor',
    'ProductVerifier',
    'VerifiedProduct',
    'verify_products',

    # Data models
    'BoundingBox',
    'OCRItem',
    'VisualProduct',
    'HTMLCandidate',
    'FusedProduct',
    'PDPData',
    'ExtractionResult',

    # Config
    'PerceptionConfig',
    'get_config',
    'set_config',

    # Utilities
    'match_html_only',
]
