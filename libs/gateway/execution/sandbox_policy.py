"""
Code Sandbox Policy - Security boundaries for code execution.

Defines allowlisted modules, execution timeouts, and install restrictions
for sandboxed code execution.

Architecture Reference:
- architecture/BENCHMARK_ALIGNMENT.md (code sandbox policy)
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class SandboxPolicy:
    """
    Security policy for sandboxed code execution.

    Defines what is allowed and forbidden in the sandbox.
    """

    # Allowed standard library modules
    allowed_stdlib: Set[str] = field(default_factory=lambda: {
        "json", "csv", "math", "statistics", "datetime", "re",
        "collections", "itertools", "functools", "operator",
        "string", "textwrap", "unicodedata",
        "pathlib", "os.path", "glob", "fnmatch",
        "io", "tempfile",
        "copy", "pprint",
        "hashlib", "hmac", "base64",
        "decimal", "fractions",
        "random", "secrets",
        "typing", "dataclasses", "enum",
        "logging", "warnings",
        "unittest", "pytest",
        "time", "calendar",
    })

    # Allowed third-party packages
    allowed_packages: Set[str] = field(default_factory=lambda: {
        "openpyxl", "pandas", "numpy",
        "python-docx", "docx",
        "PyMuPDF", "fitz",
        "python-pptx", "pptx",
        "icalendar",
        "pyyaml", "yaml",
        "requests",
        "beautifulsoup4", "bs4",
        "Pillow", "PIL",
        "matplotlib",
    })

    # Blocked modules (always forbidden)
    blocked_modules: Set[str] = field(default_factory=lambda: {
        "subprocess", "shutil", "sys",
        "ctypes", "cffi",
        "socket", "http.server", "xmlrpc",
        "multiprocessing",
        "importlib", "__import__",
        "code", "codeop", "compile",
        "exec", "eval",
        "pickle", "shelve", "marshal",
        "webbrowser",
        "smtplib", "poplib", "imaplib",  # Direct email sending
    })

    # Blocked builtins
    blocked_builtins: Set[str] = field(default_factory=lambda: {
        "exec", "eval", "compile",
        "__import__", "globals", "locals",
        "breakpoint", "exit", "quit",
    })

    # Execution limits
    max_execution_time_seconds: int = 30
    max_memory_mb: int = 256
    max_output_size_bytes: int = 1024 * 1024  # 1MB
    max_file_size_bytes: int = 10 * 1024 * 1024  # 10MB
    max_files_created: int = 20

    # Filesystem restrictions
    allowed_write_dirs: List[str] = field(default_factory=lambda: [
        "/tmp",
        "panda_system_docs/",
        "artifacts/",
    ])

    # Network restrictions
    allow_network: bool = False
    allowed_hosts: Set[str] = field(default_factory=set)

    # Install restrictions
    allow_pip_install: bool = False
    allowed_pip_packages: Set[str] = field(default_factory=set)

    def is_module_allowed(self, module_name: str) -> bool:
        """Check if a module import is allowed."""
        # Check blocked list first
        base_module = module_name.split(".")[0]
        if base_module in self.blocked_modules or module_name in self.blocked_modules:
            return False

        # Check allowed lists
        if base_module in self.allowed_stdlib:
            return True
        if base_module in self.allowed_packages:
            return True

        return False

    def is_builtin_allowed(self, name: str) -> bool:
        """Check if a builtin function is allowed."""
        return name not in self.blocked_builtins

    def is_write_path_allowed(self, path: str) -> bool:
        """Check if writing to a path is allowed."""
        for allowed_dir in self.allowed_write_dirs:
            if path.startswith(allowed_dir) or path.startswith("/" + allowed_dir):
                return True
        return False

    def validate_code(self, code: str) -> List[str]:
        """
        Validate code against policy.

        Args:
            code: Python source code to validate

        Returns:
            List of violation descriptions (empty if valid)
        """
        import ast

        violations = []

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return [f"Syntax error: {e}"]

        for node in ast.walk(tree):
            # Check imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not self.is_module_allowed(alias.name):
                        violations.append(f"Blocked import: {alias.name}")

            elif isinstance(node, ast.ImportFrom):
                if node.module and not self.is_module_allowed(node.module):
                    violations.append(f"Blocked import: {node.module}")

            # Check blocked function calls
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if not self.is_builtin_allowed(node.func.id):
                        violations.append(f"Blocked builtin: {node.func.id}")

            # Check os.system, subprocess.run, etc.
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    full_name = f"{node.value.id}.{node.attr}"
                    if full_name in ("os.system", "os.popen", "os.exec",
                                     "os.execv", "os.execvp", "os.spawn"):
                        violations.append(f"Blocked call: {full_name}")

        return violations

    def to_dict(self) -> Dict[str, Any]:
        """Serialize policy to dict."""
        return {
            "allowed_stdlib": sorted(self.allowed_stdlib),
            "allowed_packages": sorted(self.allowed_packages),
            "blocked_modules": sorted(self.blocked_modules),
            "blocked_builtins": sorted(self.blocked_builtins),
            "max_execution_time_seconds": self.max_execution_time_seconds,
            "max_memory_mb": self.max_memory_mb,
            "max_output_size_bytes": self.max_output_size_bytes,
            "max_file_size_bytes": self.max_file_size_bytes,
            "max_files_created": self.max_files_created,
            "allowed_write_dirs": self.allowed_write_dirs,
            "allow_network": self.allow_network,
            "allow_pip_install": self.allow_pip_install,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SandboxPolicy":
        """Deserialize policy from dict."""
        policy = cls()
        if "allowed_stdlib" in data:
            policy.allowed_stdlib = set(data["allowed_stdlib"])
        if "allowed_packages" in data:
            policy.allowed_packages = set(data["allowed_packages"])
        if "blocked_modules" in data:
            policy.blocked_modules = set(data["blocked_modules"])
        if "max_execution_time_seconds" in data:
            policy.max_execution_time_seconds = data["max_execution_time_seconds"]
        if "max_memory_mb" in data:
            policy.max_memory_mb = data["max_memory_mb"]
        if "allow_network" in data:
            policy.allow_network = data["allow_network"]
        return policy


# Default policies for different contexts
STRICT_POLICY = SandboxPolicy(
    max_execution_time_seconds=10,
    max_memory_mb=128,
    allow_network=False,
    allow_pip_install=False,
)

STANDARD_POLICY = SandboxPolicy()

PERMISSIVE_POLICY = SandboxPolicy(
    max_execution_time_seconds=120,
    max_memory_mb=512,
    allow_network=True,
    allowed_hosts={"api.github.com", "pypi.org"},
    allow_pip_install=True,
    allowed_pip_packages={"requests", "beautifulsoup4", "pandas"},
)


def get_sandbox_policy(level: str = "standard") -> SandboxPolicy:
    """
    Get sandbox policy by security level.

    Args:
        level: Security level (strict, standard, permissive)

    Returns:
        SandboxPolicy instance
    """
    policies = {
        "strict": STRICT_POLICY,
        "standard": STANDARD_POLICY,
        "permissive": PERMISSIVE_POLICY,
    }
    return policies.get(level, STANDARD_POLICY)
