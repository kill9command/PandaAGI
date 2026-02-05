#!/usr/bin/env python
"""
Run benchmark suite with baseline comparison and regression gates.

Usage:
    python scripts/run_benchmark.py              # Run all suites
    python scripts/run_benchmark.py --save       # Run and save as baseline
    python scripts/run_benchmark.py --suite m1   # Run specific suite
    python scripts/run_benchmark.py --report     # Generate report only (no gate check)
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from libs.benchmark import (
    BenchmarkRunner,
    BaselineManager,
    RegressionGate,
    ReportGenerator,
)


def main():
    parser = argparse.ArgumentParser(description="Run benchmark suite")
    parser.add_argument(
        "--suites",
        "-s",
        nargs="+",
        help="Specific suites to run (default: all)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save result as new baseline",
    )
    parser.add_argument(
        "--no-gate",
        action="store_true",
        help="Skip regression gate check",
    )
    parser.add_argument(
        "--threshold",
        "-t",
        type=float,
        default=0.05,
        help="Default regression threshold (default: 0.05 = 5%%)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("benchmarks/reports"),
        help="Output directory for reports",
    )
    parser.add_argument(
        "--baselines-dir",
        "-b",
        type=Path,
        default=Path("benchmarks/baselines"),
        help="Directory for baselines",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Panda Benchmark Suite")
    print("=" * 60)
    print()

    # Run benchmarks
    runner = BenchmarkRunner()
    print(f"Running suites: {args.suites or 'all'}")
    result = runner.run_all(suite_names=args.suites)

    print(f"\nCompleted in {result.duration_ms/1000:.2f}s")
    print(f"  Total: {result.total_tests} tests")
    print(f"  Passed: {result.total_passed}")
    print(f"  Failed: {result.total_failed}")
    print(f"  Skipped: {result.total_skipped}")
    print(f"  Pass Rate: {result.overall_pass_rate*100:.1f}%")
    print()

    # Baseline comparison
    baseline_mgr = BaselineManager(baselines_dir=args.baselines_dir)
    comparison = baseline_mgr.compare(result)

    if comparison:
        print("Baseline Comparison:")
        print(f"  Baseline: {comparison.baseline.timestamp}")
        print(f"  Overall Delta: {comparison.overall_delta*100:+.1f}%")
        if comparison.has_regression:
            print(f"  Regressions: {', '.join(comparison.regression_suites)}")
        print()

    # Gate check
    gate_result = None
    if not args.no_gate:
        gate = RegressionGate(default_threshold=args.threshold)
        gate_result = gate.check(result, comparison)
        print(f"Regression Gate: {gate_result.summary}")
        print()

    # Generate report
    generator = ReportGenerator(output_dir=args.output_dir)
    report = generator.generate(result, comparison, gate_result)
    paths = generator.save(report)

    print("Reports saved:")
    for name, path in paths.items():
        print(f"  {name}: {path}")
    print()

    # Save as baseline if requested
    if args.save:
        baseline_path = baseline_mgr.save_baseline(result)
        print(f"Saved as baseline: {baseline_path}")
        print()

    # Print summary
    print("=" * 60)
    print(report.summary)
    print("=" * 60)

    # Return exit code
    if gate_result:
        return gate_result.exit_code
    return 0 if result.total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
