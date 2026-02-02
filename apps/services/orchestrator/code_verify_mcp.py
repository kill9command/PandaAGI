"""
Code verification suite tool.

Runs tests, linters, and type checkers in one unified call.
"""
import subprocess
import re
import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


async def code_verify_suite(
    target: str = ".",
    repo: str = None,
    tests: bool = True,
    lint: bool = False,
    typecheck: bool = False,
    timeout: int = 60,
    **kwargs
) -> Dict[str, Any]:
    """
    Run verification suite (tests + optional lint/typecheck).

    MCP tool signature:
    {
        "name": "code.verify_suite",
        "description": "Run tests, linters, and type checkers in one call",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "default": ".", "description": "Directory or file to verify"},
                "repo": {"type": "string", "description": "Repository path"},
                "tests": {"type": "boolean", "default": true},
                "lint": {"type": "boolean", "default": false, "description": "Run linter (slower, opt-in)"},
                "typecheck": {"type": "boolean", "default": false, "description": "Run type checker (slower, opt-in)"},
                "timeout": {"type": "integer", "default": 60}
            },
            "required": []
        }
    }

    Args:
        target: Directory or file to verify (default: current dir)
        repo: Repository path
        tests: Run tests (default: True)
        lint: Run linter (default: False, opt-in for speed)
        typecheck: Run type checker (default: False, opt-in for speed)
        timeout: Max seconds per operation

    Returns:
        {
            "tests": {"passed": 12, "failed": 2, "errors": [...], "status": "fail"},
            "lint": {"issues": 5, "details": [...], "status": "warnings"},
            "typecheck": {"errors": 1, "details": [...], "status": "fail"},
            "summary": "12/14 tests passed, 5 lint issues",
            "overall_status": "fail"
        }
    """
    results = {
        "timestamp": datetime.now().isoformat()
    }

    # Run tests
    if tests:
        results["tests"] = await _run_tests(target, repo, timeout)

    # Run linter (opt-in)
    if lint:
        results["lint"] = await _run_linter(target, repo, timeout // 2)

    # Run type checker (opt-in)
    if typecheck:
        results["typecheck"] = await _run_typecheck(target, repo, timeout // 2)

    # Generate summary
    results["summary"] = _generate_summary(results)
    results["overall_status"] = _overall_status(results)

    return results


async def _run_tests(target: str, repo: Optional[str], timeout: int) -> Dict[str, Any]:
    """Run pytest and parse results."""
    # Try pytest first
    cmd = ["pytest", target, "-v", "--tb=short", "-q"]

    try:
        result = subprocess.run(
            cmd,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        output = result.stdout + result.stderr

        # Parse pytest output
        # Example: "10 passed, 2 failed in 1.23s" or "10 passed in 0.5s"
        passed_match = re.search(r'(\d+)\s+passed', output)
        failed_match = re.search(r'(\d+)\s+failed', output)

        if passed_match or failed_match:
            passed = int(passed_match.group(1)) if passed_match else 0
            failed = int(failed_match.group(1)) if failed_match else 0

            # Extract failed test names
            errors = []
            if failed > 0:
                failed_tests = re.findall(r'FAILED\s+([\w/:\.]+)(?:\s+-\s+(.+?))?$', output, re.MULTILINE)
                errors = [f"{test}: {reason}" if reason else test for test, reason in failed_tests[:10]]

            return {
                "passed": passed,
                "failed": failed,
                "total": passed + failed,
                "errors": errors,
                "status": "pass" if failed == 0 else "fail",
                "runner": "pytest"
            }
        else:
            # Fallback: check exit code
            if result.returncode == 0:
                return {
                    "status": "pass",
                    "runner": "pytest",
                    "message": "All tests passed (count unknown)"
                }
            else:
                return {
                    "status": "fail",
                    "runner": "pytest",
                    "output": output[:500]
                }

    except subprocess.TimeoutExpired:
        return {"status": "timeout", "error": f"Tests exceeded {timeout}s timeout"}
    except FileNotFoundError:
        # pytest not installed, try unittest
        return await _run_unittest(target, repo, timeout)
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def _run_unittest(target: str, repo: Optional[str], timeout: int) -> Dict[str, Any]:
    """Fallback to unittest if pytest not available."""
    cmd = ["python", "-m", "unittest", "discover", "-s", target, "-v"]

    try:
        result = subprocess.run(
            cmd,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        output = result.stdout + result.stderr

        # Parse unittest output
        # Example: "Ran 10 tests in 0.5s" followed by "OK" or "FAILED (failures=2)"
        ran_match = re.search(r'Ran\s+(\d+)\s+test', output)
        failed_match = re.search(r'FAILED\s+\(.*?failures=(\d+)', output)

        if ran_match:
            total = int(ran_match.group(1))
            failed = int(failed_match.group(1)) if failed_match else 0
            passed = total - failed

            return {
                "passed": passed,
                "failed": failed,
                "total": total,
                "status": "pass" if failed == 0 else "fail",
                "runner": "unittest"
            }
        else:
            return {
                "status": "unknown",
                "runner": "unittest",
                "output": output[:500]
            }

    except Exception as e:
        return {"status": "error", "error": str(e), "runner": "unittest"}


async def _run_linter(target: str, repo: Optional[str], timeout: int) -> Dict[str, Any]:
    """Run flake8 linter and parse results."""
    # Use flake8 (faster than pylint)
    cmd = ["flake8", target, "--count", "--max-line-length=120"]

    try:
        result = subprocess.run(
            cmd,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        output = result.stdout + result.stderr

        # Parse issue count (last line usually)
        lines = output.strip().split('\n')
        issue_count = 0

        # Try to extract count from last line
        if lines:
            count_match = re.search(r'(\d+)$', lines[-1])
            if count_match:
                issue_count = int(count_match.group(1))
            else:
                # Count lines with issues
                issue_count = len([l for l in lines if ':' in l and '.' in l])

        # Extract first 10 issues
        issues = []
        for line in lines[:10]:
            if ':' in line and '.' in line:
                issues.append(line.strip())

        return {
            "issues": issue_count,
            "details": issues,
            "status": "pass" if issue_count == 0 else "warnings",
            "tool": "flake8"
        }

    except subprocess.TimeoutExpired:
        return {"status": "timeout", "error": f"Linting exceeded {timeout}s timeout"}
    except FileNotFoundError:
        return {"status": "skipped", "error": "flake8 not installed"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def _run_typecheck(target: str, repo: Optional[str], timeout: int) -> Dict[str, Any]:
    """Run mypy type checker and parse results."""
    cmd = ["mypy", target, "--no-error-summary", "--show-error-codes"]

    try:
        result = subprocess.run(
            cmd,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        output = result.stdout + result.stderr

        # Count errors
        error_lines = [line for line in output.split('\n') if 'error:' in line.lower()]
        error_count = len(error_lines)

        return {
            "errors": error_count,
            "details": error_lines[:10],
            "status": "pass" if error_count == 0 else "fail",
            "tool": "mypy"
        }

    except subprocess.TimeoutExpired:
        return {"status": "timeout", "error": f"Type checking exceeded {timeout}s timeout"}
    except FileNotFoundError:
        return {"status": "skipped", "error": "mypy not installed"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _generate_summary(results: Dict[str, Any]) -> str:
    """Generate human-readable summary."""
    parts = []

    if "tests" in results:
        tests = results["tests"]
        if tests.get("status") == "pass":
            count = tests.get("passed", tests.get("total", 0))
            parts.append(f"✅ {count} tests passed")
        elif tests.get("status") == "fail":
            passed = tests.get("passed", 0)
            failed = tests.get("failed", 0)
            total = tests.get("total", passed + failed)
            parts.append(f"❌ {failed}/{total} tests failed")
        elif tests.get("status") == "timeout":
            parts.append("⏱️ Tests timed out")

    if "lint" in results:
        lint = results["lint"]
        if lint.get("status") == "warnings" and lint.get("issues", 0) > 0:
            parts.append(f"⚠️ {lint['issues']} lint issues")
        elif lint.get("status") == "pass":
            parts.append("✅ No lint issues")

    if "typecheck" in results:
        tc = results["typecheck"]
        if tc.get("status") == "fail" and tc.get("errors", 0) > 0:
            parts.append(f"❌ {tc['errors']} type errors")
        elif tc.get("status") == "pass":
            parts.append("✅ No type errors")

    return ", ".join(parts) if parts else "✅ All checks passed"


def _overall_status(results: Dict[str, Any]) -> str:
    """Determine overall status from all checks."""
    # Check if any failed
    if "tests" in results and results["tests"].get("status") == "fail":
        return "fail"
    if "typecheck" in results and results["typecheck"].get("status") == "fail":
        return "fail"

    # Check for warnings
    if "lint" in results and results["lint"].get("status") == "warnings":
        return "warnings"

    # Check for timeouts
    if "tests" in results and results["tests"].get("status") == "timeout":
        return "timeout"

    # All passed
    return "pass"
