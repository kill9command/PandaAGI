"""
Regression Gates - Block deploys when benchmarks regress.

Provides configurable thresholds per suite and overall.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class GateResult:
    """Result of checking a regression gate."""
    passed: bool
    suite_name: str
    threshold: float
    current_pass_rate: float
    baseline_pass_rate: float
    delta: float
    message: str


@dataclass
class GateCheckResult:
    """Aggregate result of all gate checks."""
    passed: bool
    gates: List[GateResult]
    failed_gates: List[str]
    summary: str

    @property
    def exit_code(self) -> int:
        """Return exit code for CI (0 = pass, 1 = fail)."""
        return 0 if self.passed else 1


class RegressionGate:
    """
    Regression gate that fails when pass rates drop.

    Features:
    - Per-suite thresholds
    - Overall threshold
    - Minimum test count requirements
    - Configurable strictness
    """

    DEFAULT_THRESHOLDS = {
        "constraint_pipeline": 0.05,  # 5% drop allowed
        "m1_self_extension": 0.10,    # 10% drop allowed
        "m2_apex": 0.10,
        "m3_harness": 0.05,
        "m4_deep_planning": 0.10,
        "phase_contracts": 0.05,
        "mini_benchmarks": 0.05,
        "spreadsheet": 0.10,
        "document": 0.10,
        "pdf": 0.10,
        "email": 0.10,
        "calendar": 0.10,
        "travel": 0.10,
        "shopping": 0.10,
    }

    def __init__(
        self,
        thresholds: Optional[Dict[str, float]] = None,
        default_threshold: float = 0.05,
        min_tests: int = 1,
        require_baseline: bool = False,
    ):
        """
        Initialize regression gate.

        Args:
            thresholds: Per-suite thresholds (fraction, e.g., 0.05 = 5%)
            default_threshold: Default threshold for unlisted suites
            min_tests: Minimum tests required per suite
            require_baseline: Fail if no baseline exists
        """
        self.thresholds = {**self.DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.default_threshold = default_threshold
        self.min_tests = min_tests
        self.require_baseline = require_baseline

    def check(
        self,
        result: Any,  # BenchmarkResult
        comparison: Optional[Any] = None,  # ComparisonResult
    ) -> GateCheckResult:
        """
        Check if benchmark results pass the regression gate.

        Args:
            result: Current BenchmarkResult
            comparison: ComparisonResult from baseline comparison

        Returns:
            GateCheckResult with pass/fail status
        """
        gates = []
        failed_gates = []

        # If no comparison (no baseline), check if that's allowed
        if comparison is None:
            if self.require_baseline:
                return GateCheckResult(
                    passed=False,
                    gates=[],
                    failed_gates=["no_baseline"],
                    summary="FAILED: No baseline exists and require_baseline=True"
                )
            else:
                # No baseline, just check minimum requirements
                for suite in result.suites:
                    if suite.total < self.min_tests:
                        failed_gates.append(suite.name)
                        gates.append(GateResult(
                            passed=False,
                            suite_name=suite.name,
                            threshold=0,
                            current_pass_rate=suite.pass_rate,
                            baseline_pass_rate=0,
                            delta=0,
                            message=f"Suite has {suite.total} tests, minimum is {self.min_tests}"
                        ))
                    else:
                        gates.append(GateResult(
                            passed=True,
                            suite_name=suite.name,
                            threshold=0,
                            current_pass_rate=suite.pass_rate,
                            baseline_pass_rate=0,
                            delta=0,
                            message="No baseline, passed minimum test requirement"
                        ))

                passed = len(failed_gates) == 0
                return GateCheckResult(
                    passed=passed,
                    gates=gates,
                    failed_gates=failed_gates,
                    summary=f"{'PASSED' if passed else 'FAILED'}: No baseline, checked minimum requirements"
                )

        # Check each suite against threshold
        for delta in comparison.deltas:
            threshold = self.thresholds.get(delta.suite_name, self.default_threshold)

            # Check if regression exceeds threshold
            if delta.delta_pass_rate < -threshold:
                passed = False
                message = (
                    f"Regression: {delta.delta_percentage:+.1f}% "
                    f"(threshold: -{threshold*100:.0f}%)"
                )
                failed_gates.append(delta.suite_name)
            else:
                passed = True
                if delta.delta_pass_rate >= 0:
                    message = f"Improved: {delta.delta_percentage:+.1f}%"
                else:
                    message = f"Minor drop: {delta.delta_percentage:+.1f}% (within threshold)"

            gates.append(GateResult(
                passed=passed,
                suite_name=delta.suite_name,
                threshold=threshold,
                current_pass_rate=delta.current_pass_rate,
                baseline_pass_rate=delta.baseline_pass_rate,
                delta=delta.delta_pass_rate,
                message=message,
            ))

        # Overall result
        all_passed = len(failed_gates) == 0

        if all_passed:
            summary = f"PASSED: All {len(gates)} suites within thresholds"
        else:
            summary = f"FAILED: {len(failed_gates)} suite(s) regressed: {', '.join(failed_gates)}"

        return GateCheckResult(
            passed=all_passed,
            gates=gates,
            failed_gates=failed_gates,
            summary=summary,
        )

    def get_threshold(self, suite_name: str) -> float:
        """Get threshold for a suite."""
        return self.thresholds.get(suite_name, self.default_threshold)


def check_regression(
    result: Any,  # BenchmarkResult
    comparison: Optional[Any] = None,  # ComparisonResult
    thresholds: Optional[Dict[str, float]] = None,
) -> GateCheckResult:
    """
    Convenience function to check regression.

    Args:
        result: Current BenchmarkResult
        comparison: ComparisonResult from baseline
        thresholds: Custom thresholds

    Returns:
        GateCheckResult
    """
    gate = RegressionGate(thresholds=thresholds)
    return gate.check(result, comparison)
