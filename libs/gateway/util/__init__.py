"""
Utility module - Various utilities and helpers.

Contains:
- ErrorCompactor: Compact error messages
- PrincipleExtractor: Extract improvement principles
- PandoraLoop: Main reflection loop
- cache_manager: Caching utilities
"""

from libs.gateway.util.error_compactor import ErrorCompactor, CompactedError, get_error_compactor
from libs.gateway.util.principle_extractor import PrincipleExtractor, ImprovementPrinciple
from libs.gateway.util.pandora_loop import PandoraLoop, LoopResult, format_loop_summary

__all__ = [
    "ErrorCompactor",
    "CompactedError",
    "get_error_compactor",
    "PrincipleExtractor",
    "ImprovementPrinciple",
    "PandoraLoop",
    "LoopResult",
    "format_loop_summary",
]
