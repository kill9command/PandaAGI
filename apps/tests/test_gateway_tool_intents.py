import copy
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from libs.gateway.app import (
    app as gateway_app,
    RUNTIME_POLICY,
    SOLVER_URL,
    COORDINATOR_URL,
    ORCH_URL,
    REPOS_BASE,
)


class DummyResp:
    def __init__(self, data, status_code: int = 200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("HTTP error", request=None, response=None)

    def json(self):
        return self._data


def _solver_payload(obj: dict) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(obj)
                }
            }
        ]
    }


async def _mock_get_models(self, url, params=None, headers=None):
    if url.endswith("/v1/models"):
        return DummyResp({"data": [{"id": SOLVER_URL}]})
    return DummyResp({"ok": True})


def test_chat_tool_intent_deferred_requires_confirm(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    prev_policy = copy.deepcopy(RUNTIME_POLICY)

    RUNTIME_POLICY["chat_allow_file_create"] = True
    RUNTIME_POLICY["write_confirm"] = True

    call_state = {"solver": 0, "file_create": 0, "memory": 0}

    async def mock_post(self, url, json=None, headers=None):
        if url == SOLVER_URL:
            if call_state["solver"] == 0:
                call_state["solver"] += 1
                return DummyResp(_solver_payload(
                    {
                        "_type": "ANSWER",
                        "analysis": "Proposing file creation.",
                        "answer": "Pending your confirmation to create hello.md.",
                        "tool_intent": {"action": "create_file", "path": "hello.md", "content": "Hello from test"},
                        "solver_self_history": ["Proposed creating hello.md"],
                        "suggest_memory_save": None,
                    }
                ))
            call_state["solver"] += 1
            return DummyResp(_solver_payload(
                {
                    "_type": "ANSWER",
                    "analysis": "Awaiting confirmation.",
                    "answer": "Pending your confirmation to create hello.md.",
                    "solver_self_history": ["Awaiting user confirmation."],
                    "suggest_memory_save": None,
                }
            ))
        if url == f"{ORCH_URL}/memory.query":
            call_state["memory"] += 1
            return DummyResp({"items": []})
        if url == f"{ORCH_URL}/file.create":
            call_state["file_create"] += 1
            return DummyResp({"ok": True})
        raise AssertionError(f"Unexpected POST {url}")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get_models)

    client = TestClient(gateway_app)
    payload = {
        "mode": "chat",
        "messages": [{"role": "user", "content": "Please create hello.md"}],
        "repo": str(repo),
    }

    try:
        resp = client.post("/v1/chat/completions", json=payload)
    finally:
        RUNTIME_POLICY.clear()
        RUNTIME_POLICY.update(prev_policy)

    body = resp.json()
    assert resp.status_code == 200, f"Unexpected status {resp.status_code}: {body}"
    assert body.get("requires_confirm"), "Chat response should include deferred actions"
    pending = body["requires_confirm"][0]
    assert pending["tool"] == "file.create"
    assert pending["args"]["path"] == "hello.md"
    assert call_state["file_create"] == 0, "file.create should not execute before confirmation"
    assert call_state["solver"] == 1


