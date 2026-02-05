"""
Report Generator - Generate benchmark reports in JSON and Markdown.

Produces:
- JSON report for CI/automation
- Markdown report for human review
- Summary for console output
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkReport:
    """Generated benchmark report."""
    json_content: str
    markdown_content: str
    summary: str
    passed: bool
    timestamp: str


class ReportGenerator:
    """
    Generates benchmark reports.

    Features:
    - JSON output for CI integration
    - Markdown for human-readable reports
    - Console summary
    - Configurable output paths
    """

    def __init__(
        self,
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize report generator.

        Args:
            output_dir: Directory for report files
        """
        self.output_dir = output_dir or Path("benchmarks/reports")

    def generate(
        self,
        result: Any,  # BenchmarkResult
        comparison: Optional[Any] = None,  # ComparisonResult
        gate_result: Optional[Any] = None,  # GateCheckResult
    ) -> BenchmarkReport:
        """
        Generate full benchmark report.

        Args:
            result: BenchmarkResult from runner
            comparison: ComparisonResult from baseline comparison
            gate_result: GateCheckResult from regression check

        Returns:
            BenchmarkReport with JSON and Markdown content
        """
        timestamp = result.timestamp

        # Generate JSON
        json_content = self._generate_json(result, comparison, gate_result)

        # Generate Markdown
        markdown_content = self._generate_markdown(result, comparison, gate_result)

        # Generate summary
        summary = self._generate_summary(result, comparison, gate_result)

        passed = gate_result.passed if gate_result else result.total_failed == 0

        return BenchmarkReport(
            json_content=json_content,
            markdown_content=markdown_content,
            summary=summary,
            passed=passed,
            timestamp=timestamp,
        )

    def save(
        self,
        report: BenchmarkReport,
        prefix: str = "benchmark",
    ) -> Dict[str, Path]:
        """
        Save report files to disk.

        Args:
            report: BenchmarkReport to save
            prefix: Filename prefix

        Returns:
            Dict with paths to saved files
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Use timestamp for unique filenames
        ts = datetime.fromisoformat(report.timestamp).strftime("%Y%m%d_%H%M%S")

        paths = {}

        # Save JSON
        json_path = self.output_dir / f"{prefix}_{ts}.json"
        json_path.write_text(report.json_content)
        paths["json"] = json_path

        # Save Markdown
        md_path = self.output_dir / f"{prefix}_{ts}.md"
        md_path.write_text(report.markdown_content)
        paths["markdown"] = md_path

        # Also save as "latest"
        latest_json = self.output_dir / f"{prefix}_latest.json"
        latest_json.write_text(report.json_content)
        paths["latest_json"] = latest_json

        latest_md = self.output_dir / f"{prefix}_latest.md"
        latest_md.write_text(report.markdown_content)
        paths["latest_md"] = latest_md

        logger.info(f"[ReportGenerator] Saved reports to {self.output_dir}")
        return paths

    def _generate_json(
        self,
        result: Any,
        comparison: Optional[Any],
        gate_result: Optional[Any],
    ) -> str:
        """Generate JSON report."""
        report = {
            "timestamp": result.timestamp,
            "git_commit": result.git_commit,
            "git_branch": result.git_branch,
            "summary": {
                "total_tests": result.total_tests,
                "passed": result.total_passed,
                "failed": result.total_failed,
                "skipped": result.total_skipped,
                "pass_rate": round(result.overall_pass_rate, 4),
                "duration_ms": result.duration_ms,
            },
            "suites": [],
            "gate_check": None,
            "comparison": None,
        }

        # Add suite details
        for suite in result.suites:
            suite_data = {
                "name": suite.name,
                "passed": suite.passed,
                "failed": suite.failed,
                "skipped": suite.skipped,
                "total": suite.total,
                "pass_rate": round(suite.pass_rate, 4),
                "duration_ms": suite.duration_ms,
                "error": suite.error,
            }
            report["suites"].append(suite_data)

        # Add gate check results
        if gate_result:
            report["gate_check"] = {
                "passed": gate_result.passed,
                "summary": gate_result.summary,
                "failed_suites": gate_result.failed_gates,
                "gates": [
                    {
                        "suite": g.suite_name,
                        "passed": g.passed,
                        "threshold": g.threshold,
                        "current": round(g.current_pass_rate, 4),
                        "baseline": round(g.baseline_pass_rate, 4),
                        "delta": round(g.delta, 4),
                        "message": g.message,
                    }
                    for g in gate_result.gates
                ],
            }

        # Add comparison
        if comparison:
            report["comparison"] = {
                "baseline_timestamp": comparison.baseline.timestamp,
                "baseline_commit": comparison.baseline.git_commit,
                "overall_delta": round(comparison.overall_delta, 4),
                "has_regression": comparison.has_regression,
                "regression_suites": comparison.regression_suites,
            }

        return json.dumps(report, indent=2)

    def _generate_markdown(
        self,
        result: Any,
        comparison: Optional[Any],
        gate_result: Optional[Any],
    ) -> str:
        """Generate Markdown report."""
        lines = []

        # Header
        passed = gate_result.passed if gate_result else result.total_failed == 0
        status_emoji = "✅" if passed else "❌"
        lines.append(f"# Benchmark Report {status_emoji}")
        lines.append("")
        lines.append(f"**Timestamp:** {result.timestamp}")
        if result.git_commit:
            lines.append(f"**Commit:** `{result.git_commit}` ({result.git_branch})")
        lines.append("")

        # Summary
        lines.append("## Summary")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Total Tests | {result.total_tests} |")
        lines.append(f"| Passed | {result.total_passed} |")
        lines.append(f"| Failed | {result.total_failed} |")
        lines.append(f"| Skipped | {result.total_skipped} |")
        lines.append(f"| Pass Rate | {result.overall_pass_rate*100:.1f}% |")
        lines.append(f"| Duration | {result.duration_ms/1000:.2f}s |")
        lines.append("")

        # Gate check result
        if gate_result:
            lines.append("## Regression Gate")
            lines.append("")
            gate_emoji = "✅" if gate_result.passed else "❌"
            lines.append(f"**Status:** {gate_emoji} {gate_result.summary}")
            lines.append("")

        # Suite results table
        lines.append("## Suite Results")
        lines.append("")
        lines.append("| Suite | Passed | Failed | Total | Pass Rate | Delta | Status |")
        lines.append("|-------|--------|--------|-------|-----------|-------|--------|")

        for suite in result.suites:
            delta_str = ""
            status = "✅" if suite.failed == 0 else "❌"

            if comparison:
                for d in comparison.deltas:
                    if d.suite_name == suite.name:
                        if d.delta_pass_rate >= 0:
                            delta_str = f"+{d.delta_percentage:.1f}%"
                        else:
                            delta_str = f"{d.delta_percentage:.1f}%"
                        if d.is_regression:
                            status = "⚠️"
                        break

            lines.append(
                f"| {suite.name} | {suite.passed} | {suite.failed} | {suite.total} | "
                f"{suite.pass_rate*100:.1f}% | {delta_str} | {status} |"
            )

        lines.append("")

        # Comparison details
        if comparison:
            lines.append("## Baseline Comparison")
            lines.append("")
            lines.append(f"**Baseline:** {comparison.baseline.timestamp}")
            if comparison.baseline.git_commit:
                lines.append(f"**Baseline Commit:** `{comparison.baseline.git_commit}`")
            lines.append(f"**Overall Delta:** {comparison.overall_delta*100:+.1f}%")
            lines.append("")

            if comparison.has_regression:
                lines.append("### Regressions Detected")
                lines.append("")
                for suite_name in comparison.regression_suites:
                    lines.append(f"- {suite_name}")
                lines.append("")

        # Footer
        lines.append("---")
        lines.append(f"*Generated by Pandora Benchmark Harness*")

        return "\n".join(lines)

    def _generate_summary(
        self,
        result: Any,
        comparison: Optional[Any],
        gate_result: Optional[Any],
    ) -> str:
        """Generate console summary."""
        lines = []

        passed = gate_result.passed if gate_result else result.total_failed == 0
        status = "PASSED" if passed else "FAILED"

        lines.append(f"Benchmark {status}")
        lines.append(f"  Tests: {result.total_passed}/{result.total_tests} passed ({result.overall_pass_rate*100:.1f}%)")
        lines.append(f"  Duration: {result.duration_ms/1000:.2f}s")

        if comparison:
            delta_str = f"{comparison.overall_delta*100:+.1f}%"
            lines.append(f"  Delta: {delta_str} vs baseline")

            if comparison.has_regression:
                lines.append(f"  Regressions: {', '.join(comparison.regression_suites)}")

        if gate_result:
            lines.append(f"  Gate: {gate_result.summary}")

        return "\n".join(lines)
