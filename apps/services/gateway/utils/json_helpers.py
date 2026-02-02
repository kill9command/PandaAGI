"""
JSON Parsing Utilities

Provides robust JSON extraction from text, handling fenced code blocks
and malformed JSON responses from LLMs.
"""

import json
import re
from typing import Any, Iterator, Optional

# Regex for extracting JSON from markdown fenced code blocks
JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)


def iter_json_object_slices(text: str) -> Iterator[str]:
    """
    Iterate over JSON object slices in text.

    This generator finds all top-level JSON objects in a text string,
    handling nested braces and string escaping correctly.

    Args:
        text: Input text potentially containing JSON objects

    Yields:
        Each JSON object slice as a string
    """
    depth = 0
    start = None
    in_string = False
    escape = False

    for idx, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == "\"":
                in_string = False
            continue

        if ch == "\"":
            in_string = True
            continue

        if ch == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif ch == "}":
            if depth:
                depth -= 1
                if depth == 0 and start is not None:
                    yield text[start : idx + 1]
                    start = None


def extract_json(obj_or_text: Any) -> Optional[dict]:
    """
    Extract JSON from text or pass through dict.

    Handles multiple formats:
    1. Already a dict - returns as-is
    2. Pure JSON string - parses directly
    3. JSON in markdown fence (```json ... ```)
    4. JSON embedded in other text

    Args:
        obj_or_text: Either a dict or string potentially containing JSON

    Returns:
        Parsed dict or None if no valid JSON found
    """
    if isinstance(obj_or_text, dict):
        return obj_or_text

    text = (obj_or_text or "").strip()

    def _try_load(candidate: str) -> Optional[dict]:
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                return result
            return None
        except Exception:
            return None

    if not text:
        return None

    # Try fenced code block first (```json ... ```)
    m = JSON_FENCE_RE.search(text)
    if m:
        candidate = (m.group(1) or "").strip()
        parsed = _try_load(candidate)
        if parsed is not None:
            return parsed

    # Try parsing the whole text as JSON
    parsed = _try_load(text)
    if parsed is not None:
        return parsed

    # Try extracting embedded JSON objects
    for slice_text in iter_json_object_slices(text):
        parsed = _try_load(slice_text.strip())
        if parsed is not None:
            return parsed

    return None
