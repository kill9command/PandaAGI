"""
SQLite-backed session store for Gateway sessions.

Provides simple create/get/list/revoke/extend helpers and a small
"allows_tool" helper to check whether a session permits a named tool.

DB location (default):
  apps/db/sessions.db

This module ensures the DB and table exist on import.
"""
from __future__ import annotations

import os
import sqlite3
import json
import time
import secrets
import datetime
import threading
from typing import Optional, List, Dict, Any

# Config: DB path can be overridden via SESSION_DB_PATH env var
DB_DIR = os.path.join(os.getcwd(), "apps", "db")
DB_PATH = os.getenv("SESSION_DB_PATH", os.path.join(DB_DIR, "sessions.db"))
os.makedirs(DB_DIR, exist_ok=True)

DEFAULT_TTL_MINUTES = 15
DEFAULT_ALLOWED_TOOLS = ["code.apply_patch", "git.commit", "tasks.run"]

# Thread lock to serialize database access and prevent race conditions
_db_lock = threading.Lock()

def _conn() -> sqlite3.Connection:
    # Use check_same_thread=False so this module can be used from async code paths.
    # IMPORTANT: Callers must hold _db_lock to prevent race conditions.
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def _ensure_db() -> None:
    with _db_lock:
        conn = _conn()
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        token TEXT PRIMARY KEY,
                        repo TEXT,
                        allowed_tools TEXT,
                        created_by TEXT,
                        created_at INTEGER,
                        expires_at INTEGER,
                        revoked INTEGER DEFAULT 0
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions (expires_at)")
        finally:
            conn.close()

_ensure_db()

def _now() -> int:
    return int(time.time())

def _iso(ts: int) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def create_session(repo: str, allowed_tools: Optional[List[str]] = None, ttl_minutes: int = DEFAULT_TTL_MINUTES, created_by: Optional[str] = None) -> Dict[str, Any]:
    """
    Create a new session and persist it.

    Returns a dict with token, repo, allowed_tools, created_by, created_at, expires_at (unix),
    and expires_at_iso (RFC-like UTC).
    """
    token = secrets.token_urlsafe(32)
    now = _now()
    ttl = int(ttl_minutes or DEFAULT_TTL_MINUTES)
    expires_at = now + ttl * 60
    tools = allowed_tools if allowed_tools is not None else list(DEFAULT_ALLOWED_TOOLS)
    allowed_json = json.dumps(tools)
    with _db_lock:
        conn = _conn()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO sessions (token, repo, allowed_tools, created_by, created_at, expires_at, revoked) VALUES (?, ?, ?, ?, ?, ?, 0)",
                    (token, repo or "", allowed_json, created_by or "", now, expires_at)
                )
        finally:
            conn.close()
    return {
        "token": token,
        "repo": repo or "",
        "allowed_tools": tools,
        "created_by": created_by or "",
        "created_at": now,
        "expires_at": expires_at,
        "expires_at_iso": _iso(expires_at),
    }

def get_session(token: str) -> Optional[Dict[str, Any]]:
    """
    Return session dict iff token exists, not revoked, and not expired.
    If session not found, revoked, or expired -> returns None.
    """
    if not token:
        return None
    with _db_lock:
        conn = _conn()
        try:
            row = conn.execute("SELECT token, repo, allowed_tools, created_by, created_at, expires_at, revoked FROM sessions WHERE token = ?", (token,)).fetchone()
            if not row:
                return None
            d = dict(row)
            if int(d.get("revoked", 0)):
                return None
            if d.get("expires_at") and int(d.get("expires_at")) <= _now():
                return None
            try:
                d["allowed_tools"] = json.loads(d.get("allowed_tools") or "[]")
            except Exception:
                d["allowed_tools"] = []
            d["created_at_iso"] = _iso(int(d["created_at"])) if d.get("created_at") else None
            d["expires_at_iso"] = _iso(int(d["expires_at"])) if d.get("expires_at") else None
            return d
        finally:
            conn.close()

def list_sessions(active_only: bool = False) -> List[Dict[str, Any]]:
    """
    Return list of all sessions. If active_only True, filter out revoked or expired sessions.
    """
    with _db_lock:
        conn = _conn()
        try:
            rows = conn.execute("SELECT token, repo, allowed_tools, created_by, created_at, expires_at, revoked FROM sessions").fetchall()
            out: List[Dict[str, Any]] = []
            for r in rows:
                d = dict(r)
                try:
                    d["allowed_tools"] = json.loads(d.get("allowed_tools") or "[]")
                except Exception:
                    d["allowed_tools"] = []
                d["created_at_iso"] = _iso(int(d["created_at"])) if d.get("created_at") else None
                d["expires_at_iso"] = _iso(int(d["expires_at"])) if d.get("expires_at") else None
                if active_only:
                    if int(d.get("revoked", 0)):
                        continue
                    if d.get("expires_at") and int(d.get("expires_at")) <= _now():
                        continue
                out.append(d)
            return out
        finally:
            conn.close()

def revoke_session(token: str) -> bool:
    """
    Mark a session revoked. Returns True if a row was updated.
    """
    with _db_lock:
        conn = _conn()
        try:
            with conn:
                cur = conn.execute("UPDATE sessions SET revoked = 1 WHERE token = ?", (token,))
                return cur.rowcount > 0
        finally:
            conn.close()

def extend_session(token: str, ttl_minutes: int) -> Optional[Dict[str, Any]]:
    """
    Extend a session's expiry by ttl_minutes from now. Returns updated session summary or None if not found.
    """
    with _db_lock:
        conn = _conn()
        try:
            row = conn.execute("SELECT token FROM sessions WHERE token = ?", (token,)).fetchone()
            if not row:
                return None
            new_exp = _now() + int(ttl_minutes * 60)
            with conn:
                conn.execute("UPDATE sessions SET expires_at = ? WHERE token = ?", (new_exp, token))
            return {"token": token, "expires_at": new_exp, "expires_at_iso": _iso(new_exp)}
        finally:
            conn.close()

def allows_tool(token: str, tool: str) -> bool:
    """
    Return True if the session exists and the given tool is allowed by the session's allowed_tools list.

    Note: create_session stores a default allowed tools list when allowed_tools is None. That ensures
    new sessions are usable without special-casing elsewhere.
    """
    s = get_session(token)
    if not s:
        return False
    allowed = s.get("allowed_tools") or []
    # If allowed is empty list, treat as no-tools-allowed. Typical callers should pass allowed_tools when creating sessions.
    return tool in allowed