def test_chat_tool_intent_handles_create_action(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    prev_policy = copy.deepcopy(RUNTIME_POLICY)

    RUNTIME_POLICY["chat_allow_file_create"] = True
    RUNTIME_POLICY["write_confirm"] = True

    call_state = {"solver": 0, "file_create": 0, "memory": 0}

    async def mock_post(self, url, json=None, headers=None):
        if url == SOLVER_URL:
            if call_state["solver"] == 0:
                call_state["solver"] += 1
                return DummyResp(_solver_payload(
                    {
                        "_type": "ANSWER",
                        "analysis": "Proposing file creation.",
                        "answer": "hello.txt pending confirmation.",
                        "tool_intent": {"action": "create", "file": "hello.txt", "content": "Hello, world!"},
                        "solver_self_history": ["Suggested creating hello.txt"],
                        "suggest_memory_save": None,
                    }
                ))
            call_state["solver"] += 1
            return DummyResp(_solver_payload(
                {
                    "_type": "ANSWER",
                    "analysis": "Still waiting for confirmation.",
                    "answer": "hello.txt pending confirmation.",
                    "solver_self_history": ["Awaiting user confirmation."],
                    "suggest_memory_save": None,
                }
            ))
        if url == f"{ORCH_URL}/memory.query":
            call_state["memory"] += 1
            return DummyResp({"items": []})
        if url == f"{ORCH_URL}/file.create":
            call_state["file_create"] += 1
            return DummyResp({"ok": True})
        raise AssertionError(f"Unexpected POST {url}")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get_models)

    client = TestClient(gateway_app)
    payload = {
        "mode": "chat",
        "messages": [{"role": "user", "content": "Please create hello.txt"}],
        "repo": str(repo),
    }

    try:
        resp = client.post("/v1/chat/completions", json=payload)
    finally:
        RUNTIME_POLICY.clear()
        RUNTIME_POLICY.update(prev_policy)

    body = resp.json()
    assert resp.status_code == 200, f"Unexpected status {resp.status_code}: {body}"
    assert body.get("requires_confirm"), "Chat response should include deferred actions"
    pending = body["requires_confirm"][0]
    assert pending["tool"] == "file.create"
    assert pending["args"]["path"] == "hello.txt"
    assert call_state["file_create"] == 0
    assert call_state["solver"] == 1


def test_chat_tool_intent_uses_single_allowed_root(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    prev_policy = copy.deepcopy(RUNTIME_POLICY)
    RUNTIME_POLICY["chat_allow_file_create"] = True
    RUNTIME_POLICY["write_confirm"] = False
    RUNTIME_POLICY["chat_allowed_write_paths"] = [str(repo)]

    call_state = {"solver": 0, "file_create": 0, "memory": 0, "repo_used": None}

    async def mock_post(self, url, json=None, headers=None):
        if url == SOLVER_URL:
            if call_state["solver"] == 0:
                call_state["solver"] += 1
                return DummyResp(_solver_payload(
                    {
                        "_type": "ANSWER",
                        "analysis": "Proposing file creation.",
                        "answer": "Ready to create hello.md.",
                        "tool_intent": {"action": "create_file", "path": "hello.md", "content": "Hello!"},
                        "solver_self_history": ["Proposed creating hello.md"],
                        "suggest_memory_save": None,
                    }
                ))
            call_state["solver"] += 1
            return DummyResp(_solver_payload(
                {
                    "_type": "ANSWER",
                    "analysis": "Creation acknowledged.",
                    "answer": "hello.md created.",
                    "solver_self_history": ["Confirmed hello.md creation."],
                    "suggest_memory_save": None,
                }
            ))
        if url == f"{ORCH_URL}/memory.query":
            call_state["memory"] += 1
            return DummyResp({"items": []})
        if url == f"{ORCH_URL}/file.create":
            call_state["file_create"] += 1
            call_state["repo_used"] = json.get("repo") if json else None
            return DummyResp({"ok": True})
        raise AssertionError(f"Unexpected POST {url}")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get_models)

    client = TestClient(gateway_app)
    payload = {
        "mode": "chat",
        "messages": [{"role": "user", "content": "create hello.md"}],
        "repo": str(repo),
    }

    try:
        resp = client.post("/v1/chat/completions", json=payload)
    finally:
        RUNTIME_POLICY.clear()
        RUNTIME_POLICY.update(prev_policy)

    assert resp.status_code == 200
    assert resp.json().get("requires_confirm") == []
    assert call_state["file_create"] == 1
    assert call_state["repo_used"] == str(repo)
    assert call_state["solver"] == 1


