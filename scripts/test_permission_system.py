#!/usr/bin/env python3
"""
Test script for the Permission Validation System.

Tests:
1. Mode gates: write tools denied in chat mode
2. Mode gates: write tools allowed in code mode
3. Repo scope: operations in saved repo auto-allowed
4. Repo scope: operations outside saved repo need approval
5. Approval flow: approve → operation proceeds
6. Approval flow: deny → operation rejected
7. Timeout handling (mocked)
"""

import os
import sys
import asyncio
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set test environment before imports
os.environ["SAVED_REPO"] = "/home/henry/pythonprojects/stockanalysis"
os.environ["ENFORCE_MODE_GATES"] = "1"
os.environ["EXTERNAL_REPO_TIMEOUT"] = "5"  # Short timeout for testing

from libs.gateway.permission_validator import (
    PermissionValidator,
    PermissionDecision,
    ValidationResult,
    reset_validator,
    get_validator
)


def test_mode_gates_chat_denied():
    """Test that write tools are denied in chat mode."""
    print("\n=== Test: Mode Gates - Chat Mode Denied ===")
    reset_validator()
    validator = get_validator()

    write_tools = [
        ("file.write", {"file_path": "/home/henry/pythonprojects/stockanalysis/test.txt"}),
        ("file.edit", {"file_path": "/home/henry/pythonprojects/stockanalysis/test.txt"}),
        ("git.commit", {"repo": "/home/henry/pythonprojects/stockanalysis", "message": "test"}),
        ("bash.execute", {"cwd": "/home/henry/pythonprojects/stockanalysis", "command": "ls"}),
    ]

    all_passed = True
    for tool, args in write_tools:
        result = validator.validate(tool, args, mode="chat", session_id="test-session")
        if result.decision == PermissionDecision.DENIED:
            print(f"  ✓ {tool} correctly DENIED in chat mode")
        else:
            print(f"  ✗ {tool} should be DENIED in chat mode, got {result.decision}")
            all_passed = False

    return all_passed


def test_mode_gates_code_allowed():
    """Test that write tools are allowed in code mode (within saved repo)."""
    print("\n=== Test: Mode Gates - Code Mode Allowed ===")
    reset_validator()
    validator = get_validator()

    # Operations within SAVED_REPO should be allowed in code mode
    write_tools = [
        ("file.write", {"file_path": "/home/henry/pythonprojects/stockanalysis/test.txt"}),
        ("file.edit", {"file_path": "/home/henry/pythonprojects/stockanalysis/src/main.py"}),
        ("git.commit", {"repo": "/home/henry/pythonprojects/stockanalysis", "message": "test"}),
        ("bash.execute", {"cwd": "/home/henry/pythonprojects/stockanalysis", "command": "ls"}),
    ]

    all_passed = True
    for tool, args in write_tools:
        result = validator.validate(tool, args, mode="code", session_id="test-session")
        if result.decision == PermissionDecision.ALLOWED:
            print(f"  ✓ {tool} correctly ALLOWED in code mode (saved repo)")
        else:
            print(f"  ✗ {tool} should be ALLOWED in code mode, got {result.decision}: {result.reason}")
            all_passed = False

    return all_passed


def test_read_only_tools_always_allowed():
    """Test that read-only tools are always allowed regardless of mode."""
    print("\n=== Test: Read-Only Tools Always Allowed ===")
    reset_validator()
    validator = get_validator()

    read_tools = [
        ("file.read", {"file_path": "/etc/passwd"}),
        ("file.glob", {"pattern": "**/*.py"}),
        ("file.grep", {"pattern": "test", "path": "/tmp"}),
        ("git.status", {"repo": "/other/repo"}),
        ("git.diff", {"repo": "/other/repo"}),
        ("doc.search", {"query": "test"}),
        ("memory.query", {"query": "test"}),
    ]

    all_passed = True
    for tool, args in read_tools:
        for mode in ["chat", "code"]:
            result = validator.validate(tool, args, mode=mode, session_id="test-session")
            if result.decision == PermissionDecision.ALLOWED:
                print(f"  ✓ {tool} correctly ALLOWED in {mode} mode")
            else:
                print(f"  ✗ {tool} should be ALLOWED in {mode} mode, got {result.decision}")
                all_passed = False

    return all_passed


