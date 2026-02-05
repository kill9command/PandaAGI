"""
Source Reliability Tracker

SQLite-based tracking of source reliability for confidence calibration.
Tracks success/failure rates per domain to adjust extraction confidence.

Architecture reference: panda_system_docs/architecture/main-system-patterns/
                       UNIVERSAL_CONFIDENCE_SYSTEM.md
"""

import sqlite3
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from contextlib import contextmanager
from urllib.parse import urlparse
import json


DB_PATH = "panda_system_docs/source_reliability.db"

# Reliability thresholds
RELIABILITY_CONFIG = {
    "min_samples": 5,           # Minimum extractions before reliability is calculated
    "decay_days": 30,           # Older records weight less
    "high_reliability": 0.85,   # >= this is "reliable"
    "low_reliability": 0.50,    # <= this is "unreliable"
    "default_reliability": 0.70,  # Before enough samples
}


@dataclass
class SourceStats:
    """Statistics for a source domain"""
    domain: str
    total_extractions: int
    successful_extractions: int
    failed_extractions: int
    reliability_score: float
    last_success: Optional[float]  # Unix timestamp
    last_failure: Optional[float]
    extraction_types: Dict[str, int]  # e.g., {"price": 50, "title": 48}


class SourceReliabilityTracker:
    """
    Tracks extraction reliability per source domain.
    Used to adjust confidence based on historical success rates.
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._ensure_db()

    def _ensure_db(self):
        """Ensure database and tables exist"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Main extractions log table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS extraction_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    extraction_type TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    confidence REAL,
                    timestamp REAL NOT NULL,
                    url TEXT,
                    error_type TEXT,
                    metadata TEXT
                )
            """)

            # Aggregated stats table (updated periodically)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS domain_stats (
                    domain TEXT PRIMARY KEY,
                    total_extractions INTEGER DEFAULT 0,
                    successful INTEGER DEFAULT 0,
                    failed INTEGER DEFAULT 0,
                    reliability_score REAL DEFAULT 0.7,
                    last_success REAL,
                    last_failure REAL,
                    extraction_types TEXT DEFAULT '{}',
                    updated_at REAL
                )
            """)

            # Indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_log_domain
                ON extraction_log(domain)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_log_timestamp
                ON extraction_log(timestamp)
            """)

            conn.commit()

    @contextmanager
    def _get_connection(self):
        """Get database connection with context manager"""
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def log_extraction(
        self,
        url: str,
        extraction_type: str,
        success: bool,
        confidence: float = 0.0,
        error_type: Optional[str] = None,
        metadata: Optional[Dict] = None
    ):
        """
        Log an extraction attempt.

        Args:
            url: Full URL of the page
            extraction_type: Type of extraction ("price", "title", "availability", etc.)
            success: Whether extraction succeeded
            confidence: Confidence score of the extraction
            error_type: Type of error if failed
            metadata: Additional metadata
        """
        domain = self._extract_domain(url)
        timestamp = time.time()

        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO extraction_log
                (domain, extraction_type, success, confidence, timestamp, url, error_type, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                domain,
                extraction_type,
                1 if success else 0,
                confidence,
                timestamp,
                url,
                error_type,
                json.dumps(metadata) if metadata else None
            ))

            conn.commit()

        # Update aggregated stats
        self._update_domain_stats(domain)

    def get_reliability(self, url_or_domain: str) -> float:
        """
        Get reliability score for a domain.

        Returns:
            Reliability score 0.0-1.0
        """
        domain = self._extract_domain(url_or_domain)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT reliability_score, total_extractions
                FROM domain_stats
                WHERE domain = ?
            """, (domain,))

            row = cursor.fetchone()
            if not row or row["total_extractions"] < RELIABILITY_CONFIG["min_samples"]:
                return RELIABILITY_CONFIG["default_reliability"]

            return row["reliability_score"]

    def get_domain_stats(self, url_or_domain: str) -> Optional[SourceStats]:
        """Get full statistics for a domain"""
        domain = self._extract_domain(url_or_domain)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM domain_stats WHERE domain = ?
            """, (domain,))

            row = cursor.fetchone()
            if not row:
                return None

            return SourceStats(
                domain=row["domain"],
                total_extractions=row["total_extractions"],
                successful_extractions=row["successful"],
                failed_extractions=row["failed"],
                reliability_score=row["reliability_score"],
                last_success=row["last_success"],
                last_failure=row["last_failure"],
                extraction_types=json.loads(row["extraction_types"] or "{}")
            )

    def adjust_confidence(
        self,
        url: str,
        base_confidence: float,
        extraction_type: str = "generic"
    ) -> float:
        """
        Adjust extraction confidence based on source reliability.

        Args:
            url: Source URL
            base_confidence: Initial confidence from extraction
            extraction_type: Type of extraction

        Returns:
            Adjusted confidence score
        """
        reliability = self.get_reliability(url)

        # Scale base confidence by reliability
        # High reliability boosts, low reliability dampens
        if reliability >= RELIABILITY_CONFIG["high_reliability"]:
            # Reliable source - boost slightly
            adjusted = base_confidence * 1.1
        elif reliability <= RELIABILITY_CONFIG["low_reliability"]:
            # Unreliable source - dampen
            adjusted = base_confidence * 0.8
        else:
            # Normal reliability - minor adjustment
            adjustment = (reliability - 0.7) / 0.3  # -1 to +0.5 range
            adjusted = base_confidence * (1 + adjustment * 0.1)

        return max(0.0, min(1.0, adjusted))

    def get_unreliable_domains(
        self,
        threshold: Optional[float] = None
    ) -> List[SourceStats]:
        """Get list of unreliable domains"""
        threshold = threshold or RELIABILITY_CONFIG["low_reliability"]

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM domain_stats
                WHERE reliability_score <= ?
                AND total_extractions >= ?
                ORDER BY reliability_score ASC
            """, (threshold, RELIABILITY_CONFIG["min_samples"]))

            return [
                SourceStats(
                    domain=row["domain"],
                    total_extractions=row["total_extractions"],
                    successful_extractions=row["successful"],
                    failed_extractions=row["failed"],
                    reliability_score=row["reliability_score"],
                    last_success=row["last_success"],
                    last_failure=row["last_failure"],
                    extraction_types=json.loads(row["extraction_types"] or "{}")
                )
                for row in cursor.fetchall()
            ]

    def get_top_domains(self, limit: int = 20) -> List[SourceStats]:
        """Get most reliable domains"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM domain_stats
                WHERE total_extractions >= ?
                ORDER BY reliability_score DESC, total_extractions DESC
                LIMIT ?
            """, (RELIABILITY_CONFIG["min_samples"], limit))

            return [
                SourceStats(
                    domain=row["domain"],
                    total_extractions=row["total_extractions"],
                    successful_extractions=row["successful"],
                    failed_extractions=row["failed"],
                    reliability_score=row["reliability_score"],
                    last_success=row["last_success"],
                    last_failure=row["last_failure"],
                    extraction_types=json.loads(row["extraction_types"] or "{}")
                )
                for row in cursor.fetchall()
            ]

    def _update_domain_stats(self, domain: str):
        """Update aggregated stats for a domain"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Calculate time-weighted stats
            cutoff = time.time() - (RELIABILITY_CONFIG["decay_days"] * 86400)

            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(success) as successes,
                    MAX(CASE WHEN success = 1 THEN timestamp END) as last_success,
                    MAX(CASE WHEN success = 0 THEN timestamp END) as last_failure
                FROM extraction_log
                WHERE domain = ? AND timestamp > ?
            """, (domain, cutoff))

            row = cursor.fetchone()
            total = row["total"] or 0
            successes = row["successes"] or 0
            failures = total - successes
            last_success = row["last_success"]
            last_failure = row["last_failure"]

            # Calculate reliability score
            if total >= RELIABILITY_CONFIG["min_samples"]:
                reliability = successes / total
            else:
                reliability = RELIABILITY_CONFIG["default_reliability"]

            # Get extraction type breakdown
            cursor.execute("""
                SELECT extraction_type, COUNT(*) as cnt
                FROM extraction_log
                WHERE domain = ? AND timestamp > ?
                GROUP BY extraction_type
            """, (domain, cutoff))

            extraction_types = {
                row["extraction_type"]: row["cnt"]
                for row in cursor.fetchall()
            }

            # Upsert domain stats
            cursor.execute("""
                INSERT INTO domain_stats
                (domain, total_extractions, successful, failed, reliability_score,
                 last_success, last_failure, extraction_types, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(domain) DO UPDATE SET
                    total_extractions = excluded.total_extractions,
                    successful = excluded.successful,
                    failed = excluded.failed,
                    reliability_score = excluded.reliability_score,
                    last_success = excluded.last_success,
                    last_failure = excluded.last_failure,
                    extraction_types = excluded.extraction_types,
                    updated_at = excluded.updated_at
            """, (
                domain, total, successes, failures, reliability,
                last_success, last_failure, json.dumps(extraction_types), time.time()
            ))

            conn.commit()

    def _extract_domain(self, url_or_domain: str) -> str:
        """Extract domain from URL or return as-is if already domain"""
        if "://" in url_or_domain:
            parsed = urlparse(url_or_domain)
            return parsed.netloc.lower()
        return url_or_domain.lower()

    def cleanup_old_records(self, days: int = 90):
        """Remove extraction logs older than specified days"""
        cutoff = time.time() - (days * 86400)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM extraction_log WHERE timestamp < ?
            """, (cutoff,))
            deleted = cursor.rowcount
            conn.commit()

        return deleted


# Singleton instance
_tracker_instance: Optional[SourceReliabilityTracker] = None


def get_tracker() -> SourceReliabilityTracker:
    """Get singleton tracker instance"""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = SourceReliabilityTracker()
    return _tracker_instance
