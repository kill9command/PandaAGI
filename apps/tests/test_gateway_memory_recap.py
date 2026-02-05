import copy
import json

import httpx
from fastapi.testclient import TestClient

from apps.services.tool_server.memory_store import reset_memory_store_cache
from libs.gateway.app import (
    app as gateway_app,
    RUNTIME_POLICY,
    GUIDE_URL,
    TOOL_SERVER_URL,
    RECENT_SHORT_TERM,
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


async def _mock_get_models(self, url, params=None, headers=None):
    if url.endswith("/v1/models"):
        return DummyResp({"data": [{"id": GUIDE_URL}]})
    return DummyResp({"ok": True})


def test_meta_recap_uses_injected_summary_and_guide(monkeypatch, tmp_path):
    RECENT_SHORT_TERM.clear()
    prev_policy = copy.deepcopy(RUNTIME_POLICY)

    call_state = {"guide": 0, "memory_query": 0}

    async def mock_post(self, url, json=None, headers=None):
        if url == GUIDE_URL:
            call_state["guide"] += 1
            if call_state["guide"] == 1:
                return DummyResp(_guide_payload(
                    {
                        "_type": "ANSWER",
                        "analysis": "Provide a brief overview of hamsters.",
                        "answer": "Hamsters are small, furry rodents that are popular as pets.",
                        "solver_self_history": ["Shared a quick hamster overview."],
                        "suggest_memory_save": None,
                        "tool_intent": None,
                    }
                ))
            return DummyResp(_guide_payload(
                {
                    "_type": "ANSWER",
                    "analysis": "Summarize prior conversation and elaborate.",
                    "answer": "We were just talking about hamsters. Here is more detail on their habitat and diet.",
                    "solver_self_history": ["Expanded on hamster habitat and diet."],
                    "suggest_memory_save": None,
                    "tool_intent": None,
                }
            ))
        if url == f"{TOOL_SERVER_URL}/memory.query":
            call_state["memory_query"] += 1
            return DummyResp({"items": []})
        return DummyResp({"ok": True})

    try:
        monkeypatch.setenv("MEMORY_ROOT", str(tmp_path))
        reset_memory_store_cache()
        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get_models)

        client = TestClient(gateway_app)

        first_payload = {
            "mode": "chat",
            "messages": [
                {"role": "user", "content": "Question: tell me about hamsters"}
            ],
        }
        resp1 = client.post("/v1/chat/completions", json=first_payload)
        assert resp1.status_code == 200

        recap_payload = {
            "mode": "chat",
            "messages": [
                {
                    "role": "user",
                    "content": "Question: what were we just talking about and could you elaborate?",
                }
            ],
        }
        resp2 = client.post("/v1/chat/completions", json=recap_payload)
        assert resp2.status_code == 200
        body = resp2.json()
        answer = body["choices"][0]["message"]["content"]
        assert "We were just talking about hamsters" in answer
        assert "more detail" in answer
        assert call_state["guide"] == 2
    finally:
        RUNTIME_POLICY.clear()
        RUNTIME_POLICY.update(prev_policy)
        RECENT_SHORT_TERM.clear()
        reset_memory_store_cache()
