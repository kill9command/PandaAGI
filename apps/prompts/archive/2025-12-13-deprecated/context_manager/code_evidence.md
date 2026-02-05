# Context Manager - Code Evidence Processing

When processing code operation bundles, extract structured code-specific facts and maintain coding session state.

---

## Coding Turn Summary Schema

Extract these fields from code operation results:

```json
{
  "module": "authentication",
  "files_touched": ["src/auth.py", "tests/test_auth.py"],
  "change_type": "feature_addition|bug_fix|refactor|test_creation|documentation",
  "verification": {
    "tests_run": true,
    "tests_passed": 12,
    "tests_failed": 0,
    "lint_issues": 0,
    "type_errors": 0,
    "status": "pass|fail|partial|skipped"
  },
  "artifacts": {
    "diff_handle": "artifact_abc123",
    "test_output_handle": "artifact_def456",
    "outline_handle": "artifact_ghi789"
  },
  "pending_issues": []
}
```

---

## Evidence Extraction Rules

### From code.verify_suite Results

**Input**:
```json
{
  "tests": {"passed": 10, "failed": 2, "total": 12, "errors": ["test_login_invalid", "test_refresh_expired"]},
  "lint": {"issues": 3, "details": ["line too long: auth.py:120"]},
  "summary": "❌ 2/12 tests failed, ⚠️ 3 lint issues"
}
```

**Output Claim**:
```json
{
  "claim_id": "verification_abc123",
  "summary": "Tests: 10/12 passed; Failures: test_login_invalid, test_refresh_expired; Lint: 3 issues",
  "confidence": 0.7,
  "evidence": ["test_output_artifact_handle"],
  "repo_facts": {
    "test_status": "10/12 passed",
    "failed_tests": ["test_login_invalid", "test_refresh_expired"],
    "lint_issues": 3
  }
}
```

**Pending Task**:
```
"Fix failing tests: test_login_invalid, test_refresh_expired in tests/test_auth.py"
```

### From git.diff Results

**Input**:
```json
{
  "diff_text": "diff --git a/src/auth.py\n+def refresh_token(self, token):\n+    ...",
  "files_changed": 1
}
```

**Output Claim**:
```json
{
  "claim_id": "change_abc123",
  "summary": "Modified src/auth.py: added refresh_token method (+15 lines, -2 lines)",
  "confidence": 1.0,
  "evidence": ["diff_artifact_handle"],
  "repo_facts": {
    "files_modified": ["src/auth.py"],
    "lines_added": 15,
    "lines_removed": 2,
    "change_summary": "Added refresh_token method"
  }
}
```

### From repo.scope_discover Results

**Input**:
```json
{
  "impacted_files": ["src/auth.py", "src/tokens.py", "tests/test_auth.py"],
  "dependencies": {"src/auth.py": ["jwt", "database"]},
  "file_summaries": {"src/auth.py": {"lines": 150, "language": "python"}}
}
```

**Output Claim**:
```json
{
  "claim_id": "scope_abc123",
  "summary": "Authentication module: 3 files (auth.py, tokens.py, test_auth.py); Dependencies: jwt, database",
  "confidence": 0.9,
  "repo_facts": {
    "module": "authentication",
    "core_files": ["src/auth.py", "src/tokens.py"],
    "test_files": ["tests/test_auth.py"],
    "dependencies": ["jwt", "database"]
  }
}
```

### From file.read_outline Results

**Input**:
```json
{
  "symbols": [
    {"type": "class", "name": "AuthManager", "line": 42, "docstring": "Manages authentication"},
    {"type": "function", "name": "login", "line": 67, "docstring": "User login"}
  ],
  "file_info": {"lines": 150, "size_kb": 8}
}
```

**Output Claim**:
```json
{
  "claim_id": "outline_abc123",
  "summary": "auth.py structure: AuthManager class (L42), login function (L67); 150 lines total",
  "confidence": 1.0,
  "evidence": ["outline_artifact_handle"],
  "repo_facts": {
    "file": "src/auth.py",
    "classes": ["AuthManager"],
    "functions": ["login", "logout", "refresh_token"],
    "lines": 150
  }
}
```

---

## Pending Tasks Logic

### Auto-Create Pending Task When:

1. **Test Failures Detected**:
   - Format: `"Fix failing test: {test_name} in {file}:{line}"`
   - Priority: HIGH if syntax error, MEDIUM if assertion failure
   - Extract test name and file from error output

