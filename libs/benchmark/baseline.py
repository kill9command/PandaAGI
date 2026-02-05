"""
Baseline Manager - Save and compare benchmark baselines.

Tracks historical benchmark results and calculates deltas.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Baseline:
    """Stored baseline from a previous run."""
    timestamp: str
    git_commit: Optional[str]
    git_branch: Optional[str]
    suites: Dict[str, Dict[str, Any]]
    overall_pass_rate: float
    total_tests: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "git_commit": self.git_commit,
            "git_branch": self.git_branch,
            "suites": self.suites,
            "overall_pass_rate": self.overall_pass_rate,
            "total_tests": self.total_tests,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Baseline":
        return cls(
            timestamp=data.get("timestamp", ""),
            git_commit=data.get("git_commit"),
            git_branch=data.get("git_branch"),
            suites=data.get("suites", {}),
            overall_pass_rate=data.get("overall_pass_rate", 0.0),
            total_tests=data.get("total_tests", 0),
        )


@dataclass
class Delta:
    """Difference between current run and baseline."""
    suite_name: str
    baseline_pass_rate: float
    current_pass_rate: float
    delta_pass_rate: float  # Positive = improvement, negative = regression
    baseline_total: int
    current_total: int
    delta_total: int
    is_regression: bool
    threshold: float

    @property
    def delta_percentage(self) -> float:
        """Delta as percentage points."""
        return self.delta_pass_rate * 100


@dataclass
class ComparisonResult:
    """Result of comparing current run to baseline."""
    baseline: Baseline
    deltas: List[Delta]
    overall_delta: float
    has_regression: bool
    regression_suites: List[str]


class BaselineManager:
    """
    Manages benchmark baselines for comparison.

    Features:
    - Save baselines to disk
    - Load most recent baseline
    - Compare current results to baseline
    - Calculate per-suite deltas
    """

    DEFAULT_PATH = Path("benchmarks/baselines")
    BASELINE_FILE = "baseline.json"
    HISTORY_FILE = "history.json"

    def __init__(
        self,
        baselines_dir: Optional[Path] = None,
        thresholds: Optional[Dict[str, float]] = None,
    ):
        """
        Initialize baseline manager.

        Args:
            baselines_dir: Directory to store baselines
            thresholds: Per-suite regression thresholds (default 5%)
        """
        self.baselines_dir = baselines_dir or self.DEFAULT_PATH
        self.thresholds = thresholds or {}
        self.default_threshold = 0.05  # 5% drop triggers regression

    def save_baseline(
        self,
        result: Any,  # BenchmarkResult
        name: Optional[str] = None,
    ) -> Path:
        """
        Save benchmark result as baseline.

        Args:
            result: BenchmarkResult to save
            name: Optional baseline name (default: "latest")

        Returns:
            Path to saved baseline
        """
        self.baselines_dir.mkdir(parents=True, exist_ok=True)

        # Build baseline data
        suites_data = {}
        for suite in result.suites:
            suites_data[suite.name] = {
                "passed": suite.passed,
                "failed": suite.failed,
                "skipped": suite.skipped,
                "total": suite.total,
                "pass_rate": suite.pass_rate,
                "duration_ms": suite.duration_ms,
            }

        baseline = Baseline(
            timestamp=result.timestamp,
            git_commit=result.git_commit,
            git_branch=result.git_branch,
            suites=suites_data,
            overall_pass_rate=result.overall_pass_rate,
            total_tests=result.total_tests,
        )

        # Save current baseline
        baseline_path = self.baselines_dir / self.BASELINE_FILE
        baseline_path.write_text(json.dumps(baseline.to_dict(), indent=2))
        logger.info(f"[BaselineManager] Saved baseline to {baseline_path}")

        # Append to history
        self._append_to_history(baseline)

        return baseline_path

    def load_baseline(self) -> Optional[Baseline]:
        """
        Load the most recent baseline.

        Returns:
            Baseline or None if not found
        """
        baseline_path = self.baselines_dir / self.BASELINE_FILE

        if not baseline_path.exists():
            logger.info("[BaselineManager] No baseline found")
            return None

        try:
            data = json.loads(baseline_path.read_text())
            return Baseline.from_dict(data)
        except Exception as e:
            logger.error(f"[BaselineManager] Failed to load baseline: {e}")
            return None

    def compare(
        self,
        result: Any,  # BenchmarkResult
        baseline: Optional[Baseline] = None,
    ) -> Optional[ComparisonResult]:
        """
        Compare benchmark result to baseline.

        Args:
            result: Current BenchmarkResult
            baseline: Baseline to compare (default: load latest)

        Returns:
            ComparisonResult with deltas, or None if no baseline
        """
        if baseline is None:
            baseline = self.load_baseline()

        if baseline is None:
            return None

        deltas = []
        regression_suites = []

        for suite in result.suites:
            suite_name = suite.name
            baseline_suite = baseline.suites.get(suite_name, {})

            baseline_pass_rate = baseline_suite.get("pass_rate", 0.0)
            baseline_total = baseline_suite.get("total", 0)

            delta_pass_rate = suite.pass_rate - baseline_pass_rate
            delta_total = suite.total - baseline_total

            # Get threshold for this suite
            threshold = self.thresholds.get(suite_name, self.default_threshold)

            # Regression if pass rate dropped by more than threshold
            is_regression = delta_pass_rate < -threshold

            delta = Delta(
                suite_name=suite_name,
                baseline_pass_rate=baseline_pass_rate,
                current_pass_rate=suite.pass_rate,
                delta_pass_rate=delta_pass_rate,
                baseline_total=baseline_total,
                current_total=suite.total,
                delta_total=delta_total,
                is_regression=is_regression,
                threshold=threshold,
            )
            deltas.append(delta)

            if is_regression:
                regression_suites.append(suite_name)

        overall_delta = result.overall_pass_rate - baseline.overall_pass_rate
        has_regression = len(regression_suites) > 0

        return ComparisonResult(
            baseline=baseline,
            deltas=deltas,
            overall_delta=overall_delta,
            has_regression=has_regression,
            regression_suites=regression_suites,
        )

    def _append_to_history(self, baseline: Baseline) -> None:
        """Append baseline to history file."""
        history_path = self.baselines_dir / self.HISTORY_FILE

        history = []
        if history_path.exists():
            try:
                history = json.loads(history_path.read_text())
            except Exception:
                history = []

        # Append and keep last 100 entries
        history.append(baseline.to_dict())
        history = history[-100:]

        history_path.write_text(json.dumps(history, indent=2))

    def get_history(self, limit: int = 10) -> List[Baseline]:
        """
        Get recent baseline history.

        Args:
            limit: Maximum entries to return

        Returns:
            List of Baselines, most recent first
        """
        history_path = self.baselines_dir / self.HISTORY_FILE

        if not history_path.exists():
            return []

        try:
            history = json.loads(history_path.read_text())
            baselines = [Baseline.from_dict(h) for h in history[-limit:]]
            return list(reversed(baselines))  # Most recent first
        except Exception as e:
            logger.error(f"[BaselineManager] Failed to load history: {e}")
            return []

    def clear_history(self) -> None:
        """Clear all baselines and history."""
        import shutil
        if self.baselines_dir.exists():
            shutil.rmtree(self.baselines_dir)
            logger.info("[BaselineManager] Cleared all baselines")
