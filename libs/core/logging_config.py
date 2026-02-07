"""
Centralized Logging Configuration for PandaAI

This module sets up unified logging across all services (Gateway, Orchestrator).
All logs go to TWO files for easy debugging:

1. logs/panda/system.log - All Python logging from all components (rotating)
2. logs/panda/latest.log - Domain events from PandaLogger (turns, phases, LLM calls)

Usage in any module:
    from libs.core.logging_config import setup_logging, get_logger

    # Call once at service startup
    setup_logging()

    # Get a logger for your module
    logger = get_logger(__name__)
    logger.info("My message")

Debugging:
    # Watch all system activity in real-time:
    tail -f logs/panda/system.log

    # Watch domain events (turns, phases):
    tail -f logs/panda/latest.log

    # Watch both:
    tail -f logs/panda/system.log logs/panda/latest.log
"""

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# =============================================================================
# Configuration
# =============================================================================

LOG_DIR = Path("logs/panda")
SYSTEM_LOG_FILE = LOG_DIR / "system.log"
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10 MB per file
BACKUP_COUNT = 5  # Keep 5 rotated files

# Default log level (can be overridden by LOG_LEVEL env var)
DEFAULT_LOG_LEVEL = "INFO"

# Log format with timestamp, level, component, and message
LOG_FORMAT = "%(asctime)s | %(levelname)-5s | %(name)-30s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Simplified format for console
CONSOLE_FORMAT = "%(asctime)s | %(levelname)-5s | %(name)-20s | %(message)s"
CONSOLE_DATE_FORMAT = "%H:%M:%S"

# =============================================================================
# Global State
# =============================================================================

_logging_configured = False
_file_handler: Optional[RotatingFileHandler] = None


# =============================================================================
# Setup Functions
# =============================================================================


def setup_logging(
    level: Optional[str] = None,
    log_to_console: bool = True,
    log_to_file: bool = True,
    service_name: str = "panda",
) -> None:
    """
    Configure unified logging for PandaAI services.

    This should be called ONCE at the start of each service (Gateway, Orchestrator).

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR). Defaults to LOG_LEVEL env var or INFO.
        log_to_console: Whether to also log to stdout (default True)
        log_to_file: Whether to log to system.log file (default True)
        service_name: Service identifier for log context

    Example:
        # In Gateway startup:
        from libs.core.logging_config import setup_logging
        setup_logging(service_name="gateway")

        # In Orchestrator startup:
        from libs.core.logging_config import setup_logging
        setup_logging(service_name="tool_server")
    """
    global _logging_configured, _file_handler

    # Don't reconfigure if already set up (singleton pattern)
    if _logging_configured:
        return

    # Determine log level
    if level is None:
        level = os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL)
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Ensure log directory exists
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove any existing handlers (prevents duplicates)
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # === File Handler (system.log) ===
    if log_to_file:
        _file_handler = RotatingFileHandler(
            SYSTEM_LOG_FILE,
            maxBytes=MAX_LOG_SIZE,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        _file_handler.setLevel(log_level)
        _file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        root_logger.addHandler(_file_handler)

    # === Console Handler (stdout) ===
    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(logging.Formatter(CONSOLE_FORMAT, CONSOLE_DATE_FORMAT))
        root_logger.addHandler(console_handler)

    # === Reduce noise from chatty libraries ===
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    # Mark as configured
    _logging_configured = True

    # Write startup marker
    logger = logging.getLogger(service_name)
    logger.info("=" * 60)
    logger.info(f"LOGGING INITIALIZED - {service_name.upper()}")
    logger.info(f"Log file: {SYSTEM_LOG_FILE.absolute()}")
    logger.info(f"Log level: {level.upper()}")
    logger.info("=" * 60)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a module.

    This is the recommended way to get a logger in any module.

    Args:
        name: Usually __name__ to get the module's dotted path

    Returns:
        Logger instance

    Example:
        from libs.core.logging_config import get_logger
        logger = get_logger(__name__)
        logger.info("Processing request")
    """
    return logging.getLogger(name)


def get_system_log_path() -> Path:
    """Get the path to the system log file."""
    return SYSTEM_LOG_FILE


def get_latest_log_path() -> Path:
    """Get the path to the PandaLogger latest.log file."""
    return LOG_DIR / "latest.log"


# =============================================================================
# Convenience Functions
# =============================================================================


def log_request_start(logger: logging.Logger, trace_id: str, query: str, mode: str = "chat"):
    """Log the start of a request with standard format."""
    logger.info(f"[{trace_id}] REQUEST START | mode={mode} | query={query[:100]}...")


def log_request_end(logger: logging.Logger, trace_id: str, success: bool, elapsed_ms: float):
    """Log the end of a request with standard format."""
    status = "SUCCESS" if success else "FAILED"
    logger.info(f"[{trace_id}] REQUEST END | {status} | elapsed={elapsed_ms:.0f}ms")


def log_phase(logger: logging.Logger, trace_id: str, phase: int, name: str, status: str, elapsed_ms: float = None):
    """Log a phase transition with standard format."""
    elapsed = f" | elapsed={elapsed_ms:.0f}ms" if elapsed_ms else ""
    logger.info(f"[{trace_id}] PHASE {phase} | {name} | {status}{elapsed}")


def log_tool_call(logger: logging.Logger, trace_id: str, tool: str, status: str = "calling"):
    """Log a tool call with standard format."""
    logger.info(f"[{trace_id}] TOOL | {tool} | {status}")


def log_llm_call(logger: logging.Logger, trace_id: str, role: str, tokens: int = 0, elapsed_ms: float = None):
    """Log an LLM call with standard format."""
    elapsed = f" | elapsed={elapsed_ms:.0f}ms" if elapsed_ms else ""
    logger.info(f"[{trace_id}] LLM | {role} | tokens={tokens}{elapsed}")


# =============================================================================
# Log File Utilities
# =============================================================================


def tail_logs(n: int = 50) -> str:
    """
    Get the last N lines from the system log.

    Useful for debugging in code or API endpoints.
    """
    if not SYSTEM_LOG_FILE.exists():
        return "No log file found"

    try:
        with open(SYSTEM_LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
            return "".join(lines[-n:])
    except Exception as e:
        return f"Error reading log: {e}"


def get_log_files() -> dict:
    """
    Get information about all log files.

    Returns dict with log file paths and sizes.
    """
    result = {}

    if LOG_DIR.exists():
        for log_file in LOG_DIR.glob("*.log*"):
            try:
                stat = log_file.stat()
                result[str(log_file)] = {
                    "size_kb": stat.st_size / 1024,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                }
            except Exception:
                pass

    return result


def clear_old_logs(keep_days: int = 7):
    """
    Clear log files older than N days.

    Keeps system.log and latest.log, removes old rotated files.
    """
    import time

    cutoff = time.time() - (keep_days * 24 * 60 * 60)

    if LOG_DIR.exists():
        for log_file in LOG_DIR.glob("panda_*.log"):
            try:
                if log_file.stat().st_mtime < cutoff:
                    log_file.unlink()
            except Exception:
                pass
