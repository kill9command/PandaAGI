"""
Safety validation for file and git operations.

Enforces protection of critical system files at the Orchestrator level
(defense-in-depth, not just prompt-level).
"""
import re
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SecurityError(Exception):
    """Raised when attempting to perform unsafe operation."""
    pass


# Protected path patterns (glob-style)
PROTECTED_PATTERNS = [
    # Git internals
    ".git/*", ".git/**/*",

    # Environment and secrets
    ".env*", "*.env", "credentials*", "secrets*",
    "*.key", "*.pem", "*.crt", "*.p12",

    # System control scripts
    "start.sh", "stop.sh", "server_health.sh",

    # Core application files (Gateway/Orchestrator)
    "project_build_instructions/gateway/app.py",
    "project_build_instructions/orchestrator/app.py",
    "gateway/app.py",
    "orchestrator/app.py",

    # Process management
    "vllm.pid", "*.pid", ".pids/*",

    # Databases (read-only allowed, write requires approval)
    "*.db", "*.sqlite", "*.sqlite3",

    # System configs
    "pyproject.toml", "setup.py", "requirements.txt",

    # Model weights (very large, dangerous to modify)
    "models/**/*.safetensors", "models/**/*.bin",
]


def matches_protected_pattern(file_path: str, patterns: list = None) -> bool:
    """
    Check if file path matches any protected pattern.

    Args:
        file_path: Path to check
        patterns: Optional custom patterns (defaults to PROTECTED_PATTERNS)

    Returns:
        True if path matches any protected pattern
    """
    if patterns is None:
        patterns = PROTECTED_PATTERNS

    # Normalize path
    path = Path(file_path).as_posix()

    for pattern in patterns:
        # Convert glob pattern to regex
        regex_pattern = pattern.replace(".", r"\.")
        regex_pattern = regex_pattern.replace("*", ".*")
        regex_pattern = regex_pattern.replace("?", ".")

        if re.match(f"^{regex_pattern}$", path):
            return True

        # Also check basename for patterns like "*.key"
        if re.match(f"^{regex_pattern}$", Path(path).name):
            return True

    return False


def validate_file_operation(
    file_path: str,
    operation: str,
    force: bool = False,
    repo: Optional[str] = None
) -> None:
    """
    Validate file operation against protected paths.

    Args:
        file_path: Path to file being operated on
        operation: Operation type (read, write, edit, delete)
        force: If True, bypass protection (requires explicit user approval)
        repo: Repository path (used to resolve relative paths)

    Raises:
        SecurityError: If operation violates safety rules
    """
    # Resolve relative paths
    if repo and not Path(file_path).is_absolute():
        full_path = Path(repo) / file_path
    else:
        full_path = Path(file_path)

    # Check against protected patterns
    if matches_protected_pattern(str(full_path)):
        if force:
            logger.warning(
                f"[SECURITY] Protected path operation FORCED: {operation} {full_path}"
            )
        else:
            logger.error(
                f"[SECURITY] Blocked protected path operation: {operation} {full_path}"
            )
            raise SecurityError(
                f"Cannot {operation} protected path: {file_path}. "
                f"This file is critical to system operation. "
                f"Use force=True with explicit approval if absolutely necessary."
            )

    # Additional validation for write operations
    if operation in ("write", "edit", "delete"):
        # Prevent accidental deletion of entire directories
        if full_path.is_dir():
            raise SecurityError(
                f"Cannot {operation} directory: {file_path}. "
                f"File operations only, not directories."
            )


def validate_git_operation(
    operation: str,
    repo: str,
    force: bool = False
) -> None:
    """
    Validate git operation safety.

    Args:
        operation: Git operation (commit, push, reset, etc.)
        repo: Repository path
        force: If True, bypass protection

    Raises:
        SecurityError: If operation is dangerous
    """
    # Dangerous git operations (require force)
    dangerous_ops = [
        "reset --hard",
        "push --force",
        "push -f",
        "clean -fd",
        "rebase",
    ]

    for dangerous in dangerous_ops:
        if dangerous in operation.lower():
            if force:
                logger.warning(
                    f"[SECURITY] Dangerous git operation FORCED: {operation}"
                )
            else:
                logger.error(
                    f"[SECURITY] Blocked dangerous git operation: {operation}"
                )
                raise SecurityError(
                    f"Git operation '{dangerous}' is destructive and requires explicit approval. "
                    f"Use force=True with user confirmation."
                )


def get_approval_required_operations():
    """
    Return list of operations that require user approval.

    Used by approval_manager to determine when to prompt user.
    """
    return {
        "file.write": "Create new file",
        "file.edit": "Modify file",
        "file.delete": "Delete file",
        "git.commit": "Commit changes",
        "git.push": "Push to remote",
        "git.reset": "Reset repository state",
        "bash.execute": "Execute shell command",
    }


def format_approval_message(operation: str, args: dict) -> str:
    """
    Format user-friendly approval message.

    Args:
        operation: Operation name (e.g., "file.edit")
        args: Operation arguments

    Returns:
        Human-readable approval message
    """
    if operation == "file.write":
        return f"Create new file: {args.get('file_path', 'unknown')}?"

    elif operation == "file.edit":
        file_path = args.get('file_path', 'unknown')
        if matches_protected_pattern(file_path):
            return f"⚠️  Edit PROTECTED file: {file_path}? (This is a critical system file)"
        return f"Edit file: {file_path}?"

    elif operation == "file.delete":
        return f"⚠️  DELETE file: {args.get('file_path', 'unknown')}? (Cannot be undone)"

    elif operation == "git.commit":
        message = args.get('message', '')
        return f"Commit changes with message: '{message[:50]}...'?"

    elif operation == "git.push":
        return f"Push commits to remote repository?"

    elif operation == "bash.execute":
        command = args.get('command', '')[:50]
        return f"Execute shell command: '{command}...'?"

    return f"Proceed with {operation}?"
