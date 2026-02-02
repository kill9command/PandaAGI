#!/usr/bin/env python3
"""
scripts/aggregate_daily_metrics.py

Daily Metrics Aggregation Script

Aggregates per-turn metrics.json files into daily rollups and updates
the trends.db SQLite database for trend analysis.

Architecture reference: panda_system_docs/architecture/main-system-patterns/
                       OBSERVABILITY_SYSTEM.md

Usage:
    python scripts/aggregate_daily_metrics.py                    # Aggregate today
    python scripts/aggregate_daily_metrics.py --date 2025-12-28  # Specific date
    python scripts/aggregate_daily_metrics.py --backfill 7       # Last N days

ARCHITECTURAL DECISION (2025-12-30):
Created as part of Tier 8 (Observability) implementation.
"""

import argparse
import json
import logging
import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Paths
TURNS_DIR = Path(os.getenv("TURNS_DIR", "panda_system_docs/turns"))
OBSERVABILITY_DIR = Path(os.getenv("OBSERVABILITY_DIR", "panda_system_docs/observability"))
TRENDS_DB_PATH = OBSERVABILITY_DIR / "trends.db"
DAILY_DIR = OBSERVABILITY_DIR / "daily"


@dataclass
class DailyMetrics:
    """Aggregated metrics for a single day."""
    date: str  # YYYY-MM-DD

    # Turn counts
    total_turns: int = 0
    successful_turns: int = 0  # APPROVE
    failed_turns: int = 0       # FAIL
    retry_turns: int = 0        # RETRY
    revise_turns: int = 0       # REVISE

    # Timing averages (ms)
    avg_duration_ms: float = 0.0
    max_duration_ms: int = 0
    min_duration_ms: int = 0
    total_duration_ms: int = 0

    # Token usage averages
    avg_tokens_total: float = 0.0
    total_tokens: int = 0

    # Phase breakdown (average % of total time)
    phase_timing_pct: Dict[str, float] = field(default_factory=dict)

    # Tool usage
    tool_calls_total: int = 0
    tool_success_rate: float = 0.0
    tools_used: Dict[str, int] = field(default_factory=dict)

    # Quality
    avg_quality_score: float = 0.0
    avg_confidence: float = 0.0

    # Site metrics
    sites_visited: Dict[str, int] = field(default_factory=dict)
    site_success_rates: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def ensure_db():
    """Ensure trends.db exists with proper schema."""
    OBSERVABILITY_DIR.mkdir(parents=True, exist_ok=True)
    DAILY_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(TRENDS_DB_PATH)
    cursor = conn.cursor()

    # Daily metrics table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_metrics (
            date TEXT PRIMARY KEY,
            total_turns INTEGER,
            successful_turns INTEGER,
            failed_turns INTEGER,
            retry_turns INTEGER,
            revise_turns INTEGER,
            avg_duration_ms REAL,
            max_duration_ms INTEGER,
            min_duration_ms INTEGER,
            total_duration_ms INTEGER,
            avg_tokens_total REAL,
            total_tokens INTEGER,
            tool_calls_total INTEGER,
            tool_success_rate REAL,
            avg_quality_score REAL,
            avg_confidence REAL,
            created_at REAL
        )
    """)

    # Daily tool metrics table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_tool_metrics (
            date TEXT,
            tool_name TEXT,
            call_count INTEGER,
            success_count INTEGER,
            avg_duration_ms REAL,
            PRIMARY KEY (date, tool_name)
        )
    """)

    # Daily site metrics table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_site_metrics (
            date TEXT,
            site TEXT,
            visit_count INTEGER,
            success_count INTEGER,
            avg_extraction_time_ms REAL,
            PRIMARY KEY (date, site)
        )
    """)

    # Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_metrics(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_date ON daily_tool_metrics(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_site_date ON daily_site_metrics(date)")

    conn.commit()
    conn.close()
    logger.info(f"Ensured trends.db at {TRENDS_DB_PATH}")


def get_turns_for_date(date: str) -> List[Path]:
    """Get all turn directories for a specific date."""
    turns = []

    if not TURNS_DIR.exists():
        logger.warning(f"Turns directory not found: {TURNS_DIR}")
        return turns

    # Parse target date
    target_date = datetime.strptime(date, "%Y-%m-%d").date()

    for turn_dir in TURNS_DIR.iterdir():
        if not turn_dir.is_dir() or not turn_dir.name.startswith("turn_"):
            continue

        metrics_path = turn_dir / "metrics.json"
        if not metrics_path.exists():
            continue

        # Check if this turn is from the target date
        try:
            with open(metrics_path) as f:
                metrics = json.load(f)

            # Check timestamp field
            timestamp = metrics.get("timestamp") or metrics.get("created_at")
            if timestamp:
                if isinstance(timestamp, (int, float)):
                    turn_date = datetime.fromtimestamp(timestamp).date()
                else:
                    turn_date = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date()

                if turn_date == target_date:
                    turns.append(turn_dir)
        except Exception as e:
            logger.warning(f"Error reading {metrics_path}: {e}")
            continue

    return turns


def aggregate_day(date: str) -> DailyMetrics:
    """Aggregate all metrics for a specific date."""
    metrics = DailyMetrics(date=date)
    turns = get_turns_for_date(date)

    if not turns:
        logger.info(f"No turns found for {date}")
        return metrics

    # Accumulators
    durations = []
    tokens = []
    quality_scores = []
    confidences = []
    phase_timings = defaultdict(list)
    tool_calls = defaultdict(lambda: {"total": 0, "success": 0})
    site_visits = defaultdict(lambda: {"total": 0, "success": 0})
    validation_outcomes = defaultdict(int)

    for turn_dir in turns:
        metrics_path = turn_dir / "metrics.json"

        try:
            with open(metrics_path) as f:
                turn_metrics = json.load(f)
        except Exception as e:
            logger.warning(f"Error reading {metrics_path}: {e}")
            continue

        metrics.total_turns += 1

        # Duration
        duration = turn_metrics.get("total_duration_ms", 0)
        if duration:
            durations.append(duration)

        # Tokens
        total_tokens = turn_metrics.get("total_tokens", 0)
        if total_tokens:
            tokens.append(total_tokens)

        # Validation outcome
        outcome = turn_metrics.get("validation_outcome", "")
        if outcome:
            validation_outcomes[outcome] += 1

        # Quality/confidence
        quality = turn_metrics.get("quality_score", 0)
        if quality:
            quality_scores.append(quality)

        confidence = turn_metrics.get("confidence", 0)
        if confidence:
            confidences.append(confidence)

        # Phase timings (if available)
        phases = turn_metrics.get("phases", [])
        for phase in phases:
            phase_name = phase.get("phase", "unknown")
            pct = phase.get("duration_pct", 0)
            if pct:
                phase_timings[phase_name].append(pct)

        # Tool calls
        tools_called = turn_metrics.get("tools_called", [])
        for tool in tools_called:
            name = tool.get("tool_name", "unknown")
            tool_calls[name]["total"] += 1
            if tool.get("success", True):
                tool_calls[name]["success"] += 1

        # Site visits
        sites = turn_metrics.get("sites_visited", [])
        for site in sites:
            domain = site.get("domain", "unknown")
            site_visits[domain]["total"] += 1
            if site.get("success", True):
                site_visits[domain]["success"] += 1

    # Calculate aggregates
    if durations:
        metrics.avg_duration_ms = sum(durations) / len(durations)
        metrics.max_duration_ms = max(durations)
        metrics.min_duration_ms = min(durations)
        metrics.total_duration_ms = sum(durations)

    if tokens:
        metrics.avg_tokens_total = sum(tokens) / len(tokens)
        metrics.total_tokens = sum(tokens)

    if quality_scores:
        metrics.avg_quality_score = sum(quality_scores) / len(quality_scores)

    if confidences:
        metrics.avg_confidence = sum(confidences) / len(confidences)

    # Validation outcomes
    metrics.successful_turns = validation_outcomes.get("APPROVE", 0)
    metrics.failed_turns = validation_outcomes.get("FAIL", 0)
    metrics.retry_turns = validation_outcomes.get("RETRY", 0)
    metrics.revise_turns = validation_outcomes.get("REVISE", 0)

    # Phase timing percentages (averages)
    for phase_name, pcts in phase_timings.items():
        metrics.phase_timing_pct[phase_name] = sum(pcts) / len(pcts)

    # Tool usage
    total_tool_calls = sum(t["total"] for t in tool_calls.values())
    total_tool_successes = sum(t["success"] for t in tool_calls.values())
    metrics.tool_calls_total = total_tool_calls
    if total_tool_calls > 0:
        metrics.tool_success_rate = total_tool_successes / total_tool_calls
    metrics.tools_used = {k: v["total"] for k, v in tool_calls.items()}

    # Site metrics
    metrics.sites_visited = {k: v["total"] for k, v in site_visits.items()}
    metrics.site_success_rates = {
        k: v["success"] / v["total"] if v["total"] > 0 else 0.0
        for k, v in site_visits.items()
    }

    logger.info(f"Aggregated {metrics.total_turns} turns for {date}")
    return metrics


def save_daily_json(metrics: DailyMetrics):
    """Save daily metrics to JSON file."""
    output_path = DAILY_DIR / f"{metrics.date}.json"

    with open(output_path, 'w') as f:
        json.dump(metrics.to_dict(), f, indent=2)

    logger.info(f"Saved daily JSON to {output_path}")


def save_to_trends_db(metrics: DailyMetrics):
    """Save daily metrics to trends.db."""
    conn = sqlite3.connect(TRENDS_DB_PATH)
    cursor = conn.cursor()

    # Insert/replace daily metrics
    cursor.execute("""
        INSERT OR REPLACE INTO daily_metrics
        (date, total_turns, successful_turns, failed_turns, retry_turns, revise_turns,
         avg_duration_ms, max_duration_ms, min_duration_ms, total_duration_ms,
         avg_tokens_total, total_tokens, tool_calls_total, tool_success_rate,
         avg_quality_score, avg_confidence, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        metrics.date,
        metrics.total_turns,
        metrics.successful_turns,
        metrics.failed_turns,
        metrics.retry_turns,
        metrics.revise_turns,
        metrics.avg_duration_ms,
        metrics.max_duration_ms,
        metrics.min_duration_ms,
        metrics.total_duration_ms,
        metrics.avg_tokens_total,
        metrics.total_tokens,
        metrics.tool_calls_total,
        metrics.tool_success_rate,
        metrics.avg_quality_score,
        metrics.avg_confidence,
        datetime.now().timestamp()
    ))

    # Insert tool metrics
    for tool_name, count in metrics.tools_used.items():
        cursor.execute("""
            INSERT OR REPLACE INTO daily_tool_metrics
            (date, tool_name, call_count, success_count, avg_duration_ms)
            VALUES (?, ?, ?, ?, ?)
        """, (metrics.date, tool_name, count, 0, 0))  # TODO: track per-tool success/timing

    # Insert site metrics
    for site, count in metrics.sites_visited.items():
        success_rate = metrics.site_success_rates.get(site, 0)
        cursor.execute("""
            INSERT OR REPLACE INTO daily_site_metrics
            (date, site, visit_count, success_count, avg_extraction_time_ms)
            VALUES (?, ?, ?, ?, ?)
        """, (metrics.date, site, count, int(count * success_rate), 0))

    conn.commit()
    conn.close()
    logger.info(f"Saved to trends.db for {metrics.date}")


def main():
    parser = argparse.ArgumentParser(description="Aggregate daily metrics")
    parser.add_argument("--date", help="Specific date to aggregate (YYYY-MM-DD)")
    parser.add_argument("--backfill", type=int, help="Backfill last N days")
    args = parser.parse_args()

    # Ensure database exists
    ensure_db()

    # Determine dates to process
    dates_to_process = []

    if args.date:
        dates_to_process.append(args.date)
    elif args.backfill:
        today = datetime.now().date()
        for i in range(args.backfill):
            date = today - timedelta(days=i)
            dates_to_process.append(date.strftime("%Y-%m-%d"))
    else:
        # Default: today
        dates_to_process.append(datetime.now().strftime("%Y-%m-%d"))

    # Process each date
    for date in dates_to_process:
        logger.info(f"Processing {date}...")
        metrics = aggregate_day(date)

        if metrics.total_turns > 0:
            save_daily_json(metrics)
            save_to_trends_db(metrics)
        else:
            logger.info(f"No data to save for {date}")

    logger.info("Done!")


if __name__ == "__main__":
    main()
