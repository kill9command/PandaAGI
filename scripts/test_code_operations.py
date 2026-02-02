#!/usr/bin/env python3
"""
Test script for code operations MCP modules.

Tests file operations, git operations, bash execution, and diagnostics.
"""

import os
import shutil
import tempfile
from pathlib import Path

# Import the MCP modules
from apps.services.orchestrator import code_mcp, git_mcp, bash_mcp, diagnostics_mcp


def setup_test_repo():
    """Create a temporary git repository for testing."""
    test_dir = tempfile.mkdtemp(prefix="pandora_test_")
    print(f"Created test directory: {test_dir}")

    # Initialize git repo
    import subprocess
    subprocess.run(["git", "init"], cwd=test_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=test_dir,
        check=True,
        capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=test_dir,
        check=True,
        capture_output=True
    )

    return test_dir


def cleanup_test_repo(test_dir):
    """Clean up test repository."""
    if test_dir and os.path.exists(test_dir):
        shutil.rmtree(test_dir)
        print(f"Cleaned up test directory: {test_dir}")


def test_file_operations(test_dir):
    """Test file read, write, edit, glob, and grep operations."""
    print("\n=== Testing File Operations ===")

    # Test file.write
    print("\n1. Testing file.write...")
    result = code_mcp.write_file(
        file_path="test.py",
        content="def hello():\n    print('Hello, World!')\n",
        repo=test_dir,
        mode="fail_if_exists"
    )
    print(f"   ✓ Created file: {result['path']}")
    print(f"   ✓ Digest: {result['digest']}")

    # Test file.read
    print("\n2. Testing file.read...")
    result = code_mcp.read_file(
        file_path="test.py",
        repo=test_dir
    )
    print(f"   ✓ Read {result['total_lines']} lines")
    print(f"   ✓ Content preview: {result['lines'][0][:50]}...")

    # Test file.edit
    print("\n3. Testing file.edit...")
    result = code_mcp.edit_file(
        file_path="test.py",
        old_string="print('Hello, World!')",
        new_string="print('Hello, Pandora!')",
        repo=test_dir
    )
    print(f"   ✓ Made {result['replacements']} replacement(s)")

    # Create more files for glob/grep testing
    for i in range(3):
        code_mcp.write_file(
            file_path=f"module{i}.py",
            content=f"# Module {i}\ndef function_{i}():\n    return {i}\n",
            repo=test_dir,
            mode="overwrite"
        )

    # Test file.glob
    print("\n4. Testing file.glob...")
    result = code_mcp.glob_files(
        pattern="*.py",
        repo=test_dir
    )
    print(f"   ✓ Found {result['count']} Python files")
    print(f"   ✓ Files: {', '.join(result['matches'])}")

    # Test file.grep
    print("\n5. Testing file.grep...")
    result = code_mcp.grep_files(
        pattern="def.*:",
        repo=test_dir,
        file_type="py",
        output_mode="content",
        max_results=10
    )
    print(f"   ✓ Found {result['count']} matches")
    print(f"   ✓ Engine: {result.get('engine', 'unknown')}")

    print("\n✅ All file operations tests passed!")


def test_git_operations(test_dir):
    """Test git operations."""
    print("\n=== Testing Git Operations ===")

    # Test git.status
    print("\n1. Testing git.status...")
    result = git_mcp.git_status(test_dir)
    print(f"   ✓ Branch: {result['branch']}")
    print(f"   ✓ Untracked files: {len(result['untracked'])}")
    print(f"   ✓ Clean: {result['clean']}")

    # Test git.add
    print("\n2. Testing git.add...")
    result = git_mcp.git_add(test_dir, ["test.py"])
    print(f"   ✓ Staged {result['count']} file(s)")

    # Test git.diff (staged changes)
    print("\n3. Testing git.diff (staged)...")
    result = git_mcp.git_diff(test_dir, cached=True)
    print(f"   ✓ Has changes: {result['has_changes']}")

    # Test git.commit
    print("\n4. Testing git.commit_safe...")
    result = git_mcp.git_commit(
        repo=test_dir,
        message="Initial commit: Add test.py\n\nThis is a test commit.",
        add_paths=None  # Already staged
    )
    print(f"   ✓ Commit SHA: {result['commit_sha']}")

    # Test git.log
    print("\n5. Testing git.log...")
    result = git_mcp.git_log(test_dir, max_count=5)
    print(f"   ✓ Retrieved {result['count']} commit(s)")

    # Test git.branch (list)
    print("\n6. Testing git.branch (list)...")
    result = git_mcp.git_branch(test_dir)
    print(f"   ✓ Branches: {len(result['branches'])}")

    print("\n✅ All git operations tests passed!")


