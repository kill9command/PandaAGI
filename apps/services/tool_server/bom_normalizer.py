"""Basic BOM normalization utilities."""

from __future__ import annotations

import re
from typing import List, Dict, Any, Optional


def _clean_line(line: str) -> str:
    line = re.sub(r"\s+", " ", line)
    return line.strip(" -\t\n\r")


def _extract_quantity(text: str) -> tuple[Optional[float], str]:
    match = re.match(r"^(?P<count>\d+(?:\.\d+)?)\s*[x×]\s*(?P<rest>.+)$", text, re.IGNORECASE)
    if match:
        count = float(match.group("count"))
        rest = match.group("rest").strip()
        return count, rest

    match = re.match(r"^(?P<count>\d+(?:\.\d+)?)\s+(?P<rest>.+)$", text)
    if match:
        count = float(match.group("count"))
        rest = match.group("rest").strip()
        return count, rest

    return None, text


def normalize_bom_lines(lines: List[str], source: str | None = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for raw in lines:
        line = _clean_line(raw)
        if not line:
            continue
        quantity, remainder = _extract_quantity(line)
        part = remainder
        notes: Optional[str] = None

        if " - " in part:
            part, notes = part.split(" - ", 1)
        elif " – " in part:
            part, notes = part.split(" – ", 1)

        part = part.strip()
        if not part:
            continue

        row: Dict[str, Any] = {
            "part": part,
            "quantity": quantity if quantity is not None else 1,
        }
        if notes:
            row["notes"] = notes.strip()
        if source:
            row["source"] = source
        rows.append(row)

    return rows


def normalize_bom_text(text: str, source: str | None = None) -> List[Dict[str, Any]]:
    if not text:
        return []
    lines = [line for line in text.splitlines() if line.strip()]
    return normalize_bom_lines(lines, source=source)
