"""
Bash MCP - Sandboxed bash command execution

Provides safe bash command execution with timeout, output limits, and security checks.
Supports background execution and output monitoring.
"""

import os
import re
import signal
import subprocess
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Dict, Optional, List


# Global registry for background shells
_BACKGROUND_SHELLS: Dict[str, "BackgroundShell"] = {}

# Output limits
MAX_OUTPUT_SIZE = 30_000  # characters
DEFAULT_TIMEOUT = 120  # seconds


class BashError(Exception):
    """Exception for bash execution errors."""
    pass


class BackgroundShell:
    """Manages a persistent background shell process."""

    def __init__(self, shell_id: str, cwd: Optional[str] = None):
        self.shell_id = shell_id
        self.cwd = cwd or os.getcwd()
        self.process: Optional[subprocess.Popen] = None
        self.output_buffer = deque(maxlen=1000)  # Keep last 1000 lines
        self.output_lock = threading.Lock()
        self.reader_thread: Optional[threading.Thread] = None
        self.started_at = time.time()
        self.last_read_index = 0

    def start(self):
        """Start the background shell."""
        self.process = subprocess.Popen(
            ["/bin/bash"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=self.cwd,
            text=True,
            bufsize=1
        )

        # Start output reader thread
        self.reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self.reader_thread.start()

    def _read_output(self):
        """Read output from process continuously."""
        if not self.process or not self.process.stdout:
            return

        for line in self.process.stdout:
            with self.output_lock:
                self.output_buffer.append((time.time(), line.rstrip()))

    def send_command(self, command: str):
        """Send a command to the shell."""
        if not self.process or not self.process.stdin:
            raise BashError("Shell not running")

        try:
            self.process.stdin.write(command + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise BashError(f"Failed to send command: {e}")

    def get_new_output(self, filter_regex: Optional[str] = None) -> List[str]:
        """Get new output since last read."""
        with self.output_lock:
            new_lines = []

            for timestamp, line in list(self.output_buffer)[self.last_read_index:]:
                if filter_regex:
                    try:
                        if re.search(filter_regex, line):
                            new_lines.append(line)
                    except re.error:
                        pass  # Skip invalid regex
                else:
                    new_lines.append(line)

            self.last_read_index = len(self.output_buffer)

            return new_lines

    def get_status(self) -> Dict[str, Any]:
        """Get shell status."""
        if not self.process:
            return {"status": "not_started"}

        poll = self.process.poll()

        if poll is None:
            return {
                "status": "running",
                "pid": self.process.pid,
                "uptime": time.time() - self.started_at
            }
        else:
            return {
                "status": "completed",
                "exit_code": poll,
                "uptime": time.time() - self.started_at
            }

    def kill(self):
        """Terminate the shell."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()


def execute_command(
    command: str,
    cwd: Optional[str] = None,
    timeout: Optional[int] = None,
    run_in_background: bool = False,
    description: Optional[str] = None,
    env: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Execute a bash command.

    Args:
        command: Command to execute
        cwd: Working directory
        timeout: Timeout in seconds (default: 120)
        run_in_background: Run as background process
        description: Human-readable description
        env: Environment variables to set

    Returns:
        Dict with execution results
    """
    timeout = timeout or DEFAULT_TIMEOUT
    cwd = cwd or os.getcwd()

    # Security checks
    _validate_command(command)

    if run_in_background:
        return _execute_background(command, cwd, description)
    else:
        return _execute_foreground(command, cwd, timeout, env)


def _validate_command(command: str):
    """Basic security validation of command."""
    # Block obviously dangerous patterns
    dangerous_patterns = [
        r'rm\s+-rf\s+/',  # rm -rf /
        r':\(\)\{.*\};',  # Fork bombs
        r'mkfs\.',  # Filesystem formatting
        r'dd\s+if=.*of=/dev/sd',  # Direct disk writes
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, command):
            raise BashError(f"Command contains dangerous pattern: {pattern}")

    # Warn about sudo (but don't block)
    if 'sudo' in command:
        print("Warning: Command contains 'sudo'")


def _execute_foreground(
    command: str,
    cwd: str,
    timeout: int,
    env: Optional[Dict[str, str]]
) -> Dict[str, Any]:
    """Execute command in foreground with timeout."""
    # Prepare environment
    exec_env = os.environ.copy()
    if env:
        exec_env.update(env)

    start_time = time.time()

    try:
        result = subprocess.run(
            ["/bin/bash", "-c", command],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=exec_env
        )

        elapsed = time.time() - start_time

        # Truncate output if too large
        stdout = result.stdout
        stderr = result.stderr

        if len(stdout) > MAX_OUTPUT_SIZE:
            stdout = stdout[:MAX_OUTPUT_SIZE] + f"\n... [truncated {len(stdout) - MAX_OUTPUT_SIZE} chars]"

        if len(stderr) > MAX_OUTPUT_SIZE:
            stderr = stderr[:MAX_OUTPUT_SIZE] + f"\n... [truncated {len(stderr) - MAX_OUTPUT_SIZE} chars]"

        return {
            "exit_code": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "elapsed_seconds": elapsed,
            "timed_out": False,
            "command": command
        }

    except subprocess.TimeoutExpired:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds",
            "elapsed_seconds": timeout,
            "timed_out": True,
            "command": command
        }

    except Exception as e:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Execution error: {str(e)}",
            "elapsed_seconds": time.time() - start_time,
            "timed_out": False,
            "command": command
        }


