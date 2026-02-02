import copy
import datetime
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from apps.services.orchestrator.memory_store import reset_memory_store_cache
from libs.gateway.app import (
    app as gateway_app,
    RUNTIME_POLICY,
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
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(content)
                }
            }
        ]
    }


def _coordinator_payload() -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps({"_type": "PLAN", "plan": [], "notes": {"facts": [], "open_qs": [], "decisions": [], "todos": []}})
                }
            }
        ]
    }


def test_continue_flow_injects_recent_summary(monkeypatch, tmp_path):
    RECENT_SHORT_TERM.clear()
    prev_policy = copy.deepcopy(RUNTIME_POLICY)

    call_state = {"guide": 0, "coordinator": 0, "memory_query": 0}

    async def mock_post(self, url, json=None, headers=None):
        if url == GUIDE_URL:
            call_state["guide"] += 1
            if call_state["guide"] == 1:
                return DummyResp(
                    _guide_payload(
                        {
                            "_type": "ANSWER",
                            "analysis": "Provide a quick hamster overview.",
                            "answer": "Hamsters are small, furry rodents that make popular pets.",
                            "solver_self_history": ["Provided hamster overview."],
                            "suggest_memory_save": None,
                            "tool_intent": None,
                        }
                    )
                )
            return DummyResp(
                _guide_payload(
                    {
                        "_type": "ANSWER",
                        "analysis": "Expand the recap for repository context.",
                        "answer": "Let's expand the hamster summary for the repository context.",
                        "solver_self_history": ["Expanded hamster summary for repo context."],
                        "suggest_memory_save": None,
                        "tool_intent": None,
                    }
                )
            )
        if url == COORDINATOR_URL:
            call_state["coordinator"] += 1
            return DummyResp(_coordinator_payload())
        if url == f"{ORCH_URL}/memory.query":
            call_state["memory_query"] += 1
            return DummyResp({"items": []})
        return DummyResp({"ok": True})

    async def mock_get(self, url, params=None, headers=None):
        if url.endswith("/v1/models"):
            return DummyResp({"data": [{"id": GUIDE_URL}]})
        return DummyResp({"ok": True})

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

    try:
        monkeypatch.setenv("MEMORY_ROOT", str(tmp_path))
        reset_memory_store_cache()
        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        client = TestClient(gateway_app)

        first_payload = {
            "mode": "chat",
            "messages": [
                {"role": "user", "content": "Question: tell me about hamsters"}
            ],
        }
        resp1 = client.post("/v1/chat/completions", json=first_payload)
        assert resp1.status_code == 200

        continue_payload = {
            "mode": "continue",
            "repo": "/tmp/repo",
            "messages": [
                {
                    "role": "user",
                    "content": "What were we just talking about, and please continue summarizing it for the repo context.",
                }
            ],
        }
        resp2 = client.post("/v1/chat/completions", json=continue_payload)
        assert resp2.status_code == 200
        assert call_state["guide"] == 2
        trace2 = load_trace(resp2.json())
        injected_block = "\n\n".join(trace2.get("injected_context") or [])
        assert "Recent conversation summary" in injected_block
        body = resp2.json()
        answer = body["choices"][0]["message"]["content"]
        assert "hamster" in answer.lower()

        followup_payload = {
            "mode": "continue",
            "repo": "/tmp/repo",
            "messages": [
                {
                    "role": "user",
                    "content": "What do you think is the best food for them?",
                }
            ],
        }
        resp3 = client.post("/v1/chat/completions", json=followup_payload)
        assert resp3.status_code == 200
        assert call_state["guide"] == 3
        trace3 = load_trace(resp3.json())
        injected_block_3 = "\n\n".join(trace3.get("injected_context") or [])
        assert "Recent conversation summary" in injected_block_3
        answer2 = resp3.json()["choices"][0]["message"]["content"].lower()
        assert "hamster" in answer2
    finally:
        RUNTIME_POLICY.clear()
        RUNTIME_POLICY.update(prev_policy)
        RECENT_SHORT_TERM.clear()
        reset_memory_store_cache()
