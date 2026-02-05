"""
Repository scope discovery tool.

Analyzes repository to find impacted files and dependency graphs.
Replaces multiple manual file operations with one intelligent scan.
"""
import os
import subprocess
import re
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class RepoScopeAnalyzer:
    """Analyzes repository scope for a given goal."""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)
        if not self.repo_path.exists():
            raise ValueError(f"Repository path does not exist: {repo_path}")

    async def discover(
        self,
        goal: str,
        search_patterns: Optional[List[str]] = None,
        max_files: int = 20
    ) -> Dict[str, Any]:
        """
        Discover repository scope for a goal.

        Args:
            goal: Natural language goal (e.g., "authentication module")
            search_patterns: Optional grep patterns to find related files
            max_files: Maximum files to analyze (default: 20)

        Returns:
            {
                "impacted_files": [...],
                "dependencies": {...},
                "suggested_subtasks": [...],
                "file_summaries": {...},
                "search_patterns": [...]
            }
        """
        # Auto-detect patterns from goal
        if not search_patterns:
            search_patterns = self._goal_to_patterns(goal)

        # Find files matching patterns
        impacted_files = await self._find_files(search_patterns, max_files)

        # Analyze dependencies (imports, requires)
        dependencies = await self._analyze_dependencies(impacted_files[:10])  # Limit deps analysis

        # Get file summaries (line counts, main symbols)
        file_summaries = await self._summarize_files(impacted_files[:15])  # Limit summaries

        # Generate suggested subtasks
        suggested_subtasks = self._generate_subtasks(impacted_files, goal)

        return {
            "impacted_files": impacted_files,
            "dependencies": dependencies,
            "suggested_subtasks": suggested_subtasks,
            "file_summaries": file_summaries,
            "search_patterns": search_patterns
        }

    def _goal_to_patterns(self, goal: str) -> List[str]:
        """Convert natural language goal to grep patterns."""
        goal_lower = goal.lower()
        patterns = []

        # Domain-specific keywords
        if "auth" in goal_lower:
            patterns.extend(["auth", "login", "logout", "session", "token", "credential"])
        if "test" in goal_lower:
            patterns.extend(["test", "spec", "assert"])
        if "api" in goal_lower:
            patterns.extend(["api", "endpoint", "route", "handler"])
        if "database" in goal_lower or "db" in goal_lower:
            patterns.extend(["database", "db", "query", "model", "schema"])
        if "ui" in goal_lower or "interface" in goal_lower:
            patterns.extend(["component", "view", "template", "render"])

        # Fallback: use significant goal words
        if not patterns:
            words = re.findall(r'\b\w{4,}\b', goal_lower)  # Words 4+ chars
            patterns = words[:5]  # Max 5 patterns

        return patterns if patterns else ["todo"]  # Final fallback

    async def _find_files(self, patterns: List[str], max_files: int) -> List[str]:
        """Find files matching patterns using git grep."""
        try:
            # Build regex pattern
            pattern_regex = "|".join(re.escape(p) for p in patterns)

            # Use git grep for speed (if in git repo)
            cmd = ["git", "grep", "-l", "-i", "-E", pattern_regex]
            result = subprocess.run(
                cmd,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                files = result.stdout.strip().split("\n")
                # Filter and sort
                files = [f for f in files if f and not self._should_ignore(f)]
                return files[:max_files]
        except subprocess.TimeoutExpired:
            logger.warning("git grep timed out")
        except Exception as e:
            logger.warning(f"git grep failed: {e}, falling back to walk")

        # Fallback: walk directory
        return await self._fallback_find_files(patterns, max_files)

    def _should_ignore(self, file_path: str) -> bool:
        """Check if file should be ignored."""
        ignore_patterns = [
            '.git/', '__pycache__/', 'node_modules/', '.venv/', 'venv/',
            '.pyc', '.so', '.o', '.log', '.lock', 'package-lock.json'
        ]
        return any(pattern in file_path for pattern in ignore_patterns)

    async def _fallback_find_files(self, patterns: List[str], max_files: int) -> List[str]:
        """Fallback file finding using os.walk."""
        files = []
        pattern_regex = re.compile("|".join(patterns), re.IGNORECASE)

        for root, dirs, filenames in os.walk(self.repo_path):
            # Skip ignored dirs
            dirs[:] = [d for d in dirs if not self._should_ignore(d + '/')]

            for filename in filenames:
                if self._should_ignore(filename):
                    continue

                rel_path = os.path.relpath(os.path.join(root, filename), self.repo_path)

                # Check if filename or path matches pattern
                if pattern_regex.search(rel_path):
                    files.append(rel_path)
                    if len(files) >= max_files:
                        return files

        return files

    async def _analyze_dependencies(self, files: List[str]) -> Dict[str, List[str]]:
        """Analyze import dependencies between files."""
        deps = {}

        for file_path in files:
            full_path = self.repo_path / file_path
            if not full_path.exists():
                continue

            try:
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read(50000)  # Read first 50KB only

                # Extract imports based on language
                if file_path.endswith('.py'):
                    imports = self._extract_python_imports(content)
                elif file_path.endswith(('.js', '.ts', '.jsx', '.tsx')):
                    imports = self._extract_js_imports(content)
                else:
                    imports = []

                if imports:
                    deps[file_path] = imports[:10]  # Cap at 10 imports

            except Exception as e:
                logger.debug(f"Could not analyze {file_path}: {e}")

        return deps

    def _extract_python_imports(self, content: str) -> List[str]:
        """Extract import statements from Python code."""
        imports = []

        # Match: import X, from X import Y
        for match in re.finditer(r'^(?:from\s+([\w\.]+)|import\s+([\w\.]+))', content, re.MULTILINE):
            module = match.group(1) or match.group(2)
            if module and not module.startswith('.'):  # Skip relative imports
                imports.append(module.split('.')[0])  # Just top-level module

        return list(set(imports))[:15]  # Dedupe, cap at 15

    def _extract_js_imports(self, content: str) -> List[str]:
        """Extract import statements from JavaScript/TypeScript."""
        imports = []

        # Match: import X from 'Y', require('Y')
        patterns = [
            r'import\s+.*?from\s+[\'"]([^\'"]+)[\'"]',
            r'require\s*\([\'"]([^\'"]+)[\'"]\)'
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, content):
                module = match.group(1)
                if module and not module.startswith('.'):  # Skip relative imports
                    imports.append(module.split('/')[0])  # Just package name

        return list(set(imports))[:15]  # Dedupe, cap at 15

    def _generate_subtasks(self, files: List[str], goal: str) -> List[Dict[str, str]]:
        """Generate suggested subtasks based on discovered files."""
        subtasks = []

        # Group files by type
        py_files = [f for f in files if f.endswith('.py')]
        js_files = [f for f in files if f.endswith(('.js', '.ts', '.jsx', '.tsx'))]
        test_files = [f for f in files if 'test' in f.lower()]
        src_files = [f for f in py_files + js_files if 'test' not in f.lower()]

        # Suggest reading main files
        if src_files:
            for f in src_files[:3]:  # Top 3
                subtasks.append({
                    "kind": "code",
                    "tool": "file.read_outline",
                    "q": f,
                    "why": f"understand {os.path.basename(f)} structure"
                })

        # Suggest checking tests if goal mentions testing
        if test_files and ("test" in goal.lower() or "verify" in goal.lower()):
            subtasks.append({
                "kind": "code",
                "tool": "code.verify_suite",
                "q": "tests",
                "why": "verify test coverage and status"
            })

        # Suggest git status if multiple files
        if len(files) > 5:
            subtasks.append({
                "kind": "code",
                "q": "git.status",
                "why": "check repository state"
            })

        return subtasks[:5]  # Cap at 5 suggestions

    async def _summarize_files(self, files: List[str]) -> Dict[str, Dict[str, Any]]:
        """Get basic summaries of files (line count, size)."""
        summaries = {}

        for file_path in files:
            full_path = self.repo_path / file_path
            if not full_path.exists():
                continue

            try:
                stat = full_path.stat()

                # Count lines efficiently
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = sum(1 for _ in f)

                summaries[file_path] = {
                    "lines": lines,
                    "size_kb": stat.st_size // 1024,
                    "language": self._detect_language(file_path)
                }
            except Exception:
                pass

        return summaries

    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension."""
        ext = Path(file_path).suffix
        lang_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.jsx': 'jsx',
            '.tsx': 'tsx',
            '.java': 'java',
            '.go': 'go',
            '.rs': 'rust',
            '.c': 'c',
            '.cpp': 'cpp',
            '.rb': 'ruby'
        }
        return lang_map.get(ext, 'unknown')


# MCP endpoint
async def repo_scope_discover(
    goal: str,
    repo: str,
    search_patterns: Optional[List[str]] = None,
    max_files: int = 20,
    **kwargs
) -> Dict[str, Any]:
    """
    MCP tool: Discover repository scope for a goal.

    Tool signature:
    {
        "name": "repo.scope_discover",
        "description": "Analyze repository to find impacted files, dependencies, and generate subtask suggestions",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "Natural language goal (e.g., 'authentication module')"},
                "repo": {"type": "string", "description": "Repository path"},
                "search_patterns": {"type": "array", "items": {"type": "string"}, "optional": true},
                "max_files": {"type": "integer", "default": 20, "optional": true}
            },
            "required": ["goal", "repo"]
        }
    }

    Args:
        goal: Natural language description (e.g., "authentication module")
        repo: Repository absolute path
        search_patterns: Optional list of patterns (auto-detected if not provided)
        max_files: Maximum files to analyze (default: 20)

    Returns:
        {
            "impacted_files": List of relevant file paths,
            "dependencies": Dict mapping files to their imports,
            "suggested_subtasks": List of recommended next steps,
            "file_summaries": Basic info for each file,
            "search_patterns": Patterns used for search
        }
    """
    try:
        analyzer = RepoScopeAnalyzer(repo)
        return await analyzer.discover(goal, search_patterns, max_files)
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"repo.scope_discover failed: {e}")
        return {"error": f"Analysis failed: {str(e)}"}
