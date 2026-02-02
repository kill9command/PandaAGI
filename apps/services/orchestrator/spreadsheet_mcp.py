"""
orchestrator/spreadsheet_mcp.py

Lightweight helpers to write structured rows to CSV or ODS files. The default
path is CSV because it has no heavy dependencies, but the module can emit ODS
when odfpy is available.
"""

from __future__ import annotations

import csv
import datetime as dt
import os
from pathlib import Path
from typing import Iterable, List, Dict, Any, Optional

try:
    from odf.opendocument import OpenDocumentSpreadsheet  # type: ignore
    from odf.table import Table, TableRow, TableCell  # type: ignore
    from odf.text import P  # type: ignore
    HAS_ODS = True
except Exception:  # pragma: no cover - odfpy optional
    HAS_ODS = False


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _normalize_headers(rows: List[Dict[str, Any]]) -> List[str]:
    headers = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                headers.append(str(key))
    return headers


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    headers = _normalize_headers(rows)
    _ensure_parent(path)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in headers})
    return {
        "path": str(path),
        "format": "csv",
        "rows": len(rows),
        "columns": headers,
    }


def write_ods(path: Path, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not HAS_ODS:
        raise RuntimeError("odfpy is required to write ODS files")
    headers = _normalize_headers(rows)
    doc = OpenDocumentSpreadsheet()
    table = Table(name="Sheet1")
    doc.spreadsheet.addElement(table)

    header_row = TableRow()
    for heading in headers:
        cell = TableCell()
        cell.addElement(P(text=str(heading)))
        header_row.addElement(cell)
    table.addElement(header_row)

    for row in rows:
        tr = TableRow()
        for heading in headers:
            cell = TableCell()
            value = row.get(heading, "")
            cell.addElement(P(text=str(value)))
            tr.addElement(cell)
        table.addElement(tr)

    _ensure_parent(path)
    doc.save(str(path))
    return {
        "path": str(path),
        "format": "ods",
        "rows": len(rows),
        "columns": headers,
    }


def write_spreadsheet(
    rows: List[Dict[str, Any]],
    *,
    repo_root: str,
    filename: Optional[str] = None,
    format: str = "csv",
) -> Dict[str, Any]:
    if not rows:
        raise ValueError("rows must be a non-empty list of objects")
    repo_path = Path(repo_root)
    if not repo_path.exists():
        raise FileNotFoundError(f"repo_root not found: {repo_root}")

    if not filename:
        timestamp = dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"parts_{timestamp}.{format}"

    safe_name = filename.replace("..", "_")
    target = repo_path / safe_name

    fmt = format.lower()
    if fmt == "csv":
        return write_csv(target, rows)
    if fmt == "ods":
        return write_ods(target, rows)
    raise ValueError(f"unsupported spreadsheet format '{format}'")

