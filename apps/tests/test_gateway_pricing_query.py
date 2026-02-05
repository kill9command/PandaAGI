import copy
import json
json_module = json

import httpx
from fastapi.testclient import TestClient

from apps.services.tool_server.memory_store import reset_memory_store_cache
import libs.gateway.app as gateway_module
from libs.gateway.app import (
    app as gateway_app,
    RUNTIME_POLICY,
    GUIDE_URL,
    COORDINATOR_URL,
    TOOL_SERVER_URL,
    RECENT_SHORT_TERM,
    _extract_pricing_query,
)


def test_extract_pricing_query_uses_history_subject():
    user_text = "can you find me one for sale?"
    history_text = "my favorite hamster is the syrian hamster"
    result = _extract_pricing_query(user_text, fallback=user_text, history=history_text)
    assert result.lower() == "syrian hamster"


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


def _capsule_payload(content: dict) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(content)
                }
            }
        ]
    }


def test_gateway_auto_adds_purchasing_lookup(monkeypatch, tmp_path):
    RECENT_SHORT_TERM.clear()
    prev_policy = copy.deepcopy(RUNTIME_POLICY)
    call_state = {"guide": 0, "lookup_args": None}

    async def mock_post(self, url, json=None, headers=None):
        payload = json or {}
        messages = payload.get("messages") or []
        first_content = messages[0]["content"] if messages else ""
        if first_content.startswith("You are the **Coordinator**"):
            return DummyResp(_coordinator_payload())
        if first_content.startswith("You are the **Context Manager**"):
            ticket_id = "unknown"
            try:
                bundle_blob = messages[1]["content"]
                bundle_obj = json_module.loads(bundle_blob)
                ticket_id = bundle_obj.get("ticket_id", ticket_id)
            except Exception:
                pass
            return DummyResp(
                _capsule_payload(
                    {
                        "_type": "CAPSULE",
                        "ticket_id": ticket_id,
                        "status": "ok",
                        "claims": [],
                        "caveats": [],
                        "open_questions": [],
                        "artifacts": [],
                        "recommended_answer_shape": "bulleted",
                        "budget_report": {"raw_tokens": 0, "reduced_tokens": 0},
                    }
                    )
                )
        if first_content.startswith("You are the **Guide**"):
            call_state["guide"] += 1
            if call_state["guide"] == 1:
                return DummyResp(
                    _guide_payload(
                        {
                            "_type": "TICKET",
                            "analysis": "Need to confirm current offers.",
                            "ticket_id": "pending",
                            "user_turn_id": "pending",
                            "goal": "Current Syrian hamster availability",
                            "micro_plan": ["Search reputable retailers", "Capture price and availability"],
                            "subtasks": [
                                {"kind": "search", "q": "Syrian hamster for sale", "why": "find active listings"}
                            ],
                            "constraints": {"latency_ms": 4000, "budget_tokens": 2000, "privacy": "allow_external"},
                            "verification": {"required": ["prices", "dates"]},
                            "return": {"format": "raw_bundle", "max_items": 8},
                        }
                    )
                )
            return DummyResp(
                _guide_payload(
                    {
                        "_type": "ANSWER",
                        "analysis": "Capsule processed; ready to respond.",
                        "answer": "No offers found yet, but the purchasing lookup was executed.",
                        "solver_self_history": ["Asked about Syrian hamster availability."],
                        "suggest_memory_save": None,
                        "tool_intent": None,
                    }
                )
            )
        if url == f"{TOOL_SERVER_URL}/purchasing.lookup":
            call_state["lookup_args"] = payload or {}
            return DummyResp({"query": payload.get("query"), "extra_query": payload.get("extra_query", ""), "offers": [], "best_offer": None})
        if url == f"{TOOL_SERVER_URL}/doc.search":
            return DummyResp({"chunks": [], "summary": "noop"})
        if url == f"{TOOL_SERVER_URL}/memory.query":
            return DummyResp({"items": []})
        return DummyResp({"ok": True})

    async def mock_get(self, url, params=None, headers=None):
        if url.endswith("/v1/models"):
            return DummyResp({"data": [{"id": GUIDE_URL}]})
        return DummyResp({"ok": True})

    try:
        monkeypatch.setenv("MEMORY_ROOT", str(tmp_path))
        reset_memory_store_cache()
        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        client = TestClient(gateway_app)
        payload = {
            "mode": "chat",
            "messages": [
                {"role": "user", "content": "my favorite hamster is the syrian hamster"},
                {"role": "assistant", "content": "Noted."},
                {"role": "user", "content": "can you find one for sale for me?"},
            ],
        }
        resp = client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 200
        lookup_args = call_state["lookup_args"]
        assert lookup_args is not None, "Gateway should invoke purchasing.lookup automatically"
        assert lookup_args.get("query") == "syrian hamster"
        assert lookup_args.get("extra_query") == "for sale"
    finally:
        RUNTIME_POLICY.clear()
        RUNTIME_POLICY.update(prev_policy)
        RECENT_SHORT_TERM.clear()
        reset_memory_store_cache()


