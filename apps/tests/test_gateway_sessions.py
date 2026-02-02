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
    # Emulate an orchestrator success response for write tools
    return DummyResp({"ok": True, "applied": True}, status_code=200)

def test_tool_execute_denies_write_without_session():
    client = TestClient(gateway_app)
    payload = {
        "tool": "file.create",
        "args": {
            "repo": str(pathlib.Path.cwd()),
            "path": "tmp.txt",
            "content": "hello"
        }
    }
    resp = client.post("/tool/execute", json=payload)
    assert resp.status_code == 403

def test_tool_execute_allows_with_valid_session(monkeypatch):
    # Create a session directly via the session store (bypass /ui/session/start restrictions)
    s = session_store.create_session(repo=str(pathlib.Path.cwd()), allowed_tools=["code.apply_patch"], ttl_minutes=15, created_by="test_user")
    token = s.get("token")
    assert token, "session_store.create_session should return a session with a token"

    # Patch httpx.AsyncClient.post to avoid real network calls to the Orchestrator
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    client = TestClient(gateway_app)
    payload = {
        "tool": "code.apply_patch",
        "args": {
            "repo": str(pathlib.Path.cwd()),
            "patch": "--- a/foo\n+++ b/foo\n@@ -1 +1 @@\n-1\n+2\n",
            "dry_run": True
        },
        "mode": "continue"
    }
    headers = {"X-Session-Token": token}
    resp = client.post("/tool/execute", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json().get("ok") is True
