"""
Diagnostics MCP - Code validation and linting

Provides syntax checking, linting, type checking, and code quality analysis
for various programming languages.
"""

import ast
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


class DiagnosticError(Exception):
    """Exception for diagnostic operations."""
    pass


def validate_python_syntax(content: str, file_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Validate Python syntax using AST parser.

    Args:
        content: Python code content
        file_path: Optional file path for error messages

    Returns:
        Dict with validation results
    """
    diagnostics = []
    valid = True

    try:
        ast.parse(content)
    except SyntaxError as e:
        valid = False
        diagnostics.append({
            "severity": "error",
            "message": e.msg,
            "line": e.lineno,
            "column": e.offset,
            "source": "python-ast"
        })
    except Exception as e:
        valid = False
        diagnostics.append({
            "severity": "error",
            "message": str(e),
            "line": 0,
            "column": 0,
            "source": "python-ast"
        })

    return {
        "valid": valid,
        "language": "python",
        "file_path": file_path,
        "diagnostics": diagnostics,
        "error_count": sum(1 for d in diagnostics if d["severity"] == "error")
    }


def validate_json_syntax(content: str, file_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Validate JSON syntax.

    Args:
        content: JSON content
        file_path: Optional file path for error messages

    Returns:
        Dict with validation results
    """
    diagnostics = []
    valid = True

    try:
        json.loads(content)
    except json.JSONDecodeError as e:
        valid = False
        diagnostics.append({
            "severity": "error",
            "message": e.msg,
            "line": e.lineno,
            "column": e.colno,
            "source": "json-parser"
        })

    return {
        "valid": valid,
        "language": "json",
        "file_path": file_path,
        "diagnostics": diagnostics,
        "error_count": len(diagnostics)
    }


def run_pylint(
    file_path: str,
    repo: Optional[str] = None,
    config: Optional[str] = None
) -> Dict[str, Any]:
    """
    Run pylint on a Python file.

    Args:
        file_path: Path to Python file
        repo: Base repository path
        config: Optional pylintrc path

    Returns:
        Dict with linting results
    """
    if repo:
        full_path = Path(repo) / file_path
    else:
        full_path = Path(file_path)

    if not full_path.exists():
        raise FileNotFoundError(f"File not found: {full_path}")

    # Check if pylint is installed
    try:
        subprocess.run(["pylint", "--version"], capture_output=True, check=True, timeout=5)
    except (FileNotFoundError, subprocess.CalledProcessError):
        raise DiagnosticError("pylint is not installed")

    # Build command
    cmd = ["pylint", "--output-format=json", str(full_path)]

    if config:
        cmd.extend(["--rcfile", config])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        # Parse JSON output
        try:
            diagnostics_raw = json.loads(result.stdout)
        except json.JSONDecodeError:
            diagnostics_raw = []

        # Convert to standard format
        diagnostics = []
        for d in diagnostics_raw:
            diagnostics.append({
                "severity": _pylint_severity(d.get("type", "")),
                "message": d.get("message", ""),
                "line": d.get("line", 0),
                "column": d.get("column", 0),
                "rule": d.get("message-id", ""),
                "source": "pylint"
            })

        error_count = sum(1 for d in diagnostics if d["severity"] == "error")
        warning_count = sum(1 for d in diagnostics if d["severity"] == "warning")

        return {
            "file_path": str(full_path),
            "diagnostics": diagnostics,
            "error_count": error_count,
            "warning_count": warning_count,
            "exit_code": result.returncode
        }

    except subprocess.TimeoutExpired:
        raise DiagnosticError("pylint timed out")


def _pylint_severity(pylint_type: str) -> str:
    """Convert pylint type to standard severity."""
    mapping = {
        "error": "error",
        "fatal": "error",
        "warning": "warning",
        "refactor": "info",
        "convention": "info",
        "info": "info"
    }
    return mapping.get(pylint_type.lower(), "info")


def run_flake8(
    file_path: str,
    repo: Optional[str] = None,
    config: Optional[str] = None
) -> Dict[str, Any]:
    """
    Run flake8 on a Python file.

    Args:
        file_path: Path to Python file
        repo: Base repository path
        config: Optional config path

    Returns:
        Dict with linting results
    """
    if repo:
        full_path = Path(repo) / file_path
    else:
        full_path = Path(file_path)

    if not full_path.exists():
        raise FileNotFoundError(f"File not found: {full_path}")

    # Check if flake8 is installed
    try:
        subprocess.run(["flake8", "--version"], capture_output=True, check=True, timeout=5)
    except (FileNotFoundError, subprocess.CalledProcessError):
        raise DiagnosticError("flake8 is not installed")

    # Build command
    cmd = ["flake8", str(full_path)]

    if config:
        cmd.extend(["--config", config])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        # Parse output
        diagnostics = []
        for line in result.stdout.splitlines():
            match = re.match(r"(.+?):(\d+):(\d+):\s+(\w+)\s+(.+)", line)
            if match:
                file, lineno, col, code, msg = match.groups()
                diagnostics.append({
                    "severity": "error" if code.startswith("E") else "warning",
                    "message": msg,
                    "line": int(lineno),
                    "column": int(col),
                    "rule": code,
                    "source": "flake8"
                })

        error_count = sum(1 for d in diagnostics if d["severity"] == "error")
        warning_count = sum(1 for d in diagnostics if d["severity"] == "warning")

        return {
            "file_path": str(full_path),
            "diagnostics": diagnostics,
            "error_count": error_count,
            "warning_count": warning_count,
            "exit_code": result.returncode
        }

    except subprocess.TimeoutExpired:
        raise DiagnosticError("flake8 timed out")


def run_mypy(
    file_path: str,
    repo: Optional[str] = None,
    config: Optional[str] = None
) -> Dict[str, Any]:
    """
    Run mypy type checker on a Python file.

    Args:
        file_path: Path to Python file
        repo: Base repository path
        config: Optional mypy config path

    Returns:
        Dict with type checking results
    """
    if repo:
        full_path = Path(repo) / file_path
    else:
        full_path = Path(file_path)

    if not full_path.exists():
        raise FileNotFoundError(f"File not found: {full_path}")

    # Check if mypy is installed
    try:
        subprocess.run(["mypy", "--version"], capture_output=True, check=True, timeout=5)
    except (FileNotFoundError, subprocess.CalledProcessError):
        raise DiagnosticError("mypy is not installed")

    # Build command
    cmd = ["mypy", "--show-column-numbers", str(full_path)]

    if config:
        cmd.extend(["--config-file", config])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        # Parse output
        diagnostics = []
        for line in result.stdout.splitlines():
            match = re.match(r"(.+?):(\d+):(\d+):\s+(\w+):\s+(.+)", line)
            if match:
                file, lineno, col, severity, msg = match.groups()
                diagnostics.append({
                    "severity": severity.lower(),
                    "message": msg,
                    "line": int(lineno),
                    "column": int(col),
                    "rule": "type-check",
                    "source": "mypy"
                })

        error_count = sum(1 for d in diagnostics if d["severity"] == "error")
        warning_count = sum(1 for d in diagnostics if d["severity"] == "warning")

        return {
            "file_path": str(full_path),
            "diagnostics": diagnostics,
            "error_count": error_count,
            "warning_count": warning_count,
            "exit_code": result.returncode
        }

    except subprocess.TimeoutExpired:
        raise DiagnosticError("mypy timed out")


def run_eslint(
    file_path: str,
    repo: Optional[str] = None,
    config: Optional[str] = None
) -> Dict[str, Any]:
    """
    Run eslint on a JavaScript/TypeScript file.

    Args:
        file_path: Path to JS/TS file
        repo: Base repository path
        config: Optional eslint config path

    Returns:
        Dict with linting results
    """
    if repo:
        full_path = Path(repo) / file_path
    else:
        full_path = Path(file_path)

    if not full_path.exists():
        raise FileNotFoundError(f"File not found: {full_path}")

    # Check if eslint is installed
    try:
        subprocess.run(["eslint", "--version"], capture_output=True, check=True, timeout=5)
    except (FileNotFoundError, subprocess.CalledProcessError):
        raise DiagnosticError("eslint is not installed")

    # Build command
    cmd = ["eslint", "--format=json", str(full_path)]

    if config:
        cmd.extend(["--config", config])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        # Parse JSON output
        try:
            results = json.loads(result.stdout)
        except json.JSONDecodeError:
            results = []

        diagnostics = []
        for file_result in results:
            for msg in file_result.get("messages", []):
                severity_map = {1: "warning", 2: "error"}
                diagnostics.append({
                    "severity": severity_map.get(msg.get("severity", 1), "info"),
                    "message": msg.get("message", ""),
                    "line": msg.get("line", 0),
                    "column": msg.get("column", 0),
                    "rule": msg.get("ruleId", ""),
                    "source": "eslint"
                })

        error_count = sum(1 for d in diagnostics if d["severity"] == "error")
        warning_count = sum(1 for d in diagnostics if d["severity"] == "warning")

        return {
            "file_path": str(full_path),
            "diagnostics": diagnostics,
            "error_count": error_count,
            "warning_count": warning_count,
            "exit_code": result.returncode
        }

    except subprocess.TimeoutExpired:
        raise DiagnosticError("eslint timed out")


def validate_file(file_path: str, repo: Optional[str] = None) -> Dict[str, Any]:
    """
    Auto-detect file type and run appropriate validation.

    Args:
        file_path: Path to file
        repo: Base repository path

    Returns:
        Dict with validation results
    """
    if repo:
        full_path = Path(repo) / file_path
    else:
        full_path = Path(file_path)

    if not full_path.exists():
        raise FileNotFoundError(f"File not found: {full_path}")

    # Read file content
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        return {
            "valid": False,
            "error": "Cannot read file (binary or encoding issue)"
        }

    # Detect file type
    suffix = full_path.suffix.lower()

    if suffix == ".py":
        return validate_python_syntax(content, str(full_path))
    elif suffix == ".json":
        return validate_json_syntax(content, str(full_path))
    else:
        return {
            "valid": True,
            "message": f"No validator available for {suffix} files",
            "file_path": str(full_path)
        }


def get_diagnostics_summary(repo: str, file_pattern: str = "**/*.py") -> Dict[str, Any]:
    """
    Get diagnostics summary for multiple files.

    Args:
        repo: Repository path
        file_pattern: Glob pattern for files

    Returns:
        Dict with aggregated diagnostics
    """
    repo_path = Path(repo)

    if not repo_path.exists():
        raise FileNotFoundError(f"Repository not found: {repo}")

    # Find matching files
    files = list(repo_path.glob(file_pattern))

    results = []
    total_errors = 0
    total_warnings = 0

    for file_path in files[:50]:  # Limit to 50 files
        try:
            result = validate_file(str(file_path), repo)
            results.append(result)

            total_errors += result.get("error_count", 0)
            total_warnings += result.get("warning_count", 0)
        except Exception as e:
            results.append({
                "file_path": str(file_path),
                "error": str(e)
            })

    return {
        "repo": repo,
        "pattern": file_pattern,
        "files_checked": len(results),
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "results": results
    }