def test_chat_tool_intent_defaults_to_repos_base(monkeypatch):
    prev_policy = copy.deepcopy(RUNTIME_POLICY)
    RUNTIME_POLICY["chat_allow_file_create"] = True
    RUNTIME_POLICY["write_confirm"] = False
    RUNTIME_POLICY["chat_allowed_write_paths"] = []

    call_state = {"solver": 0, "file_create": 0, "memory": 0, "repo_used": None}

    async def mock_post(self, url, json=None, headers=None):
        if url == SOLVER_URL:
            if call_state["solver"] == 0:
                call_state["solver"] += 1
                return DummyResp(_solver_payload(
                    {
                        "_type": "ANSWER",
                        "analysis": "Proposing file creation.",
                        "answer": "Ready to create hello.md.",
                        "tool_intent": {"action": "create_file", "path": "hello.md", "content": "Hello!"},
                        "solver_self_history": ["Proposed creating hello.md"],
                        "suggest_memory_save": None,
                    }
                ))
            call_state["solver"] += 1
            return DummyResp(_solver_payload(
                {
                    "_type": "ANSWER",
                    "analysis": "Creation acknowledged.",
                    "answer": "hello.md created.",
                    "solver_self_history": ["Confirmed hello.md creation."],
                    "suggest_memory_save": None,
                }
            ))
        if url == f"{ORCH_URL}/memory.query":
            call_state["memory"] += 1
            return DummyResp({"items": []})
        if url == f"{ORCH_URL}/file.create":
            call_state["file_create"] += 1
            call_state["repo_used"] = json.get("repo") if json else None
            return DummyResp({"ok": True})
        raise AssertionError(f"Unexpected POST {url}")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get_models)

    client = TestClient(gateway_app)
    payload = {
        "mode": "chat",
        "messages": [{"role": "user", "content": "create hello.md"}],
        "repo": str(REPOS_BASE),
    }

    try:
        resp = client.post("/v1/chat/completions", json=payload)
    finally:
        RUNTIME_POLICY.clear()
        RUNTIME_POLICY.update(prev_policy)

    assert resp.status_code == 200
    assert resp.json().get("requires_confirm") == []
    assert call_state["file_create"] == 1
    assert call_state["repo_used"] == str(REPOS_BASE)
    assert call_state["solver"] == 1


