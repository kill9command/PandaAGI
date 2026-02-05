"""
Persistent claim registry with delta computation.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .freshness import FreshnessOracle
from .schema import CapsuleArtifact, CapsuleClaim, CapsuleDelta, DistilledCapsule


@dataclass(frozen=True)
class ClaimRow:
    claim_id: str
    session_id: str
    ticket_id: str
    statement: str
    evidence: Sequence[str]
    confidence: str
    fingerprint: str
    last_verified: str
    ttl_seconds: int
    expires_at: str
    metadata: Dict[str, Any]
    created_at: float
    updated_at: float


class ClaimRegistry:
    def __init__(self, db_path: str | Path, *, freshness: Optional[FreshnessOracle] = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._ensure_tables()
        self.freshness = freshness or FreshnessOracle()

    # ------------------------------------------------------------------ #
    # Public API

    def record_capsule(
        self,
        *,
        session_id: str,
        turn_id: str,
        ticket_id: str,
        capsule: DistilledCapsule,
    ) -> CapsuleDelta:
        if not session_id:
            raise ValueError("session_id is required")
        now_ts = time.time()
        now_iso = datetime.now(timezone.utc).isoformat()
        delta_claims: List[CapsuleClaim] = []

        normalized_claims: List[CapsuleClaim] = []
        for claim_obj in capsule.claims:
            c = CapsuleClaim.model_validate(claim_obj)
            if not c.evidence:
                continue
            fingerprint = self.fingerprint(c)
            claim_id = c.claim_id or self._derive_claim_id(c, fingerprint)
            ttl_seconds = c.ttl_seconds or self.freshness.suggest_ttl_seconds(c.confidence)
            last_verified = c.last_verified or now_iso
            expires_at = self.freshness.expiry_timestamp(last_verified=last_verified, ttl_seconds=ttl_seconds).isoformat()
            metadata = dict(c.metadata or {})

            changed = self._upsert_claim(
                claim_id=claim_id,
                session_id=session_id,
                ticket_id=ticket_id,
                statement=c.claim,
                evidence=c.evidence,
                confidence=c.confidence,
                fingerprint=fingerprint,
                last_verified=last_verified,
                ttl_seconds=ttl_seconds,
                expires_at=expires_at,
                metadata=metadata,
                created_ts=now_ts,
                turn_id=turn_id,
            )
            c.claim_id = claim_id
            c.ttl_seconds = ttl_seconds
            c.last_verified = last_verified
            c.metadata = metadata
            normalized_claims.append(c)
            if changed:
                delta_claims.append(c)

        normalized_capsule = DistilledCapsule.model_validate(
            capsule.model_copy(update={"claims": normalized_claims})
        )

        new_artifacts = self._record_artifacts(session_id=session_id, artifacts=normalized_capsule.artifacts, seen_ts=now_ts)

        return CapsuleDelta(base=normalized_capsule, claims=delta_claims, artifacts=new_artifacts)

    def list_active_claims(self, *, session_id: Optional[str] = None) -> Iterable[ClaimRow]:
        where = ""
        params: List[Any] = []
        if session_id:
            where = "WHERE session_id = ?"
            params.append(session_id)
        cursor = self._conn.execute(
            f"""
            SELECT claim_id, session_id, ticket_id, statement, evidence, confidence,
                   fingerprint, last_verified, ttl_seconds, expires_at,
                   metadata, created_at, updated_at
            FROM claims
            {where}
            ORDER BY updated_at DESC
            """,
            params,
        )
        for row in cursor.fetchall():
            # Parse metadata and skip archived claims
            metadata = json.loads(row[10]) if row[10] else {}
            if metadata.get("archived", False):
                continue  # Skip archived claims

            yield ClaimRow(
                claim_id=row[0],
                session_id=row[1],
                ticket_id=row[2],
                statement=row[3],
                evidence=json.loads(row[4]) if row[4] else [],
                confidence=row[5],
                fingerprint=row[6],
                last_verified=row[7],
                ttl_seconds=int(row[8]),
                expires_at=row[9],
                metadata=metadata,
                created_at=float(row[11]),
                updated_at=float(row[12]),
            )

    def delete_claims(self, claim_ids: Sequence[str]) -> int:
        if not claim_ids:
            return 0
        placeholders = ",".join("?" for _ in claim_ids)
        with self._lock:
            cur = self._conn.execute(
                f"DELETE FROM claims WHERE claim_id IN ({placeholders})",
                tuple(claim_ids),
            )
            self._conn.commit()
            return cur.rowcount

    def archive_claims(self, claim_ids: Sequence[str]) -> int:
        """Mark claims as archived instead of deleting them.

        Archived claims are excluded from active queries but retained for analysis.
        Updates the metadata JSON field to add archived=True and archived_at timestamp.
        """
        if not claim_ids:
            return 0

        import json
        from datetime import datetime, timezone
        archived_at = datetime.now(timezone.utc).isoformat()

        with self._lock:
            count = 0
            for claim_id in claim_ids:
                # Get current metadata
                cur = self._conn.execute(
                    "SELECT metadata FROM claims WHERE claim_id = ?",
                    (claim_id,)
                )
                row = cur.fetchone()
                if not row:
                    continue

                # Parse and update metadata
                metadata = json.loads(row[0]) if row[0] else {}
                metadata["archived"] = True
                metadata["archived_at"] = archived_at

                # Update claim
                self._conn.execute(
                    "UPDATE claims SET metadata = ? WHERE claim_id = ?",
                    (json.dumps(metadata), claim_id)
                )
                count += 1

            self._conn.commit()
            return count

    def delete_claims_for_session(self, session_id: str) -> int:
        if not session_id:
            return 0
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM claims WHERE session_id = ?",
                (session_id,),
            )
            self._conn.commit()
            return cur.rowcount

    # ------------------------------------------------------------------ #
    # Topic-aware methods (Session Knowledge System)

    def get_claims_for_topics(
        self,
        topic_ids: List[str],
        session_id: str,
        claim_types: Optional[List[str]] = None,
        min_confidence: Optional[str] = None,
        exclude_expired: bool = True,
    ) -> List[ClaimRow]:
        """
        Retrieve claims belonging to specified topics.

        Args:
            topic_ids: List of topic IDs to query
            session_id: Session scope
            claim_types: Filter by claim types (optional)
            min_confidence: Minimum confidence filter (optional)
            exclude_expired: Exclude expired claims (default True)

        Returns:
            List of matching claims
        """
        if not topic_ids:
            return []

        placeholders = ",".join("?" for _ in topic_ids)
        params: List[Any] = list(topic_ids) + [session_id]

        query = f"""
            SELECT claim_id, session_id, ticket_id, statement, evidence, confidence,
                   fingerprint, last_verified, ttl_seconds, expires_at,
                   metadata, created_at, updated_at, topic_id, claim_type
            FROM claims
            WHERE topic_id IN ({placeholders})
              AND session_id = ?
        """

        if claim_types:
            type_placeholders = ",".join("?" for _ in claim_types)
            query += f" AND claim_type IN ({type_placeholders})"
            params.extend(claim_types)

        if min_confidence:
            # Map confidence levels to values for comparison
            confidence_order = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
            min_val = confidence_order.get(min_confidence.upper(), 0)
            if min_val > 1:
                query += " AND confidence IN ('MEDIUM', 'HIGH')"
            if min_val > 2:
                query += " AND confidence = 'HIGH'"

        if exclude_expired:
            query += " AND expires_at > datetime('now')"

        query += " ORDER BY updated_at DESC"

        cursor = self._conn.execute(query, params)
        results = []

        for row in cursor.fetchall():
            metadata = json.loads(row[10]) if row[10] else {}
            if metadata.get("archived", False):
                continue

            results.append(ClaimRow(
                claim_id=row[0],
                session_id=row[1],
                ticket_id=row[2],
                statement=row[3],
                evidence=json.loads(row[4]) if row[4] else [],
                confidence=row[5],
                fingerprint=row[6],
                last_verified=row[7],
                ttl_seconds=int(row[8]),
                expires_at=row[9],
                metadata=metadata,
                created_at=float(row[11]),
                updated_at=float(row[12]),
            ))

        return results

    def get_claims_by_type(
        self,
        session_id: str,
        claim_type: str,
        exclude_expired: bool = True,
    ) -> List[ClaimRow]:
        """Get all claims of a specific type in session."""
        query = """
            SELECT claim_id, session_id, ticket_id, statement, evidence, confidence,
                   fingerprint, last_verified, ttl_seconds, expires_at,
                   metadata, created_at, updated_at
            FROM claims
            WHERE session_id = ? AND claim_type = ?
        """
        params: List[Any] = [session_id, claim_type]

        if exclude_expired:
            query += " AND expires_at > datetime('now')"

        query += " ORDER BY updated_at DESC"

        cursor = self._conn.execute(query, params)
        results = []

        for row in cursor.fetchall():
            metadata = json.loads(row[10]) if row[10] else {}
            if metadata.get("archived", False):
                continue

            results.append(ClaimRow(
                claim_id=row[0],
                session_id=row[1],
                ticket_id=row[2],
                statement=row[3],
                evidence=json.loads(row[4]) if row[4] else [],
                confidence=row[5],
                fingerprint=row[6],
                last_verified=row[7],
                ttl_seconds=int(row[8]),
                expires_at=row[9],
                metadata=metadata,
                created_at=float(row[11]),
                updated_at=float(row[12]),
            ))

        return results

    def update_claim_topic(
        self,
        claim_id: str,
        topic_id: str,
        claim_type: Optional[str] = None,
    ) -> bool:
        """
        Associate a claim with a topic and optionally set its type.

        Args:
            claim_id: Claim to update
            topic_id: Topic to associate with
            claim_type: Optional claim type (retailer, price, etc.)

        Returns:
            True if claim was updated
        """
        with self._lock:
            if claim_type:
                cur = self._conn.execute(
                    "UPDATE claims SET topic_id = ?, claim_type = ? WHERE claim_id = ?",
                    (topic_id, claim_type, claim_id)
                )
            else:
                cur = self._conn.execute(
                    "UPDATE claims SET topic_id = ? WHERE claim_id = ?",
                    (topic_id, claim_id)
                )
            self._conn.commit()
            return cur.rowcount > 0

    def bulk_update_claim_topics(
        self,
        updates: List[Dict[str, str]],
    ) -> int:
        """
        Bulk update claims with topic and type info.

        Args:
            updates: List of {"claim_id": str, "topic_id": str, "claim_type": str}

        Returns:
            Number of claims updated
        """
        if not updates:
            return 0

        count = 0
        with self._lock:
            for update in updates:
                claim_id = update.get("claim_id")
                topic_id = update.get("topic_id")
                claim_type = update.get("claim_type")

                if not claim_id:
                    continue

                if topic_id and claim_type:
                    cur = self._conn.execute(
                        "UPDATE claims SET topic_id = ?, claim_type = ? WHERE claim_id = ?",
                        (topic_id, claim_type, claim_id)
                    )
                elif topic_id:
                    cur = self._conn.execute(
                        "UPDATE claims SET topic_id = ? WHERE claim_id = ?",
                        (topic_id, claim_id)
                    )
                elif claim_type:
                    cur = self._conn.execute(
                        "UPDATE claims SET claim_type = ? WHERE claim_id = ?",
                        (claim_type, claim_id)
                    )
                else:
                    continue

                count += cur.rowcount

            self._conn.commit()

        return count

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ #
    # Internal helpers

    def _upsert_claim(
        self,
        *,
        claim_id: str,
        session_id: str,
        ticket_id: str,
        statement: str,
        evidence: Sequence[str],
        confidence: str,
        fingerprint: str,
        last_verified: str,
        ttl_seconds: int,
        expires_at: str,
        metadata: Dict[str, Any],
        created_ts: float,
        turn_id: str,
    ) -> bool:
        existing = self._fetch_claim(claim_id)
        evidence_json = json.dumps(list(evidence), ensure_ascii=False)
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        changed = (
            existing is None
            or existing.fingerprint != fingerprint
            or existing.confidence != confidence
            or existing.statement != statement
            or list(existing.evidence) != list(evidence)
        )

        updated_at = created_ts

        # Extract quality fields from metadata for dedicated columns
        matched_intent = metadata.get("matched_intent")
        intent_alignment = metadata.get("intent_alignment", 0.5)
        result_type = metadata.get("result_type")
        evidence_strength = metadata.get("evidence_strength", 0.5)
        quality_score = metadata.get("quality_score")

        with self._lock:
            if existing is None:
                self._conn.execute(
                    """
                    INSERT INTO claims (
                        claim_id, session_id, ticket_id, statement, evidence, confidence,
                        fingerprint, last_verified, ttl_seconds, expires_at,
                        metadata, created_at, updated_at, last_turn_id,
                        matched_intent, intent_alignment, result_type, evidence_strength, user_feedback_score
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        claim_id,
                        session_id,
                        ticket_id,
                        statement,
                        evidence_json,
                        confidence,
                        fingerprint,
                        last_verified,
                        int(ttl_seconds),
                        expires_at,
                        metadata_json,
                        created_ts,
                        updated_at,
                        turn_id,
                        matched_intent,
                        float(intent_alignment) if intent_alignment is not None else 0.5,
                        result_type,
                        float(evidence_strength) if evidence_strength is not None else 0.5,
                    ),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE claims
                    SET session_id=?, ticket_id=?, statement=?, evidence=?, confidence=?, fingerprint=?,
                        last_verified=?, ttl_seconds=?, expires_at=?, metadata=?,
                        updated_at=?, last_turn_id=?,
                        matched_intent=?, intent_alignment=?, result_type=?, evidence_strength=?
                    WHERE claim_id=?
                    """,
                    (
                        session_id,
                        ticket_id,
                        statement,
                        evidence_json,
                        confidence,
                        fingerprint,
                        last_verified,
                        int(ttl_seconds),
                        expires_at,
                        metadata_json,
                        updated_at,
                        turn_id,
                        matched_intent,
                        float(intent_alignment) if intent_alignment is not None else 0.5,
                        result_type,
                        float(evidence_strength) if evidence_strength is not None else 0.5,
                        claim_id,
                    ),
                )
            self._conn.commit()
        return changed

    def _fetch_claim(self, claim_id: str) -> Optional[ClaimRow]:
        cursor = self._conn.execute(
            """
            SELECT claim_id, session_id, ticket_id, statement, evidence, confidence,
                   fingerprint, last_verified, ttl_seconds, expires_at,
                   metadata, created_at, updated_at
            FROM claims
            WHERE claim_id = ?
            """,
            (claim_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return ClaimRow(
            claim_id=row[0],
            session_id=row[1],
            ticket_id=row[2],
            statement=row[3],
            evidence=json.loads(row[4]) if row[4] else [],
            confidence=row[5],
            fingerprint=row[6],
            last_verified=row[7],
            ttl_seconds=int(row[8]),
            expires_at=row[9],
            metadata=json.loads(row[10]) if row[10] else {},
            created_at=float(row[11]),
            updated_at=float(row[12]),
        )

    def _record_artifacts(
        self,
        *,
        session_id: str,
        artifacts: Sequence[CapsuleArtifact],
        seen_ts: float,
    ) -> List[CapsuleArtifact]:
        new_artifacts: List[CapsuleArtifact] = []
        with self._lock:
            for art in artifacts:
                artifact = CapsuleArtifact.model_validate(art)
                cursor = self._conn.execute(
                    "SELECT 1 FROM artifacts_seen WHERE session_id=? AND blob_id=?",
                    (session_id, artifact.blob_id),
                )
                if cursor.fetchone():
                    continue
                self._conn.execute(
                    "INSERT OR IGNORE INTO artifacts_seen (session_id, blob_id, first_seen) VALUES (?, ?, ?)",
                    (session_id, artifact.blob_id, seen_ts),
                )
                new_artifacts.append(artifact)
            self._conn.commit()
        return new_artifacts

    @staticmethod
    def fingerprint(claim: CapsuleClaim) -> str:
        parts = [claim.claim.strip(), "|".join(sorted(claim.evidence))]
        payload = "\x1f".join(parts).encode("utf-8")
        return hashlib.sha1(payload).hexdigest()

    @staticmethod
    def _derive_claim_id(claim: CapsuleClaim, fingerprint: str) -> str:
        return f"clm_{fingerprint[:16]}"

    def _ensure_tables(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    ticket_id TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    last_verified TEXT NOT NULL,
                    ttl_seconds INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    metadata TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_turn_id TEXT,
                    matched_intent TEXT,
                    intent_alignment REAL,
                    result_type TEXT,
                    evidence_strength REAL,
                    user_feedback_score INTEGER
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts_seen (
                    session_id TEXT NOT NULL,
                    blob_id TEXT NOT NULL,
                    first_seen REAL NOT NULL,
                    PRIMARY KEY (session_id, blob_id)
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_session ON claims(session_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_ticket ON claims(ticket_id)")

            # Migration: Add quality columns if they don't exist
            # Check if columns exist by trying to query them
            cursor = self._conn.execute("PRAGMA table_info(claims)")
            existing_cols = {row[1] for row in cursor.fetchall()}

            quality_columns = [
                ("matched_intent", "TEXT"),
                ("intent_alignment", "REAL"),
                ("result_type", "TEXT"),
                ("evidence_strength", "REAL"),
                ("user_feedback_score", "INTEGER"),
            ]

            for col_name, col_type in quality_columns:
                if col_name not in existing_cols:
                    try:
                        self._conn.execute(f"ALTER TABLE claims ADD COLUMN {col_name} {col_type}")
                    except Exception:
                        pass  # Column might already exist due to race condition

            self._conn.commit()


# Module-level singleton
_claim_registry_singleton: Optional[ClaimRegistry] = None
_default_db_path = Path("panda_system_docs/shared_state/claims.db")


def get_claim_registry(db_path: Optional[str | Path] = None) -> ClaimRegistry:
    """
    Get or create the singleton ClaimRegistry instance.

    Args:
        db_path: Optional database path. If not provided, uses default.

    Returns:
        ClaimRegistry instance
    """
    global _claim_registry_singleton

    if db_path is None:
        db_path = _default_db_path

    if _claim_registry_singleton is None:
        _claim_registry_singleton = ClaimRegistry(db_path)

    return _claim_registry_singleton


def reset_claim_registry() -> None:
    """Reset the singleton (useful for testing)."""
    global _claim_registry_singleton
    if _claim_registry_singleton is not None:
        _claim_registry_singleton.close()
        _claim_registry_singleton = None