def test_gateway_pricing_uses_long_term_memory_when_history_blank(monkeypatch, tmp_path):
    RECENT_SHORT_TERM.clear()
    prev_policy = copy.deepcopy(RUNTIME_POLICY)
    call_state = {"lookup_args": None, "guide": 0}

    async def mock_post(self, url, json=None, headers=None):
        payload = json or {}
        messages = payload.get("messages") or []
        first_content = messages[0]["content"] if messages else ""
        if first_content.startswith("You are the **Coordinator**"):
            return DummyResp(_coordinator_payload())
        if first_content.startswith("You are the **Context Manager**"):
            ticket_id = "pending"
            try:
                bundle_blob = messages[1]["content"]
                bundle_obj = json_module.loads(bundle_blob)
                ticket_id = bundle_obj.get("ticket_id", ticket_id)
            except Exception:
                pass
            return DummyResp(
                _capsule_payload(
                    {
                        "_type": "CAPSULE",
                        "ticket_id": ticket_id,
                        "status": "ok",
                        "claims": [],
                        "caveats": [],
                        "open_questions": [],
                        "artifacts": [],
                        "recommended_answer_shape": "bulleted",
                        "budget_report": {"raw_tokens": 0, "reduced_tokens": 0},
                    }
                )
            )
        if first_content.startswith("You are the **Guide**"):
            call_state["guide"] += 1
            if call_state["guide"] == 1:
                return DummyResp(
                    _guide_payload(
                        {
                            "_type": "TICKET",
                            "analysis": "Need hamster offers.",
                            "ticket_id": "pending",
                            "user_turn_id": "pending",
                            "goal": "Find items for sale online",
                            "micro_plan": ["Search for listings"],
                            "subtasks": [
                                {"kind": "search", "q": "items for sale online", "why": "find anything"}
                            ],
                            "constraints": {"latency_ms": 4000, "budget_tokens": 2000, "privacy": "allow_external"},
                            "verification": {"required": ["prices"]},
                            "return": {"format": "raw_bundle", "max_items": 8},
                        }
                    )
                )
            return DummyResp(
                _guide_payload(
                    {
                        "_type": "ANSWER",
                        "analysis": "done",
                        "answer": "showing results",
                        "solver_self_history": [],
                        "suggest_memory_save": None,
                        "tool_intent": None,
                    }
                )
            )
        if url == f"{TOOL_SERVER_URL}/purchasing.lookup":
            call_state["lookup_args"] = payload or {}
            return DummyResp({"query": payload.get("query"), "extra_query": payload.get("extra_query", ""), "offers": [], "best_offer": None})
        if url == f"{TOOL_SERVER_URL}/doc.search":
            return DummyResp({"chunks": [], "summary": "noop"})
        if url == f"{TOOL_SERVER_URL}/memory.query":
            return DummyResp({"items": []})
        return DummyResp({"ok": True})

    async def mock_get(self, url, params=None, headers=None):
        if url.endswith("/v1/models"):
            return DummyResp({"data": [{"id": GUIDE_URL}]})
        return DummyResp({"ok": True})

    def fake_long_term(profile, *, max_items=6):
        return ["User memory (favorite_hamster): Syrian hamster"]

    try:
        monkeypatch.setenv("MEMORY_ROOT", str(tmp_path))
        reset_memory_store_cache()
        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        monkeypatch.setattr(gateway_module, "_load_long_term_memories", fake_long_term)

        client = TestClient(gateway_app)
        payload = {
            "mode": "chat",
            "messages": [
                {"role": "user", "content": "do you know what my favorite hamster is?"},
                {"role": "assistant", "content": "Your favorite hamster is the Syrian hamster."},
                {"role": "user", "content": "can you find me some for sale online please?"},
            ],
        }
        resp = client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 200
        lookup_args = call_state["lookup_args"]
        assert lookup_args is not None
        assert lookup_args.get("query") == "syrian hamster"
    finally:
        RUNTIME_POLICY.clear()
        RUNTIME_POLICY.update(prev_policy)
        RECENT_SHORT_TERM.clear()
        reset_memory_store_cache()