2. **Linter Issues Detected**:
   - Format: `"Address {count} lint issues in {files}"`
   - Priority: LOW (doesn't block functionality)
   - Group by file

3. **Type Errors Detected**:
   - Format: `"Fix {count} type errors in {files}"`
   - Priority: MEDIUM
   - Extract error locations

4. **TODO/FIXME Comments Found** (from grep results):
   - Format: `"Review TODO at {file}:{line}: {comment}"`
   - Priority: LOW
   - Only create if explicitly searched for

### Mark Completed When:
- Subsequent turn shows all tests passing
- Lint issues = 0 in next run
- User explicitly says "done" or "fixed"

---

## Multi-File Change Chunking

When bundle contains multiple file operations, create **separate claims per file**:

**Example**:
```
Ticket: "Refactor authentication module"
Files edited: src/auth.py, src/tokens.py, tests/test_auth.py

Generate 3 claims:
1. "Modified src/auth.py: added refresh_token method (+20 lines)"
   - evidence: [diff_auth_artifact]
   - related_claims: ["change_def456", "change_ghi789"]

2. "Updated src/tokens.py: new validate_refresh_token helper (+10 lines)"
   - evidence: [diff_tokens_artifact]
   - related_claims: ["change_abc123", "change_ghi789"]

3. "Added tests in test_auth.py: test_refresh_token (+15 lines)"
   - evidence: [diff_test_artifact]
   - related_claims: ["change_abc123", "change_def456"]
```

**Token Budget per Claim**: ≤200 tokens

**Cross-Linking**: Use `related_claims` array to link multi-file changes

---

## Session Context Updates

After processing code bundle, populate turn_updates for LiveSessionContext:

```python
turn_updates = {
    # Extract repo from tool calls
    "code_repo": extract_repository_from_tools(tool_records),

    # Extract git state from git.status results
    "code_state_updates": {
        "branch": git_status_result.get("branch"),
        "modified": git_status_result.get("modified", []),
        "test_status": verify_suite_result.get("summary"),
        "last_action": format_action_summary(tool_records)
    },

    # Extract pending tasks from failures
    "new_tasks": pending_tasks_list,

    # Extract facts from claims
    "facts": {
        "code": [
            "Authentication module has 3 core files",
            "Tests: 12/12 passing",
            "JWT dependency used for tokens"
        ]
    }
}
```

**Use Existing Extractors**:
- `extract_repository_from_tools(tool_records)`
- `extract_git_state(tool_records)`
- `extract_test_results(tool_records)`

---

## Durable Knowledge Criteria

Save to `long_term_memories` when discovering:

### Architectural Decisions
```json
{
  "key": "auth_architecture",
  "value": "JWT-based: 1h access tokens, 7d refresh tokens; tokens.py handles validation",
  "domain": "code",
  "confidence": 0.95,
  "source": "claim_abc123"
}
```

### Code Patterns
```json
{
  "key": "helper_function_pattern",
  "value": "Helper functions use pattern: validate_X() in utils/, returns tuple (valid: bool, error: str)",
  "domain": "code",
  "confidence": 0.85,
  "source": "claim_def456"
}
```

### Test Strategies
```json
{
  "key": "test_strategy_auth",
  "value": "Integration tests mock database; unit tests use fixtures from conftest.py",
  "domain": "code",
  "confidence": 0.90,
  "source": "claim_ghi789"
}
```

### Code Conventions
```json
{
  "key": "error_handling_convention",
  "value": "Raise CustomError with context dict: {'code': 'ERR_AUTH', 'details': {...}}",
  "domain": "code",
  "confidence": 0.95,
  "source": "claim_jkl012"
}
```

**When to Save**:
- Pattern appears in 2+ files → save as convention
- Explicit architectural decision in commit message
- Test coverage >80% for module → save test strategy

---

## Claim Confidence Scoring

**High Confidence (0.9-1.0)**:
- Direct evidence from tool output (git.diff, file.read_outline)
- Verified test results (pass/fail is clear)
- Exact file changes captured

**Medium Confidence (0.6-0.8)**:
- Inferred from indirect evidence (scope discovery)
- Test failures without clear root cause
- Dependency relationships

**Low Confidence (0.3-0.5)**:
- Assumptions based on partial data
- TODO items (not yet verified)
- Suggested refactorings

---

## Token Budget Guidelines

**Per Claim**: ≤200 tokens
- Summary: ≤50 tokens
- Evidence handles: ≤20 tokens
- Repo facts: ≤100 tokens
- Related claims: ≤30 tokens

**Total Claims per Turn**: ≤10 claims (2000 tokens max)

**If Exceeding Budget**:
1. Consolidate related claims
2. Summarize large diffs (e.g., "+50 lines across 3 methods")
3. Store full diff in artifact, reference by handle

---

## Output to Gateway

Return capsule with code-enriched claims:

```json
{
  "claim_summaries": {
    "verification_abc123": "Tests: 12/12 passed; All checks clean",
    "change_def456": "Modified src/auth.py: added refresh_token (+20 lines)",
    "scope_ghi789": "Auth module: 3 files, JWT dependency"
  },
  "turn_summary": {
    "short": "Added refresh_token to auth.py, all tests pass",
    "bullets": [
      "Modified src/auth.py: new refresh_token method",
      "Tests: 12/12 passing",
      "No lint or type errors"
    ],
    "tokens": 150
  },
  "session_updates": {
    "code_repo": "/home/user/project",
    "code_state": {
      "branch": "main",
      "modified": ["src/auth.py"],
      "test_status": "12/12 passed"
    },
    "new_tasks": [],
    "facts": {...}
  },
  "long_term_memories": [
    {"key": "auth_refresh_token", "value": "...", "domain": "code"}
  ]
}
```

This enriched capsule enables:
- Guide synthesis with code context
- Session state persistence across turns
- Durable architectural knowledge capture
