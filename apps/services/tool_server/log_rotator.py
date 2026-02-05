"""
orchestrator/log_rotator.py

Per-query log rotation for the orchestrator.

Archives the current log file with a timestamp when a new query starts,
making it easy to debug individual queries.

Usage:
    from apps.services.tool_server.log_rotator import rotate_logs_for_query

    # At the start of each query:
    rotate_logs_for_query(query_id="abc123", query_preview="find cheapest laptop...")

Log files are stored in:
    - logs/panda/orchestrator.log (current query, centralized logging location)
    - panda_system_docs/logs/orchestrator_YYYYMMDD_HHMMSS_queryid.log (archived)
"""

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Configuration
# Archive directory for rotated logs
ARCHIVE_DIR = Path("panda_system_docs/logs")
# Current log file location (centralized logging puts it here)
CURRENT_LOG = Path("logs/panda/orchestrator.log")
MAX_ARCHIVED_LOGS = 50  # Keep last N archived logs


def rotate_logs_for_query(
    query_id: Optional[str] = None,
    query_preview: Optional[str] = None
) -> Optional[Path]:
    """
    Rotate logs when a new query starts.

    Archives the current orchestrator.log with a timestamp and query ID,
    then starts fresh for the new query.

    Args:
        query_id: Optional query/session identifier
        query_preview: Optional preview of the query (first 30 chars)

    Returns:
        Path to archived log file, or None if no rotation needed
    """
    try:
        # Ensure archive directory exists
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

        # Check if current log exists and has content
        if not CURRENT_LOG.exists():
            logger.debug("[LogRotator] No current log to rotate")
            return None

        log_size = CURRENT_LOG.stat().st_size
        if log_size < 100:  # Skip tiny logs (just startup messages)
            logger.debug(f"[LogRotator] Log too small to rotate ({log_size} bytes)")
            return None

        # Generate archive filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        query_suffix = f"_{query_id[:8]}" if query_id else ""
        archive_name = f"orchestrator_{timestamp}{query_suffix}.log"
        archive_path = ARCHIVE_DIR / archive_name

        # Find all file handlers pointing to our log file across ALL loggers
        # (not just root logger - modules may have their own handlers)
        file_handlers = []
        resolved_log_path = CURRENT_LOG.resolve()

        # Check root logger handlers
        for handler in logging.root.handlers[:]:
            handler.flush()
            if isinstance(handler, logging.FileHandler):
                try:
                    if handler.baseFilename and Path(handler.baseFilename).resolve() == resolved_log_path:
                        file_handlers.append(handler)
                except Exception:
                    pass

        # Check all named loggers too
        for logger_name in list(logging.Logger.manager.loggerDict.keys()):
            try:
                named_logger = logging.getLogger(logger_name)
                for handler in getattr(named_logger, 'handlers', []):
                    handler.flush()
                    if isinstance(handler, logging.FileHandler):
                        try:
                            if handler.baseFilename and Path(handler.baseFilename).resolve() == resolved_log_path:
                                if handler not in file_handlers:
                                    file_handlers.append(handler)
                        except Exception:
                            pass
            except Exception:
                pass

        # Properly remove and recreate file handlers to prevent null byte corruption
        # The issue is that FileHandler maintains internal state that gets out of sync
        # when we just reopen the stream
        handler_configs = []
        for handler in file_handlers:
            # Save handler configuration before removing
            handler_configs.append({
                'logger': None,  # Will find the logger below
                'handler': handler,
                'level': handler.level,
                'formatter': handler.formatter,
                'filters': handler.filters[:] if handler.filters else [],
            })
            handler.close()

            # Remove from root logger
            if handler in logging.root.handlers:
                logging.root.handlers.remove(handler)

        # Copy current log to archive (copy instead of move to avoid breaking file handles)
        shutil.copy2(CURRENT_LOG, archive_path)

        # Truncate the current log file
        with open(CURRENT_LOG, 'w') as f:
            f.write(f"# Log rotated at {datetime.now().isoformat()}\n")
            if query_preview:
                f.write(f"# New query: {query_preview[:60]}...\n")
            f.write("#" + "=" * 70 + "\n\n")

        # Create fresh file handlers (not reusing old ones to avoid state corruption)
        for config in handler_configs:
            new_handler = logging.FileHandler(
                str(CURRENT_LOG),
                mode='a',
                encoding='utf-8'
            )
            new_handler.setLevel(config['level'])
            if config['formatter']:
                new_handler.setFormatter(config['formatter'])
            for filt in config['filters']:
                new_handler.addFilter(filt)
            logging.root.addHandler(new_handler)

        logger.info(f"[LogRotator] Archived previous log to: {archive_path}")

        # Cleanup old archives if needed
        _cleanup_old_archives()

        return archive_path

    except Exception as e:
        logger.warning(f"[LogRotator] Failed to rotate logs: {e}")
        return None


def _cleanup_old_archives():
    """Remove old archived logs beyond MAX_ARCHIVED_LOGS."""
    try:
        archives = sorted(ARCHIVE_DIR.glob("orchestrator_*.log"), key=lambda p: p.stat().st_mtime)

        if len(archives) > MAX_ARCHIVED_LOGS:
            to_delete = archives[:-MAX_ARCHIVED_LOGS]
            for old_log in to_delete:
                old_log.unlink()
                logger.debug(f"[LogRotator] Deleted old archive: {old_log.name}")
    except Exception as e:
        logger.warning(f"[LogRotator] Failed to cleanup old archives: {e}")


def get_archived_logs(limit: int = 20) -> list:
    """
    Get list of recent archived logs.

    Returns:
        List of dicts with log file info: {name, path, size, timestamp}
    """
    try:
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        archives = sorted(ARCHIVE_DIR.glob("orchestrator_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)

        result = []
        for log_path in archives[:limit]:
            stat = log_path.stat()
            result.append({
                "name": log_path.name,
                "path": str(log_path),
                "size": stat.st_size,
                "size_human": _human_size(stat.st_size),
                "timestamp": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
        return result
    except Exception as e:
        logger.warning(f"[LogRotator] Failed to list archived logs: {e}")
        return []


def _human_size(size_bytes: int) -> str:
    """Convert bytes to human readable size."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"
