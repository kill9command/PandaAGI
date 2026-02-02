"""
Utilities for working with specs_discovered data.

Handles both old and new formats for backwards compatibility:
- Old format: {"gpu": "RTX 4060", "ram": "16GB"}
- New format: {"gpu": {"value": "RTX 4060", "confidence": 0.9, "source_hint": "expert_review"}}
"""

from typing import Any, Dict, Optional


def get_spec_value(specs: Dict[str, Any], key: str, default: Any = None) -> Any:
    """
    Extract spec value regardless of format (old or new).

    Old format: {"gpu": "RTX 4060"}
    New format: {"gpu": {"value": "RTX 4060", "confidence": 0.9}}

    Args:
        specs: The specs_discovered dict
        key: The spec key to retrieve (e.g., "gpu", "ram")
        default: Default value if key not found

    Returns:
        The actual spec value (string/number), not the wrapper dict

    Examples:
        >>> get_spec_value({"gpu": "RTX 4060"}, "gpu")
        "RTX 4060"
        >>> get_spec_value({"gpu": {"value": "RTX 4060", "confidence": 0.9}}, "gpu")
        "RTX 4060"
        >>> get_spec_value({}, "gpu", "N/A")
        "N/A"
    """
    if not specs:
        return default

    val = specs.get(key, default)

    if val is None:
        return default

    # New format: value is a dict with "value" key
    if isinstance(val, dict):
        return val.get("value", default)

    # Old format: value is the spec directly
    return val


def get_spec_confidence(specs: Dict[str, Any], key: str, default: float = 0.5) -> float:
    """
    Extract confidence score for a spec (new format only).

    Args:
        specs: The specs_discovered dict
        key: The spec key to retrieve
        default: Default confidence if not available (0.5 = medium)

    Returns:
        Confidence score between 0.0 and 1.0
    """
    if not specs:
        return default

    val = specs.get(key)

    if val is None:
        return default

    # New format: value is a dict with "confidence" key
    if isinstance(val, dict):
        return float(val.get("confidence", default))

    # Old format: no confidence available, return default
    return default


def get_spec_source(specs: Dict[str, Any], key: str, default: str = "unknown") -> str:
    """
    Extract source hint for a spec (new format only).

    Args:
        specs: The specs_discovered dict
        key: The spec key to retrieve
        default: Default source if not available

    Returns:
        Source hint string (e.g., "expert_review", "forum")
    """
    if not specs:
        return default

    val = specs.get(key)

    if val is None:
        return default

    # New format: value is a dict with "source_hint" key
    if isinstance(val, dict):
        return val.get("source_hint", default)

    # Old format: no source available, return default
    return default


def normalize_specs(specs: Dict[str, Any]) -> Dict[str, str]:
    """
    Normalize specs to simple key-value format (old format).

    Useful when you need a flat dict of spec values without confidence metadata.

    Args:
        specs: The specs_discovered dict (old or new format)

    Returns:
        Flat dict with spec values only: {"gpu": "RTX 4060", "ram": "16GB"}
    """
    if not specs:
        return {}

    result = {}
    for key, val in specs.items():
        if isinstance(val, dict):
            # New format
            value = val.get("value")
            if value is not None:
                result[key] = str(value)
        elif val is not None:
            # Old format
            result[key] = str(val)

    return result


def iter_specs(specs: Dict[str, Any]):
    """
    Iterate over specs yielding (key, value, confidence, source) tuples.

    Works with both old and new formats.

    Args:
        specs: The specs_discovered dict

    Yields:
        Tuple of (key, value, confidence, source_hint)
        - For old format: confidence=0.5, source_hint="unknown"
    """
    if not specs:
        return

    for key, val in specs.items():
        if isinstance(val, dict):
            # New format
            yield (
                key,
                val.get("value"),
                val.get("confidence", 0.5),
                val.get("source_hint", "unknown")
            )
        elif val is not None:
            # Old format
            yield (key, val, 0.5, "unknown")
