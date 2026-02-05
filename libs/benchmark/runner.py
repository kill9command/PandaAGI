"""
Benchmark Runner - Core execution engine for benchmark suites.

Runs pytest test suites and collects results with timing and scores.
"""

import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Result of a single test."""
    name: str
    passed: bool
    duration_ms: int
    error: Optional[str] = None
    suite: str = ""


@dataclass
class SuiteResult:
    """Result of running a test suite."""
    name: str
    passed: int
    failed: int
    skipped: int
    total: int
    duration_ms: int
    pass_rate: float
    tests: List[TestResult] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.failed == 0 and self.error is None


@dataclass
class BenchmarkResult:
    """Aggregated results from all suites."""
    timestamp: str
    suites: List[SuiteResult]
    total_passed: int
    total_failed: int
    total_skipped: int
    total_tests: int
    overall_pass_rate: float
    duration_ms: int
    git_commit: Optional[str] = None
    git_branch: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "suites": [
                {
                    "name": s.name,
                    "passed": s.passed,
                    "failed": s.failed,
                    "skipped": s.skipped,
                    "total": s.total,
                    "duration_ms": s.duration_ms,
                    "pass_rate": s.pass_rate,
                    "error": s.error,
                }
                for s in self.suites
            ],
            "total_passed": self.total_passed,
            "total_failed": self.total_failed,
            "total_skipped": self.total_skipped,
            "total_tests": self.total_tests,
            "overall_pass_rate": self.overall_pass_rate,
            "duration_ms": self.duration_ms,
            "git_commit": self.git_commit,
            "git_branch": self.git_branch,
        }


# Default suite definitions
DEFAULT_SUITES = {
    "constraint_pipeline": {
        "path": "tests/contract/test_constraint_pipeline.py",
        "description": "Constraint Pipeline tests",
        "threshold": 0.90,
    },
    "m1_self_extension": {
        "path": "tests/contract/test_tool_creation_pipeline.py",
        "description": "M1 Self-Extension Pipeline tests",
        "threshold": 0.70,
    },
    "m2_apex": {
        "path": "tests/contract/test_m3_apex_acceptance.py",
        "description": "M2 APEX Acceptance tests",
        "threshold": 0.80,
    },
    "m3_harness": {
        "path": "tests/contract/test_m4_benchmark_harness.py",
        "description": "M3 Benchmark Harness tests",
        "threshold": 0.90,
    },
    "spreadsheet": {
        "path": "panda_system_docs/workflows/bundles/spreadsheet/tests/",
        "description": "Spreadsheet tool tests",
        "threshold": 0.80,
    },
    "document": {
        "path": "panda_system_docs/workflows/bundles/document/tests/",
        "description": "Document tool tests",
        "threshold": 0.80,
    },
    "pdf": {
        "path": "panda_system_docs/workflows/bundles/pdf/tests/",
        "description": "PDF tool tests",
        "threshold": 0.80,
    },
    "email": {
        "path": "panda_system_docs/workflows/bundles/email/tests/",
        "description": "Email tool tests",
        "threshold": 0.80,
    },
    "calendar": {
        "path": "panda_system_docs/workflows/bundles/calendar/tests/",
        "description": "Calendar tool tests",
        "threshold": 0.80,
    },
    "travel": {
        "path": "panda_system_docs/workflows/bundles/travel/tests/",
        "description": "Travel domain tests",
        "threshold": 0.80,
    },
    "shopping": {
        "path": "panda_system_docs/workflows/bundles/shopping/tests/",
        "description": "Shopping domain tests",
        "threshold": 0.80,
    },
    "m4_deep_planning": {
        "path": "tests/contract/test_m5_deep_planning.py",
        "description": "M4 DeepPlanning Acceptance tests",
        "threshold": 0.70,
    },
    "phase_contracts": {
        "path": "tests/contract/test_phase_contracts.py",
        "description": "Phase I/O contract tests",
        "threshold": 0.90,
    },
    "mini_benchmarks": {
        "path": "tests/contract/test_mini_benchmarks.py",
        "description": "Mini benchmark phases 1-5",
        "threshold": 0.90,
    },
}


class BenchmarkRunner:
    """
    Runs benchmark suites and collects results.

    Features:
    - Runs pytest suites with JSON output
    - Collects pass/fail/skip counts
    - Measures timing per suite
    - Supports custom suite definitions
    """

    def __init__(
        self,
        suites: Optional[Dict[str, Dict[str, Any]]] = None,
        project_root: Optional[Path] = None,
    ):
        self.suites = suites or DEFAULT_SUITES
        self.project_root = project_root or Path(__file__).parent.parent.parent

    def run_all(self, suite_names: Optional[List[str]] = None) -> BenchmarkResult:
        """
        Run all (or specified) benchmark suites.

        Args:
            suite_names: List of suite names to run (None = all)

        Returns:
            BenchmarkResult with aggregated results
        """
        start_time = time.time()
        timestamp = datetime.now().isoformat()

        suites_to_run = suite_names or list(self.suites.keys())
        suite_results = []

        for name in suites_to_run:
            if name not in self.suites:
                logger.warning(f"[BenchmarkRunner] Unknown suite: {name}")
                continue

            suite_config = self.suites[name]
            result = self.run_suite(name, suite_config)
            suite_results.append(result)

        # Aggregate results
        total_passed = sum(s.passed for s in suite_results)
        total_failed = sum(s.failed for s in suite_results)
        total_skipped = sum(s.skipped for s in suite_results)
        total_tests = sum(s.total for s in suite_results)
        duration_ms = int((time.time() - start_time) * 1000)

        overall_pass_rate = total_passed / total_tests if total_tests > 0 else 0.0

        # Get git info
        git_commit = self._get_git_commit()
        git_branch = self._get_git_branch()

        return BenchmarkResult(
            timestamp=timestamp,
            suites=suite_results,
            total_passed=total_passed,
            total_failed=total_failed,
            total_skipped=total_skipped,
            total_tests=total_tests,
            overall_pass_rate=overall_pass_rate,
            duration_ms=duration_ms,
            git_commit=git_commit,
            git_branch=git_branch,
        )

    def run_suite(self, name: str, config: Dict[str, Any]) -> SuiteResult:
        """
        Run a single benchmark suite.

        Args:
            name: Suite name
            config: Suite configuration with 'path' key

        Returns:
            SuiteResult with pass/fail counts
        """
        path = config.get("path", "")
        full_path = self.project_root / path

        if not full_path.exists():
            logger.error(f"[BenchmarkRunner] Suite path not found: {full_path}")
            return SuiteResult(
                name=name,
                passed=0,
                failed=0,
                skipped=0,
                total=0,
                duration_ms=0,
                pass_rate=0.0,
                error=f"Path not found: {path}"
            )

        logger.info(f"[BenchmarkRunner] Running suite: {name}")
        start_time = time.time()

        try:
            # Run pytest with verbose output for accurate parsing
            result = subprocess.run(
                [
                    sys.executable, "-m", "pytest",
                    str(full_path),
                    "--tb=short",
                    "-v",
                ],
                capture_output=True,
                text=True,
                cwd=str(self.project_root),
                timeout=300,
            )

            duration_ms = int((time.time() - start_time) * 1000)

            # Parse text output
            return self._parse_text_output(name, result.stdout, result.returncode, duration_ms)

        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start_time) * 1000)
            return SuiteResult(
                name=name,
                passed=0,
                failed=0,
                skipped=0,
                total=0,
                duration_ms=duration_ms,
                pass_rate=0.0,
                error="Suite timed out after 300s"
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"[BenchmarkRunner] Suite {name} failed: {e}")
            return SuiteResult(
                name=name,
                passed=0,
                failed=0,
                skipped=0,
                total=0,
                duration_ms=duration_ms,
                pass_rate=0.0,
                error=str(e)
            )

    def _extract_json_report(self, output: str) -> Optional[Dict[str, Any]]:
        """Extract JSON report from pytest output."""
        # Look for JSON object in output
        start = output.find('{"')
        if start == -1:
            return None

        # Find matching closing brace
        depth = 0
        for i, char in enumerate(output[start:], start):
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(output[start:i+1])
                    except json.JSONDecodeError:
                        return None
        return None

    def _parse_json_report(
        self,
        name: str,
        report: Dict[str, Any],
        duration_ms: int
    ) -> SuiteResult:
        """Parse pytest-json-report output."""
        summary = report.get("summary", {})
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        skipped = summary.get("skipped", 0)
        total = passed + failed + skipped

        tests = []
        for test in report.get("tests", []):
            tests.append(TestResult(
                name=test.get("nodeid", "unknown"),
                passed=test.get("outcome") == "passed",
                duration_ms=int(test.get("duration", 0) * 1000),
                error=test.get("longrepr") if test.get("outcome") == "failed" else None,
                suite=name,
            ))

        pass_rate = passed / total if total > 0 else 0.0

        return SuiteResult(
            name=name,
            passed=passed,
            failed=failed,
            skipped=skipped,
            total=total,
            duration_ms=duration_ms,
            pass_rate=pass_rate,
            tests=tests,
        )

    def _parse_text_output(
        self,
        name: str,
        output: str,
        returncode: int,
        duration_ms: int
    ) -> SuiteResult:
        """Parse pytest text output as fallback."""
        import re

        # Look for summary line like "10 passed, 2 failed in 1.23s"
        passed = failed = skipped = 0

        # Match patterns like "22 passed"
        passed_match = re.search(r'(\d+) passed', output)
        if passed_match:
            passed = int(passed_match.group(1))

        failed_match = re.search(r'(\d+) failed', output)
        if failed_match:
            failed = int(failed_match.group(1))

        skipped_match = re.search(r'(\d+) skipped', output)
        if skipped_match:
            skipped = int(skipped_match.group(1))

        total = passed + failed + skipped
        pass_rate = passed / total if total > 0 else 0.0

        error = None
        if returncode != 0 and failed == 0 and total == 0:
            error = f"pytest exited with code {returncode}"

        return SuiteResult(
            name=name,
            passed=passed,
            failed=failed,
            skipped=skipped,
            total=total,
            duration_ms=duration_ms,
            pass_rate=pass_rate,
            error=error,
        )

    def _get_git_commit(self) -> Optional[str]:
        """Get current git commit hash."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=str(self.project_root),
            )
            if result.returncode == 0:
                return result.stdout.strip()[:8]
        except Exception:
            pass
        return None

    def _get_git_branch(self) -> Optional[str]:
        """Get current git branch."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                cwd=str(self.project_root),
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None


def run_benchmarks(
    suite_names: Optional[List[str]] = None,
    suites: Optional[Dict[str, Dict[str, Any]]] = None,
) -> BenchmarkResult:
    """
    Convenience function to run benchmarks.

    Args:
        suite_names: List of suite names to run (None = all)
        suites: Custom suite definitions (None = defaults)

    Returns:
        BenchmarkResult with all results
    """
    runner = BenchmarkRunner(suites=suites)
    return runner.run_all(suite_names)
