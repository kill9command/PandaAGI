"""
orchestrator/shared_state/preference_snapshot.py

Preference versioning service for cache optimization.
Versions preference maps per turn, allowing cache entries to reference snapshot IDs
instead of duplicating preference data.
"""
import asyncio
import json
import hashlib
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


@dataclass
class PreferenceSnapshot:
    """A versioned snapshot of user preferences."""
    snapshot_id: str
    session_id: str
    preferences: Dict[str, Any]
    created_at: str
    turn_number: int
    fingerprint: str


class PreferenceSnapshotService:
    """
    Service for versioning and deduplicating preference maps.

    Benefits:
    - Reduces cache storage (reference snapshot ID instead of full preferences)
    - Enables preference change tracking
    - Supports preference rollback for debugging
    - Optimizes cache fingerprinting
    """

    def __init__(self, storage_dir: Optional[Path] = None):
        """
        Initialize preference snapshot service.

        Args:
            storage_dir: Directory for snapshot storage
        """
        if storage_dir is None:
            from apps.services.orchestrator.shared_state.cache_config import CACHE_BASE_DIR
            storage_dir = CACHE_BASE_DIR / "preference_snapshots"

        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache of snapshots
        self._cache: Dict[str, PreferenceSnapshot] = {}
        self._cache_lock = asyncio.Lock()

        # Session -> snapshot ID mapping
        self._session_snapshots: Dict[str, List[str]] = {}

        logger.info(f"[PreferenceSnapshot] Initialized at {self.storage_dir}")

    async def create_snapshot(
        self,
        session_id: str,
        preferences: Dict[str, Any],
        turn_number: int = 0
    ) -> str:
        """
        Create a preference snapshot.

        Args:
            session_id: Session identifier
            preferences: Preference dictionary
            turn_number: Turn number in conversation

        Returns:
            Snapshot ID
        """
        # Generate snapshot fingerprint
        fingerprint = self._compute_fingerprint(preferences)

        # Check if snapshot already exists with same fingerprint
        async with self._cache_lock:
            # Look for existing snapshot with same fingerprint
            for snapshot_id, snapshot in self._cache.items():
                if snapshot.fingerprint == fingerprint and snapshot.session_id == session_id:
                    logger.debug(
                        f"[PreferenceSnapshot] Reusing existing snapshot {snapshot_id} "
                        f"for session {session_id[:8]}"
                    )
                    return snapshot_id

            # Create new snapshot
            snapshot_id = self._generate_snapshot_id(session_id, fingerprint, turn_number)
            snapshot = PreferenceSnapshot(
                snapshot_id=snapshot_id,
                session_id=session_id,
                preferences=preferences,
                created_at=datetime.now(timezone.utc).isoformat(),
                turn_number=turn_number,
                fingerprint=fingerprint
            )

            # Save to disk
            await self._save_snapshot(snapshot)

            # Cache in memory
            self._cache[snapshot_id] = snapshot

            # Track by session
            if session_id not in self._session_snapshots:
                self._session_snapshots[session_id] = []
            self._session_snapshots[session_id].append(snapshot_id)

            logger.info(
                f"[PreferenceSnapshot] Created snapshot {snapshot_id} "
                f"for session {session_id[:8]} turn {turn_number}"
            )

            return snapshot_id

    async def get_snapshot(self, snapshot_id: str) -> Optional[PreferenceSnapshot]:
        """
        Retrieve a preference snapshot by ID.

        Args:
            snapshot_id: Snapshot identifier

        Returns:
            PreferenceSnapshot if found, None otherwise
        """
        # Check memory cache first
        async with self._cache_lock:
            if snapshot_id in self._cache:
                return self._cache[snapshot_id]

        # Load from disk
        snapshot_file = self.storage_dir / f"{snapshot_id}.json"
        if not snapshot_file.exists():
            logger.warning(f"[PreferenceSnapshot] Snapshot {snapshot_id} not found")
            return None

        try:
            def _load():
                with open(snapshot_file, 'r') as f:
                    return json.load(f)

            data = await asyncio.to_thread(_load)
            snapshot = PreferenceSnapshot(**data)

            # Cache in memory
            async with self._cache_lock:
                self._cache[snapshot_id] = snapshot

            return snapshot

        except Exception as e:
            logger.error(f"[PreferenceSnapshot] Error loading snapshot {snapshot_id}: {e}")
            return None

    async def get_session_snapshots(self, session_id: str) -> List[PreferenceSnapshot]:
        """
        Get all snapshots for a session.

        Args:
            session_id: Session identifier

        Returns:
            List of PreferenceSnapshot objects
        """
        snapshot_ids = self._session_snapshots.get(session_id, [])
        snapshots = []

        for snapshot_id in snapshot_ids:
            snapshot = await self.get_snapshot(snapshot_id)
            if snapshot:
                snapshots.append(snapshot)

        return snapshots

    async def get_latest_snapshot(self, session_id: str) -> Optional[PreferenceSnapshot]:
        """
        Get the most recent snapshot for a session.

        Args:
            session_id: Session identifier

        Returns:
            Latest PreferenceSnapshot or None
        """
        snapshots = await self.get_session_snapshots(session_id)
        if not snapshots:
            return None

        # Sort by turn number
        snapshots.sort(key=lambda s: s.turn_number, reverse=True)
        return snapshots[0]

    async def compare_snapshots(
        self,
        snapshot_id_1: str,
        snapshot_id_2: str
    ) -> Dict[str, Any]:
        """
        Compare two preference snapshots.

        Args:
            snapshot_id_1: First snapshot ID
            snapshot_id_2: Second snapshot ID

        Returns:
            Dict with added, removed, and changed keys
        """
        snapshot1 = await self.get_snapshot(snapshot_id_1)
        snapshot2 = await self.get_snapshot(snapshot_id_2)

        if not snapshot1 or not snapshot2:
            return {"error": "One or both snapshots not found"}

        prefs1 = snapshot1.preferences
        prefs2 = snapshot2.preferences

        added = {k: v for k, v in prefs2.items() if k not in prefs1}
        removed = {k: v for k, v in prefs1.items() if k not in prefs2}
        changed = {
            k: {"old": prefs1[k], "new": prefs2[k]}
            for k in prefs1.keys() & prefs2.keys()
            if prefs1[k] != prefs2[k]
        }

        return {
            "added": added,
            "removed": removed,
            "changed": changed,
            "unchanged_count": len(prefs1.keys() & prefs2.keys()) - len(changed)
        }

    async def _save_snapshot(self, snapshot: PreferenceSnapshot):
        """Save snapshot to disk."""
        snapshot_file = self.storage_dir / f"{snapshot.snapshot_id}.json"

        try:
            def _write():
                with open(snapshot_file, 'w') as f:
                    json.dump(asdict(snapshot), f, indent=2)

            await asyncio.to_thread(_write)

        except Exception as e:
            logger.error(f"[PreferenceSnapshot] Error saving snapshot {snapshot.snapshot_id}: {e}")
            raise

    def _compute_fingerprint(self, preferences: Dict[str, Any]) -> str:
        """
        Compute fingerprint for preferences.

        Args:
            preferences: Preference dictionary

        Returns:
            Fingerprint hash
        """
        # Normalize preferences
        normalized = json.dumps(preferences, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def _generate_snapshot_id(self, session_id: str, fingerprint: str, turn_number: int) -> str:
        """
        Generate snapshot ID.

        Args:
            session_id: Session identifier
            fingerprint: Preference fingerprint
            turn_number: Turn number

        Returns:
            Snapshot ID
        """
        components = f"{session_id}:{fingerprint}:{turn_number}"
        return hashlib.md5(components.encode()).hexdigest()[:16]


# Global service instance
_preference_service: Optional[PreferenceSnapshotService] = None
_service_lock = asyncio.Lock()


async def get_preference_service() -> PreferenceSnapshotService:
    """
    Get global preference snapshot service (singleton).

    Returns:
        PreferenceSnapshotService instance
    """
    global _preference_service

    if _preference_service is None:
        async with _service_lock:
            if _preference_service is None:
                _preference_service = PreferenceSnapshotService()
                logger.info("[PreferenceSnapshot] Initialized global preference service")

    return _preference_service


async def create_snapshot(
    session_id: str,
    preferences: Dict[str, Any],
    turn_number: int = 0
) -> str:
    """
    Convenience function to create a preference snapshot.

    Args:
        session_id: Session identifier
        preferences: Preference dictionary
        turn_number: Turn number

    Returns:
        Snapshot ID
    """
    service = await get_preference_service()
    return await service.create_snapshot(session_id, preferences, turn_number)


async def get_snapshot(snapshot_id: str) -> Optional[PreferenceSnapshot]:
    """
    Convenience function to retrieve a snapshot.

    Args:
        snapshot_id: Snapshot identifier

    Returns:
        PreferenceSnapshot if found
    """
    service = await get_preference_service()
    return await service.get_snapshot(snapshot_id)
