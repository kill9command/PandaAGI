"""
Sandbox Test Runner - Executes tool tests in isolated environment.

Architecture Reference:
- architecture/concepts/TOOL_SYSTEM.md

Runs tests in isolated subprocess with:
- Timeout enforcement
- Output capture
- Exit code checking
"""

import asyncio
import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Result of running a test."""
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    test_file: str
    error_message: Optional[str] = None


@dataclass
class SandboxResult:
    """Result of running all tests in sandbox."""
    success: bool
    tests_run: int
    tests_passed: int
    tests_failed: int
    results: List[TestResult] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def summary(self) -> str:
        """Human-readable summary."""
        if self.error:
            return f"Sandbox error: {self.error}"
        return f"{self.tests_passed}/{self.tests_run} tests passed"


class SandboxRunner:
    """
    Runs tool tests in an isolated subprocess.

    Features:
    - Timeout enforcement (default 30s per test)
    - Output capture (stdout/stderr)
    - Exit code checking
    - Python path isolation
    """

    DEFAULT_TIMEOUT = 30  # seconds

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        python_path: Optional[str] = None
    ):
        """
        Initialize sandbox runner.

        Args:
            timeout: Maximum seconds per test
            python_path: Python interpreter to use (default: current)
        """
        self.timeout = timeout
        self.python_path = python_path or sys.executable

    async def run_tests(
        self,
        test_files: List[Path],
        working_dir: Optional[Path] = None
    ) -> SandboxResult:
        """
        Run multiple test files.

        Args:
            test_files: List of test file paths
            working_dir: Working directory for tests

        Returns:
            SandboxResult with all test results
        """
        result = SandboxResult(
            success=True,
            tests_run=0,
            tests_passed=0,
            tests_failed=0
        )

        for test_file in test_files:
            if not test_file.exists():
                logger.warning(f"[SandboxRunner] Test file not found: {test_file}")
                continue

            test_result = await self.run_single_test(test_file, working_dir)
            result.results.append(test_result)
            result.tests_run += 1

            if test_result.passed:
                result.tests_passed += 1
            else:
                result.tests_failed += 1
                result.success = False

        return result

    async def run_single_test(
        self,
        test_file: Path,
        working_dir: Optional[Path] = None
    ) -> TestResult:
        """
        Run a single test file in subprocess.

        Args:
            test_file: Path to test file
            working_dir: Working directory

        Returns:
            TestResult with execution details
        """
        import time
        start_time = time.time()

        cwd = str(working_dir) if working_dir else str(test_file.parent)

        # Build command - use pytest if available, else direct python
        cmd = [
            self.python_path,
            "-m", "pytest",
            str(test_file),
            "-v",
            "--tb=short",
            "-x",  # Stop on first failure
        ]

        try:
            # Run in subprocess with timeout
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=self._get_sandbox_env()
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                duration_ms = int((time.time() - start_time) * 1000)
                return TestResult(
                    passed=False,
                    exit_code=-1,
                    stdout="",
                    stderr="",
                    duration_ms=duration_ms,
                    test_file=str(test_file),
                    error_message=f"Test timed out after {self.timeout}s"
                )

            duration_ms = int((time.time() - start_time) * 1000)
            passed = process.returncode == 0

            return TestResult(
                passed=passed,
                exit_code=process.returncode,
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                duration_ms=duration_ms,
                test_file=str(test_file),
                error_message=None if passed else f"Test failed with exit code {process.returncode}"
            )

        except FileNotFoundError:
            # pytest not available, try direct python
            return await self._run_direct_python(test_file, cwd, start_time)
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return TestResult(
                passed=False,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_ms=duration_ms,
                test_file=str(test_file),
                error_message=f"Execution error: {e}"
            )

    async def _run_direct_python(
        self,
        test_file: Path,
        cwd: str,
        start_time: float
    ) -> TestResult:
        """Fallback: run test file directly with Python."""
        import time

        cmd = [self.python_path, str(test_file)]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=self._get_sandbox_env()
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                duration_ms = int((time.time() - start_time) * 1000)
                return TestResult(
                    passed=False,
                    exit_code=-1,
                    stdout="",
                    stderr="",
                    duration_ms=duration_ms,
                    test_file=str(test_file),
                    error_message=f"Test timed out after {self.timeout}s"
                )

            duration_ms = int((time.time() - start_time) * 1000)
            passed = process.returncode == 0

            return TestResult(
                passed=passed,
                exit_code=process.returncode,
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                duration_ms=duration_ms,
                test_file=str(test_file),
                error_message=None if passed else f"Test failed with exit code {process.returncode}"
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return TestResult(
                passed=False,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_ms=duration_ms,
                test_file=str(test_file),
                error_message=f"Execution error: {e}"
            )

    def _get_sandbox_env(self) -> dict:
        """Get environment variables for sandbox execution."""
        env = os.environ.copy()

        # Add project root to PYTHONPATH for imports
        project_root = Path(__file__).parent.parent.parent.parent
        pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{project_root}:{pythonpath}" if pythonpath else str(project_root)

        # Disable interactive prompts
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        return env

    def run_tests_sync(
        self,
        test_files: List[Path],
        working_dir: Optional[Path] = None
    ) -> SandboxResult:
        """Synchronous wrapper for run_tests."""
        return asyncio.run(self.run_tests(test_files, working_dir))


# Module-level singleton
_runner: Optional[SandboxRunner] = None


def get_sandbox_runner(timeout: int = 30) -> SandboxRunner:
    """Get or create the singleton sandbox runner."""
    global _runner
    if _runner is None or _runner.timeout != timeout:
        _runner = SandboxRunner(timeout=timeout)
    return _runner


async def run_tool_tests(test_files: List[Path], working_dir: Optional[Path] = None) -> SandboxResult:
    """Convenience function to run tool tests."""
    runner = get_sandbox_runner()
    return await runner.run_tests(test_files, working_dir)
