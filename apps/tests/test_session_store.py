import os
import sys
import importlib

def reload_session_store(tmp_db_path):
    os.environ["SESSION_DB_PATH"] = str(tmp_db_path)
    if "project_build_instructions.gateway.session_store" in sys.modules:
        del sys.modules["project_build_instructions.gateway.session_store"]
    import libs.gateway.session_store as session_store
    importlib.reload(session_store)
    return session_store

def test_create_get_extend_revoke(tmp_path):
    db_path = tmp_path / "sessions.db"
    session_store = reload_session_store(db_path)
    sess = session_store.create_session(repo=str(tmp_path), allowed_tools=["code.apply_patch", "git.commit"], ttl_minutes=1, created_by="tester")
    assert "token" in sess
    token = sess["token"]

    # newly created session should allow listed tools
    assert session_store.allows_tool(token, "code.apply_patch") is True

    # get_session returns expected fields
    got = session_store.get_session(token)
    assert got is not None
    assert got["repo"] == str(tmp_path)
    assert got["created_by"] == "tester"

    # extend the session
    old_exp = got["expires_at"]
    ext = session_store.extend_session(token, ttl_minutes=5)
    assert ext is not None
    assert ext["expires_at"] > old_exp

    # revoke and ensure session no longer returns
    assert session_store.revoke_session(token) is True
    assert session_store.get_session(token) is None