def test_repo_scope_external_needs_approval():
    """Test that operations outside saved repo need approval."""
    print("\n=== Test: Repo Scope - External Needs Approval ===")
    reset_validator()
    validator = get_validator()

    # Operations outside SAVED_REPO should need approval in code mode
    external_operations = [
        ("file.write", {"file_path": "/home/henry/pythonprojects/OTHER_PROJECT/test.txt"}),
        ("git.commit", {"repo": "/home/henry/pythonprojects/OTHER_PROJECT", "message": "test"}),
        ("bash.execute", {"cwd": "/tmp", "command": "ls"}),
    ]

    all_passed = True
    for tool, args in external_operations:
        result = validator.validate(tool, args, mode="code", session_id="test-session")
        if result.decision == PermissionDecision.NEEDS_APPROVAL:
            print(f"  ✓ {tool} correctly NEEDS_APPROVAL for external path")
            print(f"    - Request ID: {result.approval_request_id}")
            print(f"    - Reason: {result.reason}")
        else:
            print(f"  ✗ {tool} should NEED_APPROVAL for external path, got {result.decision}")
            all_passed = False

    return all_passed


def test_approval_flow_approve():
    """Test that approving a request allows the operation."""
    print("\n=== Test: Approval Flow - Approve ===")
    reset_validator()
    validator = get_validator()

    # Create a pending request
    result = validator.validate(
        "file.write",
        {"file_path": "/tmp/test.txt"},
        mode="code",
        session_id="test-session"
    )

    if result.decision != PermissionDecision.NEEDS_APPROVAL:
        print(f"  ✗ Expected NEEDS_APPROVAL, got {result.decision}")
        return False

    request_id = result.approval_request_id
    print(f"  Created request: {request_id}")

    # Approve the request
    success = validator.resolve_request(request_id, approved=True, reason="test_approved")
    if success:
        print("  ✓ Request approved successfully")
    else:
        print("  ✗ Failed to approve request")
        return False

    # Verify the request is resolved
    pending = validator.get_pending_requests()
    if not any(r["request_id"] == request_id for r in pending):
        print("  ✓ Request no longer pending after approval")
    else:
        print("  ✗ Request still pending after approval")
        return False

    return True


def test_approval_flow_deny():
    """Test that denying a request rejects the operation."""
    print("\n=== Test: Approval Flow - Deny ===")
    reset_validator()
    validator = get_validator()

    # Create a pending request
    result = validator.validate(
        "file.write",
        {"file_path": "/tmp/test.txt"},
        mode="code",
        session_id="test-session"
    )

    if result.decision != PermissionDecision.NEEDS_APPROVAL:
        print(f"  ✗ Expected NEEDS_APPROVAL, got {result.decision}")
        return False

    request_id = result.approval_request_id
    print(f"  Created request: {request_id}")

    # Deny the request
    success = validator.resolve_request(request_id, approved=False, reason="test_denied")
    if success:
        print("  ✓ Request denied successfully")
    else:
        print("  ✗ Failed to deny request")
        return False

    return True


async def test_approval_wait_timeout():
    """Test that waiting for approval times out correctly."""
    print("\n=== Test: Approval Wait Timeout ===")
    reset_validator()
    validator = get_validator()
    validator.approval_timeout = 0.5  # Very short timeout for testing

    # Create a pending request
    result = validator.validate(
        "file.write",
        {"file_path": "/tmp/test.txt"},
        mode="code",
        session_id="test-session"
    )

    if result.decision != PermissionDecision.NEEDS_APPROVAL:
        print(f"  ✗ Expected NEEDS_APPROVAL, got {result.decision}")
        return False

    request_id = result.approval_request_id
    print(f"  Created request: {request_id}")
    print("  Waiting for timeout (0.5s)...")

    # Wait for approval (should timeout)
    approved = await validator.wait_for_approval(request_id)

    if not approved:
        print("  ✓ Request correctly timed out (not approved)")
    else:
        print("  ✗ Request should have timed out")
        return False

    return True


def test_enforcement_disabled():
    """Test that ENFORCE_MODE_GATES=0 disables all checks."""
    print("\n=== Test: Enforcement Disabled ===")
    reset_validator()

    # Temporarily disable enforcement
    os.environ["ENFORCE_MODE_GATES"] = "0"
    reset_validator()  # Recreate validator with new setting
    validator = get_validator()

    result = validator.validate(
        "file.write",
        {"file_path": "/tmp/dangerous.txt"},
        mode="chat",  # Chat mode with write tool should normally be denied
        session_id="test-session"
    )

    # Restore enforcement
    os.environ["ENFORCE_MODE_GATES"] = "1"

    if result.decision == PermissionDecision.ALLOWED:
        print("  ✓ All operations ALLOWED when enforcement disabled")
        return True
    else:
        print(f"  ✗ Expected ALLOWED with enforcement disabled, got {result.decision}")
        return False