def _execute_background(command: str, cwd: str, description: Optional[str]) -> Dict[str, Any]:
    """Execute command in background."""
    shell_id = f"bash_{uuid.uuid4().hex[:8]}"

    shell = BackgroundShell(shell_id, cwd)
    shell.start()

    # Send command
    shell.send_command(command)

    # Register shell
    _BACKGROUND_SHELLS[shell_id] = shell

    return {
        "shell_id": shell_id,
        "status": "started",
        "command": command,
        "description": description,
        "message": f"Background shell started with ID: {shell_id}"
    }


def get_background_output(shell_id: str, filter_regex: Optional[str] = None) -> Dict[str, Any]:
    """
    Get output from a background shell.

    Args:
        shell_id: Shell identifier
        filter_regex: Optional regex to filter output lines

    Returns:
        Dict with new output since last check
    """
    if shell_id not in _BACKGROUND_SHELLS:
        raise BashError(f"Background shell not found: {shell_id}")

    shell = _BACKGROUND_SHELLS[shell_id]
    status = shell.get_status()
    output = shell.get_new_output(filter_regex)

    return {
        "shell_id": shell_id,
        "status": status["status"],
        "output": "\n".join(output),
        "lines": len(output),
        "shell_info": status
    }


def kill_background_shell(shell_id: str) -> Dict[str, Any]:
    """
    Kill a background shell.

    Args:
        shell_id: Shell identifier

    Returns:
        Dict with termination status
    """
    if shell_id not in _BACKGROUND_SHELLS:
        raise BashError(f"Background shell not found: {shell_id}")

    shell = _BACKGROUND_SHELLS[shell_id]
    shell.kill()

    # Remove from registry
    del _BACKGROUND_SHELLS[shell_id]

    return {
        "shell_id": shell_id,
        "status": "killed",
        "message": f"Background shell {shell_id} terminated"
    }


def list_background_shells() -> Dict[str, Any]:
    """List all active background shells."""
    shells = []

    for shell_id, shell in _BACKGROUND_SHELLS.items():
        status = shell.get_status()
        shells.append({
            "shell_id": shell_id,
            "status": status["status"],
            "cwd": shell.cwd,
            "started_at": shell.started_at,
            "uptime": status.get("uptime", 0)
        })

    return {
        "shells": shells,
        "count": len(shells)
    }


def execute_script(
    script_content: str,
    cwd: Optional[str] = None,
    timeout: Optional[int] = None,
    args: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Execute a bash script from string content.

    Args:
        script_content: Script content
        cwd: Working directory
        timeout: Timeout in seconds
        args: Script arguments

    Returns:
        Dict with execution results
    """
    import tempfile

    timeout = timeout or DEFAULT_TIMEOUT
    cwd = cwd or os.getcwd()

    # Create temporary script file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
        f.write(script_content)
        script_path = f.name

    try:
        # Make executable
        os.chmod(script_path, 0o755)

        # Build command
        cmd = [script_path]
        if args:
            cmd.extend(args)

        # Execute
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        # Truncate output
        stdout = result.stdout
        stderr = result.stderr

        if len(stdout) > MAX_OUTPUT_SIZE:
            stdout = stdout[:MAX_OUTPUT_SIZE] + f"\n... [truncated]"

        if len(stderr) > MAX_OUTPUT_SIZE:
            stderr = stderr[:MAX_OUTPUT_SIZE] + f"\n... [truncated]"

        return {
            "exit_code": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "script_path": script_path
        }

    except subprocess.TimeoutExpired:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Script timed out after {timeout} seconds",
            "script_path": script_path
        }

    finally:
        # Clean up
        try:
            os.unlink(script_path)
        except:
            pass
