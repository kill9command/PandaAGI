import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from apps.services.orchestrator.memory_store import get_memory_store, reset_memory_store_cache


@pytest.fixture()
def temp_mem_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MEMORY_ROOT", str(tmp_path))
    reset_memory_store_cache()
    yield tmp_path
    reset_memory_store_cache()


def _run_cli(args: list[str], env_root: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["MEMORY_ROOT"] = str(env_root)
    return subprocess.run(
        [sys.executable, "scripts/memory_admin.py", *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )


def test_memory_admin_list_short_term(temp_mem_root: Path):
    store = get_memory_store("default")
    store.save_memory(
        title="Hamster chat",
        body_md="We discussed hamster care.",
        scope="short_term",
        tags=["topic:hamster"],
    )

    result = _run_cli(["list", "--scope", "short_term", "--json", "--user", "default"], temp_mem_root)
    data = json.loads(result.stdout)
    assert data
    assert data[0]["title"] == "Hamster chat"
    assert data[0]["scope"] == "short_term"


def test_memory_admin_list_text(temp_mem_root: Path):
    store = get_memory_store("default")
    store.save_memory(
        title="Knowledge note",
        body_md="Long-term hamster faq.",
        scope="long_term",
        tags=["knowledge", "topic:hamster"],
    )

    result = _run_cli(["list", "--scope", "long_term", "--limit", "1", "--user", "default"], temp_mem_root)
    assert "Knowledge note" in result.stdout
