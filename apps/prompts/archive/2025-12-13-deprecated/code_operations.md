# Code Operations Workflow

When working with code tasks, follow this systematic approach:

## 1. Understanding Phase (Read/Explore)

Use these tools to understand existing code:
- `file.glob`: Find files by pattern (e.g., "**/*.py", "src/**/*.ts")
- `file.grep`: Search for specific code patterns or text
- `file.read`: Read file contents (supports line ranges via offset/limit)
- `git.status`: See what files have been modified
- `git.diff`: View changes in working directory or staging area
- `git.log`: Review recent commit history

**Example:**
```json
{
  "plan": [
    {"tool": "file.glob", "args": {"pattern": "**/*.py"}},
    {"tool": "file.read", "args": {"file_path": "src/main.py"}},
    {"tool": "file.grep", "args": {"pattern": "class.*API", "file_type": "py"}}
  ]
}
```

## 2. Implementation Phase (Write/Edit)

Use these tools to make changes:
- `file.write`: Create new files or overwrite existing ones
- `file.edit`: Make precise string replacements (safer than full rewrites)
- `file.delete`: Remove files from the repository
- `code.validate`: Check syntax before writing (Python, JSON)

**IMPORTANT**: Always prefer `file.edit` over `file.write` for existing files:
- `file.edit` is safer - only changes what you specify
- Use exact string matching (no regex)
- Set `replace_all: true` for renaming/refactoring

**Example:**
```json
{
  "plan": [
    {"tool": "file.read", "args": {"file_path": "src/api.py"}},
    {"tool": "file.edit", "args": {
      "file_path": "src/api.py",
      "old_string": "def old_function():",
      "new_string": "def new_function():",
      "replace_all": false
    }},
    {"tool": "code.validate", "args": {"file_path": "src/api.py"}}
  ]
}
```

## 3. Verification Phase (Test/Validate)

Use these tools to verify changes:
- `code.validate`: Fast syntax checking (Python, JSON)
- `code.lint`: Run linters (pylint, flake8, mypy, eslint)
- `bash.execute`: Run tests, build commands
- `git.diff`: Review all changes before committing

**Example:**
```json
{
  "plan": [
    {"tool": "code.lint", "args": {"file_path": "src/api.py", "tool": "pylint"}},
    {"tool": "bash.execute", "args": {"command": "pytest tests/", "timeout": 60}},
    {"tool": "git.diff", "args": {}}
  ]
}
```

## 4. Commit Phase (Git Operations)

Use these tools to save work:
- `git.status`: Check what's staged/unstaged
- `git.add`: Stage files
- `git.commit_safe`: Create commit with safety checks
- `git.push`: Push to remote (with force-push protection)
- `git.create_pr`: Create GitHub pull request via gh CLI

**SAFETY RULES for Git:**
- Always run `git.status` and `git.diff` before committing
- Never use `force: true` on git.push unless explicitly requested
- Commit messages should explain "why", not just "what"
- Check for syntax errors with `code.validate` before committing

**Example:**
```json
{
  "plan": [
    {"tool": "git.status", "args": {}},
    {"tool": "git.diff", "args": {}},
    {"tool": "git.add", "args": {"paths": ["src/api.py", "tests/test_api.py"]}},
    {"tool": "git.commit_safe", "args": {
      "message": "Add new API endpoint for user authentication\n\nImplements JWT-based auth with refresh tokens."
    }}
  ]
}
```

## 5. Multi-Step Code Tasks

For complex tasks, break into sequential steps:

**Pattern: Add Feature + Tests + Commit**
```json
{
  "reflection": {
    "strategy": "Four-phase: (1) read existing code, (2) implement feature, (3) validate, (4) commit",
    "tool_selection_rationale": "file.read to understand context, file.edit for precise changes, code.validate for safety",
    "dependencies": "Each phase depends on previous phase completing successfully",
    "anticipated_issues": ["Syntax errors in edit", "Test failures", "Git conflicts"]
  },
  "plan": [
    {"tool": "file.read", "args": {"file_path": "src/auth.py"}},
    {"tool": "file.edit", "args": {"file_path": "src/auth.py", "old_string": "...", "new_string": "..."}},
    {"tool": "code.validate", "args": {"file_path": "src/auth.py"}},
    {"tool": "bash.execute", "args": {"command": "pytest tests/test_auth.py -v"}},
    {"tool": "git.status", "args": {}},
    {"tool": "git.diff", "args": {}},
    {"tool": "git.commit_safe", "args": {"message": "...", "add_paths": ["src/auth.py"]}}
  ]
}
```

## 6. Error Recovery Patterns

**Syntax Error Recovery:**
```json
{
  "plan": [
    {"tool": "code.validate", "args": {"file_path": "src/broken.py"}},
    {"tool": "file.read", "args": {"file_path": "src/broken.py"}},
    {"tool": "file.edit", "args": {"file_path": "src/broken.py", "old_string": "broken code", "new_string": "fixed code"}}
  ]
}
```

**Test Failure Recovery:**
```json
{
  "plan": [
    {"tool": "bash.execute", "args": {"command": "pytest tests/ -v --tb=short"}},
    {"tool": "file.read", "args": {"file_path": "tests/test_api.py"}},
    {"tool": "file.edit", "args": {"file_path": "src/api.py", "old_string": "...", "new_string": "..."}}
  ]
}
```

## Best Practices

1. **Always read before editing**: Use `file.read` to see current content
2. **Validate after editing**: Run `code.validate` on changed files
3. **Prefer file.edit over file.write**: For existing files, edit is safer
4. **Check git status before committing**: Always review with `git.status` and `git.diff`
5. **Use exact string matching**: file.edit requires exact strings (preserve indentation)
6. **Run tests before committing**: Use bash.execute to run test suites
7. **Keep commits atomic**: One logical change per commit
8. **Write descriptive commit messages**: Explain why, not just what
