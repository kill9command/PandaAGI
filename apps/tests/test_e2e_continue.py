import pathlib
import httpx
from fastapi.testclient import TestClient
import libs.gateway.session_store as session_store
from libs.gateway.app import app as gateway_app

class DummyResp:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("HTTP error", request=None, response=None)

    def json(self):
        return self._data

async def mock_post(self, url, json=None, headers=None):
    # Return different responses depending on which orchestrator tool is being called.
    if url.endswith("/code.apply_patch"):
        if json and json.get("dry_run"):
            return DummyResp({"ok": True, "dry_run": True, "preview": {"diff": "@@ -1 +1 @@\\n-1\\n+2\\n"}})
        return DummyResp({"ok": True, "applied": True})
    if url.endswith("/git.commit"):
        return DummyResp({"commit_id": "deadbeef", "shortlog": "E2E commit"})
    if url.endswith("/tasks.run"):
        return DummyResp({"rc": 0, "stdout": "tests ok", "stderr": ""})
    # Fallback generic success
    return DummyResp({"ok": True})

def test_e2e_continue_flow(monkeypatch):
    # Patch httpx AsyncClient.post to avoid network calls to the Orchestrator.
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    client = TestClient(gateway_app)
    repo = str(pathlib.Path.cwd())

    # Create a session directly in the store (bypass /ui/session/start restrictions)
    s = session_store.create_session(repo=repo, allowed_tools=["code.apply_patch", "git.commit", "tasks.run"], ttl_minutes=15, created_by="e2e_test")
    token = s.get("token")
    assert token, "session token should be created"

    # 1) Dry-run apply_patch
    payload = {
        "tool": "code.apply_patch",
        "args": {
            "repo": repo,
            "patch": "--- a/foo\n+++ b/foo\n@@ -1 +1 @@\n-1\n+2\n",
            "dry_run": True
        },
        "mode": "continue"
    }
    resp = client.post("/tool/execute", json=payload, headers={"X-Session-Token": token})
    assert resp.status_code == 200
    j = resp.json()
    assert j.get("dry_run") or j.get("preview") is not None

    # 2) Apply the patch (dry_run = False)
    payload["args"]["dry_run"] = False
    resp = client.post("/tool/execute", json=payload, headers={"X-Session-Token": token})
    assert resp.status_code == 200
    j = resp.json()
    assert j.get("applied") is True

    # 3) Commit the change
    commit_payload = {
        "tool": "git.commit",
        "args": {
            "repo": repo,
            "add_paths": ["foo"],
            "message": "E2E: apply patch"
        }
    }
    resp = client.post("/tool/execute", json=commit_payload, headers={"X-Session-Token": token})
    assert resp.status_code == 200
    j = resp.json()
    assert "commit_id" in j

    # 4) Run tasks.run (pytest) - tasks.run is not a write tool so session token not required
    task_payload = {
        "tool": "tasks.run",
        "args": {
            "repo": repo,
            "kind": "pytest",
            "cmd": ["pytest", "-q"],
            "timeout_s": 30
        }
    }
    resp = client.post("/tool/execute", json=task_payload)
    assert resp.status_code == 200
    j = resp.json()
    assert j.get("rc") == 0
