"""
Backup Manager - Handles backup and rollback for tool/workflow modifications.

Architecture Reference:
- architecture/concepts/TOOL_SYSTEM.md
- architecture/concepts/SELF_BUILDING_SYSTEM.md

Before any tool/workflow modification:
1. Create timestamped backup in .backup/ directory
2. On validation/test failure, restore from backup
3. Record failure in plan_state.json
"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class BackupManager:
    """
    Manages backups and rollbacks for tool/workflow files.

    Backup structure:
    ```
    {bundle_dir}/.backup/
        tool_name.py.{timestamp}
        tool_name.md.{timestamp}
        workflow.md.{timestamp}
    ```
    """

    BACKUP_DIR_NAME = ".backup"
    TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"

    def __init__(self, bundle_dir: Path):
        """
        Initialize backup manager for a bundle.

        Args:
            bundle_dir: Path to the workflow bundle directory
        """
        self.bundle_dir = Path(bundle_dir)
        self.backup_dir = self.bundle_dir / self.BACKUP_DIR_NAME

    def create_backup(self, file_path: Path) -> Optional[Path]:
        """
        Create a timestamped backup of a file.

        Args:
            file_path: Path to the file to backup

        Returns:
            Path to the backup file, or None if file doesn't exist
        """
        if not file_path.exists():
            logger.debug(f"[BackupManager] No backup needed - file doesn't exist: {file_path}")
            return None

        # Ensure backup directory exists
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # Create timestamped backup name
        timestamp = datetime.now().strftime(self.TIMESTAMP_FORMAT)
        backup_name = f"{file_path.name}.{timestamp}"
        backup_path = self.backup_dir / backup_name

        # Copy file to backup
        shutil.copy2(file_path, backup_path)
        logger.info(f"[BackupManager] Created backup: {backup_path}")

        return backup_path

    def create_backups(self, file_paths: List[Path]) -> Dict[Path, Optional[Path]]:
        """
        Create backups for multiple files.

        Args:
            file_paths: List of file paths to backup

        Returns:
            Dict mapping original paths to backup paths
        """
        backups = {}
        for file_path in file_paths:
            backups[file_path] = self.create_backup(file_path)
        return backups

    def restore_backup(self, backup_path: Path, original_path: Path) -> bool:
        """
        Restore a file from backup.

        Args:
            backup_path: Path to the backup file
            original_path: Path to restore to

        Returns:
            True if restored successfully
        """
        if not backup_path.exists():
            logger.error(f"[BackupManager] Backup not found: {backup_path}")
            return False

        try:
            shutil.copy2(backup_path, original_path)
            logger.info(f"[BackupManager] Restored from backup: {backup_path} -> {original_path}")
            return True
        except Exception as e:
            logger.error(f"[BackupManager] Restore failed: {e}")
            return False

    def restore_backups(self, backups: Dict[Path, Optional[Path]]) -> int:
        """
        Restore multiple files from backups.

        Args:
            backups: Dict mapping original paths to backup paths

        Returns:
            Number of files restored
        """
        restored = 0
        for original_path, backup_path in backups.items():
            if backup_path and self.restore_backup(backup_path, original_path):
                restored += 1
            elif backup_path is None and original_path.exists():
                # File was newly created, delete it
                try:
                    original_path.unlink()
                    logger.info(f"[BackupManager] Removed new file: {original_path}")
                    restored += 1
                except Exception as e:
                    logger.error(f"[BackupManager] Failed to remove new file: {e}")
        return restored

    def get_latest_backup(self, filename: str) -> Optional[Path]:
        """
        Get the most recent backup for a filename.

        Args:
            filename: Original filename (e.g., "tool_name.py")

        Returns:
            Path to the latest backup, or None
        """
        if not self.backup_dir.exists():
            return None

        # Find all backups for this file
        pattern = f"{filename}.*"
        backups = sorted(self.backup_dir.glob(pattern), reverse=True)

        return backups[0] if backups else None

    def list_backups(self, filename: Optional[str] = None) -> List[Path]:
        """
        List all backups, optionally filtered by filename.

        Args:
            filename: Filter to specific filename (optional)

        Returns:
            List of backup paths, sorted newest first
        """
        if not self.backup_dir.exists():
            return []

        pattern = f"{filename}.*" if filename else "*"
        return sorted(self.backup_dir.glob(pattern), reverse=True)

    def cleanup_old_backups(self, keep_count: int = 5) -> int:
        """
        Remove old backups, keeping only the most recent.

        Args:
            keep_count: Number of backups to keep per file

        Returns:
            Number of backups removed
        """
        if not self.backup_dir.exists():
            return 0

        removed = 0
        # Group backups by original filename
        backups_by_file: Dict[str, List[Path]] = {}

        for backup in self.backup_dir.iterdir():
            if backup.is_file():
                # Extract original filename (everything before the timestamp)
                parts = backup.name.rsplit(".", 2)
                if len(parts) >= 2:
                    original_name = ".".join(parts[:-1])
                    if original_name not in backups_by_file:
                        backups_by_file[original_name] = []
                    backups_by_file[original_name].append(backup)

        # Remove old backups for each file
        for original_name, backups in backups_by_file.items():
            sorted_backups = sorted(backups, reverse=True)
            for old_backup in sorted_backups[keep_count:]:
                try:
                    old_backup.unlink()
                    removed += 1
                    logger.debug(f"[BackupManager] Removed old backup: {old_backup}")
                except Exception as e:
                    logger.warning(f"[BackupManager] Failed to remove backup: {e}")

        if removed:
            logger.info(f"[BackupManager] Cleaned up {removed} old backups")
        return removed


class RollbackContext:
    """
    Context manager for automatic rollback on failure.

    Usage:
        with RollbackContext(backup_manager, [file1, file2]) as ctx:
            # Make modifications
            if something_failed:
                ctx.mark_failed("reason")
        # Automatically rolls back if marked failed or exception raised
    """

    def __init__(
        self,
        backup_manager: BackupManager,
        files_to_backup: List[Path],
        plan_state_path: Optional[Path] = None
    ):
        self.backup_manager = backup_manager
        self.files_to_backup = files_to_backup
        self.plan_state_path = plan_state_path
        self.backups: Dict[Path, Optional[Path]] = {}
        self.failed = False
        self.failure_reason = ""

    def __enter__(self):
        # Create backups before modifications
        self.backups = self.backup_manager.create_backups(self.files_to_backup)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None or self.failed:
            # Rollback on exception or explicit failure
            reason = self.failure_reason or (str(exc_val) if exc_val else "Unknown error")
            logger.warning(f"[RollbackContext] Rolling back due to: {reason}")
            self.backup_manager.restore_backups(self.backups)

            # Record failure in plan_state if available
            if self.plan_state_path:
                self._record_failure(reason)

            # Don't suppress exceptions
            return False
        return False

    def mark_failed(self, reason: str):
        """Mark the operation as failed, triggering rollback on exit."""
        self.failed = True
        self.failure_reason = reason

    def _record_failure(self, reason: str):
        """Record failure in plan_state.json."""
        if not self.plan_state_path:
            return

        try:
            plan_state = {}
            if self.plan_state_path.exists():
                plan_state = json.loads(self.plan_state_path.read_text())

            if "tool_creation_failures" not in plan_state:
                plan_state["tool_creation_failures"] = []

            plan_state["tool_creation_failures"].append({
                "timestamp": datetime.now().isoformat(),
                "reason": reason,
                "files_rolled_back": [str(p) for p in self.backups.keys()]
            })

            self.plan_state_path.write_text(json.dumps(plan_state, indent=2))
            logger.info(f"[RollbackContext] Recorded failure in plan_state.json")
        except Exception as e:
            logger.error(f"[RollbackContext] Failed to record failure: {e}")


# Convenience function
def get_backup_manager(bundle_dir: Path) -> BackupManager:
    """Create a BackupManager for a bundle directory."""
    return BackupManager(bundle_dir)