def test_tool_execute_confirm_without_session(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    prev_policy = copy.deepcopy(RUNTIME_POLICY)
    RUNTIME_POLICY["chat_allow_file_create"] = True
    RUNTIME_POLICY["write_confirm"] = True
    RUNTIME_POLICY["chat_allowed_write_paths"] = [str(repo)]

    captured = {}

    async def mock_post(self, url, json=None, headers=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers or {}
        return DummyResp({"ok": True, "path": str(Path(json.get("repo", repo)) / json.get("path", ""))})

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get_models)

    client = TestClient(gateway_app)
    payload = {
        "tool": "file.create",
        "args": {
            "path": "hello.md",
            "content": "hi",
            "repo": str(repo)
        },
        "mode": "chat",
        "repo": str(repo),
        "confirmed": True
    }

    try:
        resp = client.post("/tool/execute", json=payload)
    finally:
        RUNTIME_POLICY.clear()
        RUNTIME_POLICY.update(prev_policy)

    assert resp.status_code == 200
    assert captured.get("url") == f"{ORCH_URL}/file.create"


def test_tool_execute_requires_session_when_not_confirmed(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    prev_policy = copy.deepcopy(RUNTIME_POLICY)
    RUNTIME_POLICY["chat_allow_file_create"] = True
    RUNTIME_POLICY["write_confirm"] = True
    RUNTIME_POLICY["chat_allowed_write_paths"] = [str(repo)]

    async def mock_post(self, url, json=None, headers=None):
        return DummyResp({"ok": True})

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get_models)

    client = TestClient(gateway_app)
    payload = {
        "tool": "file.create",
        "args": {
            "path": "hello.md",
            "content": "hi",
            "repo": str(repo)
        },
        "mode": "chat",
        "repo": str(repo)
    }

    try:
        resp = client.post("/tool/execute", json=payload)
    finally:
        RUNTIME_POLICY.clear()
        RUNTIME_POLICY.update(prev_policy)

    assert resp.status_code == 200


def test_continue_tool_intent_executes_immediately(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    prev_policy = copy.deepcopy(RUNTIME_POLICY)
    RUNTIME_POLICY["chat_allow_file_create"] = True
    RUNTIME_POLICY["write_confirm"] = True

    call_state = {"solver": 0, "file_create": 0, "memory": 0}

    async def mock_post(self, url, json=None, headers=None):
        if url == SOLVER_URL:
            if call_state["solver"] == 0:
                call_state["solver"] += 1
                return DummyResp(_solver_payload(
                    {
                        "_type": "ANSWER",
                        "analysis": "Proposing notes.txt creation.",
                        "answer": "Creating notes.txt now.",
                        "tool_intent": {"action": "create_file", "path": "notes.txt", "content": "Hello from continue mode"},
                        "solver_self_history": ["Created notes.txt in continue mode."],
                        "suggest_memory_save": None,
                    }
                ))
            call_state["solver"] += 1
            return DummyResp(_solver_payload(
                {
                    "_type": "ANSWER",
                    "analysis": "Confirmed creation.",
                    "answer": "Created notes.txt.",
                    "solver_self_history": ["Confirmed notes.txt creation."],
                    "suggest_memory_save": None,
                }
            ))
        if url == f"{ORCH_URL}/memory.query":
            call_state["memory"] += 1
            return DummyResp({"items": []})
        if url == f"{ORCH_URL}/file.create":
            call_state["file_create"] += 1
            path = Path(json["repo"]) / json["path"] if json else repo / "notes.txt"
            return DummyResp({"ok": True, "path": str(path)})
        raise AssertionError(f"Unexpected POST {url}")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get_models)

    client = TestClient(gateway_app)
    payload = {
        "mode": "continue",
        "messages": [{"role": "user", "content": "Create notes.txt"}],
        "repo": str(repo),
    }

    try:
        resp = client.post("/v1/chat/completions", json=payload)
    finally:
        RUNTIME_POLICY.clear()
        RUNTIME_POLICY.update(prev_policy)

    body = resp.json()
    assert resp.status_code == 200, f"Unexpected status {resp.status_code}: {body}"
    assert body.get("requires_confirm") == [], "Continue mode should execute immediately"
    assert call_state["file_create"] == 1
    assert call_state["solver"] == 1


def test_chat_tool_intent_ticket_cycle_defers_writes(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    prev_policy = copy.deepcopy(RUNTIME_POLICY)
    RUNTIME_POLICY["chat_allow_file_create"] = True
    RUNTIME_POLICY["write_confirm"] = True

    call_state = {"guide": 0, "coordinator": 0, "file_create": 0, "memory": 0}

    async def mock_post(self, url, json=None, headers=None):
        if url == f"{ORCH_URL}/memory.query":
            call_state["memory"] += 1
            return DummyResp({"items": []})

        if url.startswith(f"{ORCH_URL}/"):
            if url.endswith("/file.create"):
                call_state["file_create"] += 1
            return DummyResp({"ok": True})

        if url == SOLVER_URL:
            messages = (json or {}).get("messages") or []
            last_content = messages[-1]["content"] if messages else ""
            is_task_ticket = last_content.startswith("Task Ticket:")

            if is_task_ticket:
                call_state["coordinator"] += 1
                plan = {
                    "_type": "PLAN",
                    "plan": [
                        {
                            "tool": "doc.search",
                            "args": {"query": "notes.md outline"},
                        }
                    ],
                    "notes": {"policy": [], "coordinator": []},
                }
                return DummyResp(_solver_payload(plan))

            if call_state["guide"] == 0:
                call_state["guide"] += 1
                ticket = {
                    "_type": "TICKET",
                    "ticket_id": "ticket-abc",
                    "user_turn_id": "turn-123",
                    "goal": "Draft notes.md and gather context",
                    "micro_plan": ["create notes.md with outline"],
                    "analysis": "Need to create notes.md but confirm before writing.",
                    "needs_more_context": False,
                }
                return DummyResp(_solver_payload(ticket))

            call_state["guide"] += 1
            answer = {
                "_type": "ANSWER",
                "analysis": "notes.md queued for confirmation.",
                "answer": "notes.md is ready to create once you approve.",
                "tool_intent": {
                    "action": "create_file",
                    "path": "notes.md",
                    "content": "## Meeting notes\n- Agenda\n- Decisions\n",
                },
                "solver_self_history": ["Proposed creating notes.md on confirmation."],
            }
            return DummyResp(_solver_payload(answer))

        raise AssertionError(f"Unexpected POST {url}")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get_models)

    client = TestClient(gateway_app)
    payload = {
        "mode": "chat",
        "messages": [{"role": "user", "content": "Start a notes.md file for me."}],
        "repo": str(repo),
    }

    try:
        resp = client.post("/v1/chat/completions", json=payload)
    finally:
        RUNTIME_POLICY.clear()
        RUNTIME_POLICY.update(prev_policy)

    body = resp.json()
    assert resp.status_code == 200, f"Unexpected status {resp.status_code}: {body}"
    pending = body.get("requires_confirm")
    assert pending, "Deferred actions should be surfaced after ticket cycle"
    assert pending[0]["tool"] == "file.create"
    assert pending[0]["args"]["path"] == "notes.md"
    assert call_state["file_create"] == 0, "file.create should remain deferred until approval"
    assert call_state["guide"] == 2, "Guide should run once for ticket and once for the final answer"
    assert call_state["coordinator"] == 1, "Coordinator should run exactly once for the ticket"


def test_chat_pricing_lookup_flow(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    call_state = {"solver": 0, "coordinator": 0, "memory": 0, "purchasing": 0}

    async def mock_post(self, url, json=None, headers=None):
        messages = (json or {}).get("messages") or []
        last_content = messages[-1]["content"] if messages else ""
        is_task_ticket = last_content.startswith("Task Ticket:")
        if url == SOLVER_URL and not is_task_ticket:
            if call_state["solver"] == 0:
                call_state["solver"] += 1
                return DummyResp(
                    _solver_payload(
                        {
                            "_type": "TICKET",
                            "analysis": "Need live pricing.",
                            "ticket_id": "pending",
                            "user_turn_id": "pending",
                            "goal": "Find Syrian hamster offers",
                            "micro_plan": ["Search reputable sellers", "Record price + availability"],
                            "subtasks": [
                                {"kind": "search", "q": "Syrian hamster for sale", "why": "find listings"}
                            ],
                            "constraints": {"latency_ms": 4000, "budget_tokens": 2000, "privacy": "allow_external"},
                            "verification": {"required": ["prices", "dates"]},
                            "return": {"format": "raw_bundle"},
                        }
                    )
                )
            call_state["solver"] += 1
            return DummyResp(
                _solver_payload(
                    {
                        "_type": "ANSWER",
                        "analysis": "Used latest purchase claims.",
                        "answer": "HamsterHub has Syrian hamsters for $12.99 and ships immediately.",
                        "solver_self_history": ["Reported pricing"],
                        "suggest_memory_save": None,
                    }
                )
            )
        if url == COORDINATOR_URL and is_task_ticket:
            call_state["coordinator"] += 1
            return DummyResp(
                _solver_payload(
                    {
                        "_type": "PLAN",
                        "plan": [],
                        "notes": {"warnings": [], "assumptions": []},
                    }
                )
            )
        if url == f"{ORCH_URL}/memory.query":
            call_state["memory"] += 1
            return DummyResp({"items": []})
        if url == f"{ORCH_URL}/purchasing.lookup":
            call_state["purchasing"] += 1
            return DummyResp(
                {
                    "offers": [
                        {
                            "title": "HamsterHub Syrian hamster",
                            "price": 12.99,
                            "currency": "USD",
                            "price_text": "$12.99",
                            "availability": "In stock",
                            "source": "HamsterHub",
                        }
                    ]
                }
            )
        raise AssertionError(f"Unexpected POST {url}")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get_models)

    client = TestClient(gateway_app)
    payload = {
        "mode": "chat",
        "messages": [
            {"role": "user", "content": "my favorite hamster is the syrian hamster"},
            {"role": "assistant", "content": "Noted."},
            {"role": "user", "content": "can you find one for sale for me?"},
        ],
        "repo": str(repo),
    }

    resp = client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert "HamsterHub" in body["choices"][0]["message"]["content"]
    assert call_state["coordinator"] == 1
    assert call_state["purchasing"] == 1