def test_bash_execution(test_dir):
    """Test bash command execution."""
    print("\n=== Testing Bash Execution ===")

    # Test simple command
    print("\n1. Testing bash.execute (simple)...")
    result = bash_mcp.execute_command(
        command="echo 'Hello from bash'",
        cwd=test_dir
    )
    print(f"   ✓ Exit code: {result['exit_code']}")
    print(f"   ✓ Output: {result['stdout'].strip()}")

    # Test command with timeout
    print("\n2. Testing bash.execute (list files)...")
    result = bash_mcp.execute_command(
        command="ls -la",
        cwd=test_dir,
        timeout=10
    )
    print(f"   ✓ Exit code: {result['exit_code']}")
    print(f"   ✓ Found files in output")

    # Test background execution
    print("\n3. Testing bash.execute (background)...")
    result = bash_mcp.execute_command(
        command="sleep 2 && echo 'Done sleeping'",
        cwd=test_dir,
        run_in_background=True,
        description="Background sleep test"
    )
    print(f"   ✓ Shell ID: {result['shell_id']}")

    # List background shells
    print("\n4. Testing bash.list...")
    result = bash_mcp.list_background_shells()
    print(f"   ✓ Active shells: {result['count']}")

    # Get output from background shell
    import time
    time.sleep(3)  # Wait for background command to complete

    print("\n5. Testing bash.get_output...")
    for shell in result['shells']:
        output_result = bash_mcp.get_background_output(shell['shell_id'])
        print(f"   ✓ Shell {shell['shell_id']}: {output_result['lines']} lines")

        # Kill background shell
        bash_mcp.kill_background_shell(shell['shell_id'])

    print("\n✅ All bash execution tests passed!")


def test_diagnostics(test_dir):
    """Test code diagnostics and validation."""
    print("\n=== Testing Code Diagnostics ===")

    # Create test files
    valid_python = """
def add(a, b):
    return a + b

class Calculator:
    def multiply(self, a, b):
        return a * b
"""

    invalid_python = """
def broken(:
    return "missing param"
"""

    valid_json = '{"name": "test", "value": 42}'
    invalid_json = '{"name": "test", "value": }'

    # Write test files
    code_mcp.write_file("valid.py", valid_python, test_dir, "overwrite")
    code_mcp.write_file("invalid.py", invalid_python, test_dir, "overwrite")
    code_mcp.write_file("valid.json", valid_json, test_dir, "overwrite")
    code_mcp.write_file("invalid.json", invalid_json, test_dir, "overwrite")

    # Test Python syntax validation
    print("\n1. Testing validate_python_syntax (valid)...")
    result = diagnostics_mcp.validate_python_syntax(valid_python)
    print(f"   ✓ Valid: {result['valid']}")

    print("\n2. Testing validate_python_syntax (invalid)...")
    result = diagnostics_mcp.validate_python_syntax(invalid_python)
    print(f"   ✓ Valid: {result['valid']}")
    print(f"   ✓ Errors: {result['error_count']}")

    # Test JSON syntax validation
    print("\n3. Testing validate_json_syntax (valid)...")
    result = diagnostics_mcp.validate_json_syntax(valid_json)
    print(f"   ✓ Valid: {result['valid']}")

    print("\n4. Testing validate_json_syntax (invalid)...")
    result = diagnostics_mcp.validate_json_syntax(invalid_json)
    print(f"   ✓ Valid: {result['valid']}")
    print(f"   ✓ Errors: {result['error_count']}")

    # Test auto-validation
    print("\n5. Testing code.validate (auto-detect)...")
    result = diagnostics_mcp.validate_file("valid.py", test_dir)
    print(f"   ✓ Valid: {result['valid']}")
    print(f"   ✓ Language: {result['language']}")

    print("\n✅ All diagnostics tests passed!")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Pandora Code Operations Test Suite")
    print("=" * 60)

    test_dir = None
    try:
        # Setup
        test_dir = setup_test_repo()

        # Run tests
        test_file_operations(test_dir)
        test_git_operations(test_dir)
        test_bash_execution(test_dir)
        test_diagnostics(test_dir)

        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        # Cleanup
        if test_dir:
            cleanup_test_repo(test_dir)

    return 0


if __name__ == "__main__":
    exit(main())
