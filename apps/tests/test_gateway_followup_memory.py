import datetime
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from apps.services.orchestrator.memory_store import reset_memory_store_cache
from libs.gateway.app import (
    app as gateway_app,
    GUIDE_URL,
    COORDINATOR_URL,
    ORCH_URL,
    RECENT_SHORT_TERM,
    TRANSCRIPTS_DIR,
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


def _guide_payload(content: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(content)}}]}


def _coordinator_payload() -> dict:
    return {"choices": [{"message": {"content": json.dumps({"_type": "PLAN", "plan": [], "notes": {}})}}]}


def test_followup_question_injects_recent_summary(monkeypatch, tmp_path):
    RECENT_SHORT_TERM.clear()
    monkeypatch.setenv("MEMORY_ROOT", str(tmp_path))
    reset_memory_store_cache()
    def load_trace(resp_json: dict) -> dict:
        created = resp_json.get("created")
        trace_id = resp_json.get("trace_id")
        assert trace_id
        day = datetime.datetime.utcfromtimestamp(created).strftime("%Y%m%d")
        path = Path(TRANSCRIPTS_DIR) / f"{day}.jsonl"
        assert path.exists(), f"transcript file not found: {path}"
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                data = json.loads(line)
                if data.get("id") == trace_id:
                    return data
        raise AssertionError(f"trace {trace_id} not found in {path}")

    async def mock_post(self, url, json=None, headers=None):
        if url == GUIDE_URL:
            return DummyResp(
                _guide_payload(
                    {
                        "_type": "ANSWER",
                        "analysis": "Reference earlier summary and expand.",
                        "answer": "Let me build on the previous summary about hamsters.",
                        "solver_self_history": ["Expanded hamster recap."],
                        "suggest_memory_save": None,
                        "tool_intent": None,
                    }
                )
            )
        if url == COORDINATOR_URL:
            return DummyResp(_coordinator_payload())
        if url == f"{ORCH_URL}/memory.query":
            return DummyResp({"items": []})
        return DummyResp({"ok": True})

    async def mock_get(self, url, params=None, headers=None):
        if url.endswith("/v1/models"):
            return DummyResp({"data": [{"id": GUIDE_URL}]})
        return DummyResp({"ok": True})

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    client = TestClient(gateway_app)

    first_payload = {
        "mode": "chat",
        "messages": [{"role": "user", "content": "Question: tell me about hamsters"}],
    }
    resp1 = client.post("/v1/chat/completions", json=first_payload)
    assert resp1.status_code == 200

    followup_payload = {
        "mode": "chat",
        "messages": [{"role": "user", "content": "Tell me more about this."}],
    }
    resp2 = client.post("/v1/chat/completions", json=followup_payload)
    assert resp2.status_code == 200
    trace2 = load_trace(resp2.json())
    injected_block = "\n\n".join(trace2.get("injected_context") or [])
    assert "Recent conversation summary" in injected_block, "Follow-up questions should receive the recent conversation summary"

    # Second follow-up using pronoun "them"
    resp3 = client.post(
        "/v1/chat/completions",
        json={
            "mode": "chat",
            "messages": [
                {
                    "role": "user",
                    "content": "What do you think is the best food for them?",
                }
            ],
        },
    )
    assert resp3.status_code == 200
    trace3 = load_trace(resp3.json())
    injected_block_3 = "\n\n".join(trace3.get("injected_context") or [])
    assert "Recent conversation summary" in injected_block_3
    reset_memory_store_cache()
