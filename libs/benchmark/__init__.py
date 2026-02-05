"""
Benchmark Harness - Run task suites with scoring, baselines, and regression gates.

Implements M3 (Benchmark Harness) from architecture/README.md:
- Harness runs task suites with scores, outputs, and deltas
- Regression gate blocks drops > X% across core suites
- Automated report produced per run with pass/fail thresholds

Usage:
    from libs.benchmark import BenchmarkRunner, run_benchmarks

    runner = BenchmarkRunner()
    results = runner.run_all()
    report = runner.generate_report(results)
"""

from libs.benchmark.runner import (
    BenchmarkRunner,
    SuiteResult,
    TestResult,
    run_benchmarks,
)

from libs.benchmark.baseline import (
    BaselineManager,
    Baseline,
    Delta,
)

from libs.benchmark.gates import (
    RegressionGate,
    GateResult,
    check_regression,
)

from libs.benchmark.reporter import (
    ReportGenerator,
    BenchmarkReport,
)

__all__ = [
    # Runner
    "BenchmarkRunner",
    "SuiteResult",
    "TestResult",
    "run_benchmarks",
    # Baseline
    "BaselineManager",
    "Baseline",
    "Delta",
    # Gates
    "RegressionGate",
    "GateResult",
    "check_regression",
    # Reporter
    "ReportGenerator",
    "BenchmarkReport",
]
