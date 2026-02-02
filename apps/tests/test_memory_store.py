from pathlib import Path

import json

import pytest

from apps.services.orchestrator.memory_store import MemoryStore, reset_memory_store_cache, get_memory_store


@pytest.fixture
def memory_tmp(tmp_path: Path) -> Path:
    reset_memory_store_cache()
    return tmp_path


def test_long_term_save_and_query(memory_tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_ROOT", str(memory_tmp))
    store = get_memory_store()

    result = store.save_memory(
        title="Hamster care reference",
        body_md="Hamsters need clean bedding and a balanced diet. Always provide a running wheel.",
        tags=["topic:hamster", "knowledge"],
        scope="auto",
    )

    assert result["scope"] == "long_term"
    items = store.query("hamster diet tips", k=5)
    assert items, "Expected recall for hamster memory"
    assert items[0]["scope"] == "long_term"
    assert "hamster" in items[0]["topic"].lower()


def test_short_term_infers_from_ttl(memory_tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_ROOT", str(memory_tmp))
    store = get_memory_store()

    short_note = store.save_memory(
        title="Session scratch",
        body_md="this is a scratch note",
        tags=["session"],
        ttl_days=1,
    )
    assert short_note["scope"] == "short_term"

    items = store.query("scratch note", scope="short_term", k=2)
    assert items, "Short-term memory should be retrievable"
    assert items[0]["scope"] == "short_term"


def test_prune_expired_short_term(memory_tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_ROOT", str(memory_tmp))
    store = get_memory_store()

    expired = store.save_memory(
        title="Expired note",
        body_md="temporary info",
        ttl_days=0,
        scope="short_term",
    )
    assert expired["scope"] == "short_term"

    # Force the record to be expired by editing the JSONL directly.
    short_path = memory_tmp / "short_term" / "records.jsonl"
    if short_path.exists():
        # Re-write record with expired timestamp.
        lines = short_path.read_text(encoding="utf-8").splitlines()
        rewritten = []
        for line in lines:
            if not line.strip():
                continue
            data = json.loads(line)
            data["expires_at"] = "2000-01-01T00:00:00Z"
            rewritten.append(json.dumps(data))
        short_path.write_text("\n".join(rewritten) + ("\n" if rewritten else ""), encoding="utf-8")

    store.prune_expired()
    items = store.query("temporary info", scope="short_term", k=1)
    assert not items, "Expired short-term memories should be pruned"
    promoted_files = list((memory_tmp / "long_term" / "json").glob("*.json"))
    assert promoted_files, "Expired short-term memory should be promoted to long-term"
    promoted_data = json.loads(promoted_files[0].read_text(encoding="utf-8"))
    assert promoted_data.get("metadata", {}).get("promoted_from") == expired["record"]["id"]


def test_meta_query_returns_recent_short_term(memory_tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_ROOT", str(memory_tmp))
    store = get_memory_store()

    store.save_memory(
        title="Older topic",
        body_md="We discussed deployment automation steps.",
        scope="long_term",
        tags=["topic:deployment"],
    )

    recent = store.save_memory(
        title="Hamster chat",
        body_md="User asked about hamsters and we described their care needs.",
        scope="short_term",
        tags=["topic:hamster"],
    )

    items = store.query("what were we just talking about", k=1)
    assert items, "Recent short-term memory should be returned for meta queries"
    assert items[0]["memory_id"] == recent["record"]["id"]


def test_user_specific_memory_isolation(memory_tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_ROOT", str(memory_tmp))
    reset_memory_store_cache()

    henry_store = get_memory_store("henry")
    spouse_store = get_memory_store("spouse")

    henry_store.save_memory(
        title="Henry note",
        body_md="Henry researched hamster cages.",
        scope="short_term",
        tags=["topic:hamster"],
    )

    spouse_store.save_memory(
        title="Spouse note",
        body_md="Spouse tracked plant care schedule.",
        scope="short_term",
        tags=["topic:plants"],
    )

    henry_items = henry_store.query("hamster", k=3)
    spouse_items = spouse_store.query("hamster", k=3)

    assert any("Henry" in (item.get("title", "")) for item in henry_items)
    assert not any("Henry" in (item.get("title", "")) for item in spouse_items)