def test_no_saved_repo():
    """Test that missing SAVED_REPO allows all paths."""
    print("\n=== Test: No SAVED_REPO Configured ===")
    reset_validator()

    # Remove SAVED_REPO
    original = os.environ.pop("SAVED_REPO", None)
    reset_validator()
    validator = get_validator()

    result = validator.validate(
        "file.write",
        {"file_path": "/any/random/path/test.txt"},
        mode="code",
        session_id="test-session"
    )

    # Restore SAVED_REPO
    if original:
        os.environ["SAVED_REPO"] = original
    reset_validator()

    if result.decision == PermissionDecision.ALLOWED:
        print("  ✓ All paths ALLOWED when SAVED_REPO not configured")
        return True
    else:
        print(f"  ✗ Expected ALLOWED without SAVED_REPO, got {result.decision}")
        return False


def test_get_pending_requests():
    """Test listing pending requests."""
    print("\n=== Test: Get Pending Requests ===")
    reset_validator()
    validator = get_validator()
    # Clear any leftover pending from previous tests
    validator._pending.clear()
    validator._persist_pending()

    # Create multiple pending requests
    sessions = ["session-1", "session-2", "session-1"]
    for i, session in enumerate(sessions):
        validator.validate(
            "file.write",
            {"file_path": f"/tmp/test{i}.txt"},
            mode="code",
            session_id=session
        )

    all_pending = validator.get_pending_requests()
    session1_pending = validator.get_pending_requests(session_id="session-1")

    print(f"  Total pending: {len(all_pending)}")
    print(f"  Session-1 pending: {len(session1_pending)}")

    if len(all_pending) == 3:
        print("  ✓ All 3 requests tracked")
    else:
        print(f"  ✗ Expected 3 pending, got {len(all_pending)}")
        return False

    if len(session1_pending) == 2:
        print("  ✓ Session filtering works (2 for session-1)")
    else:
        print(f"  ✗ Expected 2 for session-1, got {len(session1_pending)}")
        return False

    return True


def test_cancel_request():
    """Test canceling a pending request."""
    print("\n=== Test: Cancel Request ===")
    reset_validator()
    validator = get_validator()

    # Create a pending request
    result = validator.validate(
        "file.write",
        {"file_path": "/tmp/test.txt"},
        mode="code",
        session_id="test-session"
    )

    request_id = result.approval_request_id

    # Cancel it
    success = validator.cancel_request(request_id)
    if success:
        print("  ✓ Request canceled successfully")
    else:
        print("  ✗ Failed to cancel request")
        return False

    # Verify it's gone
    pending = validator.get_pending_requests()
    if not any(r["request_id"] == request_id for r in pending):
        print("  ✓ Canceled request removed from pending")
    else:
        print("  ✗ Canceled request still in pending")
        return False

    return True


async def run_all_tests():
    """Run all permission system tests."""
    print("=" * 60)
    print("Permission System Test Suite")
    print("=" * 60)
    print(f"SAVED_REPO: {os.environ.get('SAVED_REPO')}")
    print(f"ENFORCE_MODE_GATES: {os.environ.get('ENFORCE_MODE_GATES')}")
    print("=" * 60)

    tests = [
        ("Mode Gates - Chat Denied", test_mode_gates_chat_denied),
        ("Mode Gates - Code Allowed", test_mode_gates_code_allowed),
        ("Read-Only Tools Always Allowed", test_read_only_tools_always_allowed),
        ("Repo Scope - External Needs Approval", test_repo_scope_external_needs_approval),
        ("Approval Flow - Approve", test_approval_flow_approve),
        ("Approval Flow - Deny", test_approval_flow_deny),
        ("Approval Wait Timeout", test_approval_wait_timeout),
        ("Enforcement Disabled", test_enforcement_disabled),
        ("No SAVED_REPO Configured", test_no_saved_repo),
        ("Get Pending Requests", test_get_pending_requests),
        ("Cancel Request", test_cancel_request),
    ]

    results = []
    for name, test_func in tests:
        try:
            if asyncio.iscoroutinefunction(test_func):
                result = await test_func()
            else:
                result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n  ✗ Exception in {name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    print("\n" + "=" * 60)
    print("Test Results Summary")
    print("=" * 60)
    passed = sum(1 for _, r in results if r)
    total = len(results)
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")

    print("=" * 60)
    print(f"Total: {passed}/{total} tests passed")
    print("=" * 60)

    return passed == total


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
