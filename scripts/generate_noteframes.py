#!/usr/bin/env python3
"""
scripts/generate_noteframes.py

LLM-driven NoteFrame generator for staged scraped pages with JSON-schema validation
and a retry loop to enforce strict JSON output.

Usage:
  set -a && source .env && PYTHONPATH=/home/henry/pythonprojects/pandaai python scripts/generate_noteframes.py

Behavior:
- Scans panda_system_docs/scrape_staging/* for staged pages (content.md + meta.json)
- For each staged page, calls the Thinking model endpoint to produce a NoteFrame JSON object:
    { "facts":[...], "decisions":[...], "open_qs":[...], "todos":[...], "summary":"..." }
- Validates the NoteFrame against expected shape and constraints.
- If validation fails, asks the model to re-output only the JSON (up to N retries).
- Falls back to an extractive NoteFrame if the model cannot produce a valid JSON.
- Writes noteframe.json and a small preview file for each staged item.
"""
from __future__ import annotations
import os
import json
import sys
import traceback
import re
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

# Configuration
STAGING_ROOT = Path("panda_system_docs/scrape_staging")
THINK_URL = os.environ.get("THINK_URL", "http://127.0.0.1:8001/v1/chat/completions")
THINK_MODEL_ID = os.environ.get("THINK_MODEL_ID") or os.environ.get("THINK_MODEL") or os.environ.get("MODEL")
MAX_CONTENT_CHARS = 8000  # truncate document content sent to model
MAX_FACTS = 6
MAX_FACT_CHAR = 200
MAX_RETRIES = 2
RETRY_SLEEP = 1.0  # seconds between retries

# Tightened system prompt that includes schema requirements and an explicit example.
SYSTEM_PROMPT = (
    "You are the Context Agent. Produce a single JSON object and nothing else. "
    "The JSON must exactly match the NoteFrame schema described below (keys and types), and must be valid JSON.\n\n"
    "NoteFrame schema:\n"
    "- facts: array of up to 6 concise strings (each <= 200 chars). If a fact is derived from the provided document, append \" (source: <path>/content.md)\" to that string.\n"
    "- decisions: array of short strings describing decisions or configuration choices (may be empty).\n"
    "- open_qs: array of outstanding question strings (may be empty).\n"
    "- todos: array of concrete follow-up actions (may be empty).\n"
    "- summary: a 2-3 sentence plain-text summary (string).\n\n"
    "Example valid output (JSON only, no surrounding text):\n"
    '{"facts":["Fact one (source: panda_system_docs/scrape_staging/EXAMPLE/content.md)"],"decisions":[],"open_qs":[],"todos":[],"summary":"Two-sentence summary here."}\n\n'
    "Constraints: do not include any extra commentary, do not wrap JSON in markdown fences, and do not add additional top-level keys."
)


def post_chat_completion(payload: Dict[str, Any], timeout: int = 120) -> Dict[str, Any]:
    """
    Post a chat completion request to THINK_URL. Uses httpx if available, falls back to urllib.
    Returns parsed JSON response.
    """
    try:
        import httpx  # type: ignore
    except Exception:
        httpx = None

    if httpx:
        try:
            resp = httpx.post(THINK_URL, json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            raise RuntimeError(f"httpx request to {THINK_URL} failed: {e}") from e

    # fallback to stdlib
    try:
        import urllib.request
        import json as _json

        data = _json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(THINK_URL, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _json.load(resp)
    except Exception as e:
        raise RuntimeError(f"urllib request to {THINK_URL} failed: {e}") from e


def extract_text_preview(text: str, max_chars: int = MAX_CONTENT_CHARS) -> str:
    if not text:
        return ""
    t = text.strip()
    if len(t) <= max_chars:
        return t
    head = t[:max_chars]
    # cut at recent sentence end if available
    tail = head.rfind(".")
    if tail > max_chars - 400 and tail > 100:
        return head[:tail + 1]
    return head + "\n\n...[truncated]..."


def extract_json_from_model_output(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    # Attempt to find JSON inside code fences first
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.S)
    if m:
        candidate = m.group(1)
        try:
            return json.loads(candidate)
        except Exception:
            pass
    # fallback: first { ... }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        # cleanup common trailing commas
        cleaned = re.sub(r",\s*}", "}", candidate)
        cleaned = re.sub(r",\s*\]", "]", cleaned)
        try:
            return json.loads(cleaned)
        except Exception:
            return None
    return None


def validate_noteframe(nf: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate the NoteFrame structure and content constraints.
    Returns (is_valid, errors).
    """
    errors: List[str] = []
    if not isinstance(nf, dict):
        return False, ["NoteFrame is not a JSON object"]

    required_keys = {"facts", "decisions", "open_qs", "todos", "summary"}
    keys = set(nf.keys())
    missing = required_keys - keys
    if missing:
        errors.append(f"Missing keys: {sorted(list(missing))}")

    # facts
    facts = nf.get("facts")
    if not isinstance(facts, list):
        errors.append("facts must be a list")
    else:
        if len(facts) > MAX_FACTS:
            errors.append(f"facts has {len(facts)} entries, max {MAX_FACTS}")
        for i, f in enumerate(facts):
            if not isinstance(f, str):
                errors.append(f"facts[{i}] is not a string")
            else:
                if len(f) > MAX_FACT_CHAR:
                    errors.append(f"facts[{i}] exceeds {MAX_FACT_CHAR} chars")

    # decisions/open_qs/todos: lists of strings
    for key in ("decisions", "open_qs", "todos"):
        v = nf.get(key)
        if not isinstance(v, list):
            errors.append(f"{key} must be a list")
        else:
            for i, it in enumerate(v):
                if not isinstance(it, str):
                    errors.append(f"{key}[{i}] is not a string")

    # summary
    summary = nf.get("summary")
    if not isinstance(summary, str):
        errors.append("summary must be a string")
    else:
        if len(summary.strip()) < 10:
            errors.append("summary too short (<10 chars)")
        if len(summary) > 2000:
            errors.append("summary too long (>2000 chars)")

    return (len(errors) == 0), errors


def parse_model_response(resp: Dict[str, Any]) -> str:
    """
    Extract text content from common completion response shapes.
    """
    try:
        choices = resp.get("choices") or []
        if choices and isinstance(choices, list):
            c = choices[0]
            if isinstance(c, dict):
                if "message" in c and isinstance(c["message"], dict):
                    return c["message"].get("content", "") or c["message"].get("text", "") or ""
                return c.get("text") or ""
        # fallback to top-level text
        return resp.get("text") or resp.get("output") or json.dumps(resp)
    except Exception:
        return json.dumps(resp)


def call_thinking_model_with_retries(document_preview: str, staged_path: str, max_retries: int = MAX_RETRIES) -> Optional[Dict[str, Any]]:
    """
    Call the Thinking model, attempt to parse JSON and validate. If validation fails,
    instruct the model to re-output only the JSON (up to max_retries).
    """
    attempt = 0
    last_text = ""
    while attempt <= max_retries:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Document path: {staged_path}\n\nDocument content (truncated):\n\n{document_preview}\n\nReturn a single JSON NoteFrame with keys: facts, decisions, open_qs, todos, summary. Output only the JSON object and nothing else."
            },
        ]
        payload = {
            "model": THINK_MODEL_ID or "model",
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": 700,
        }
        try:
            resp = post_chat_completion(payload, timeout=120)
            text = parse_model_response(resp)
            last_text = text
            nf = extract_json_from_model_output(text)
            if nf and isinstance(nf, dict):
                ok, errors = validate_noteframe(nf)
                if ok:
                    return nf
                else:
                    # Validation failed — prepare a strict retry instruction
                    attempt += 1
                    err_msg = "; ".join(errors)
                    follow_messages = [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"The previous output failed validation: {err_msg}\n\nPlease output ONLY a single valid JSON object that conforms to the NoteFrame schema. Do not include any commentary."}
                    ]
                    follow_payload = {
                        "model": THINK_MODEL_ID or "model",
                        "messages": follow_messages,
                        "temperature": 0.0,
                        "max_tokens": 700,
                    }
                    try:
                        time.sleep(RETRY_SLEEP)
                        resp2 = post_chat_completion(follow_payload, timeout=90)
                        text2 = parse_model_response(resp2)
                        last_text = text2
                        nf2 = extract_json_from_model_output(text2)
                        if nf2 and isinstance(nf2, dict):
                            ok2, errors2 = validate_noteframe(nf2)
                            if ok2:
                                return nf2
                            else:
                                # continue loop to allow another retry if attempts remain
                                attempt += 1
                                continue
                        else:
                            attempt += 1
                            continue
                    except Exception:
                        attempt += 1
                        continue
            else:
                # Could not parse JSON; try again with strict instruction
                attempt += 1
                follow_messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": "Your previous output could not be parsed as JSON. Output ONLY a single valid JSON NoteFrame object now."}
                ]
                follow_payload = {
                    "model": THINK_MODEL_ID or "model",
                    "messages": follow_messages,
                    "temperature": 0.0,
                    "max_tokens": 700,
                }
                try:
                    time.sleep(RETRY_SLEEP)
                    resp2 = post_chat_completion(follow_payload, timeout=90)
                    text2 = parse_model_response(resp2)
                    last_text = text2
                    nf2 = extract_json_from_model_output(text2)
                    if nf2 and isinstance(nf2, dict):
                        ok2, errors2 = validate_noteframe(nf2)
                        if ok2:
                            return nf2
                        else:
                            attempt += 1
                            continue
                    else:
                        attempt += 1
                        continue
                except Exception:
                    attempt += 1
                    continue

        except Exception as e:
            # network or endpoint error — bail early
            print(f"Model call error for {staged_path}: {e}", file=sys.stderr)
            traceback.print_exc()
            return None

    # After retries, try to parse last_text one more time and return if structure is acceptable
    final_nf = None
    if last_text:
        final_nf = extract_json_from_model_output(last_text)
        if final_nf and isinstance(final_nf, dict):
            okf, errs = validate_noteframe(final_nf)
            if okf:
                return final_nf
    return None


def build_extractive_noteframe(content: str, staged_path: str) -> Dict[str, Any]:
    sents = re.split(r'(?<=[\.\?\!])\s+', content.strip())
    facts: List[str] = []
    for s in sents:
        s_clean = " ".join(s.split())
        if not s_clean:
            continue
        s_trim = s_clean[:MAX_FACT_CHAR].rstrip()
        if len(s_clean) > MAX_FACT_CHAR:
            s_trim = s_trim.rstrip(".!?,;:") + "..."
        facts.append(f"{s_trim} (source: {staged_path}/content.md)")
        if len(facts) >= MAX_FACTS:
            break
    summary = ""
    if sents:
        summary = " ".join([sents[0].strip()] + ([sents[1].strip()] if len(sents) > 1 else []))[:800]
    return {"facts": facts, "decisions": [], "open_qs": [], "todos": [], "summary": summary}


def process_staged_item(staged_dir: Path) -> Dict[str, Any]:
    content_path = staged_dir / "content.md"
    if not content_path.exists():
        return {"ok": False, "path": str(staged_dir), "error": "missing content.md"}
    content_text = content_path.read_text(encoding="utf-8", errors="replace")
    preview = extract_text_preview(content_text, MAX_CONTENT_CHARS)

    # Try LLM-driven NoteFrame with retries and validation
    noteframe = None
    try:
        noteframe = call_thinking_model_with_retries(preview, str(staged_dir), max_retries=MAX_RETRIES)
    except Exception as e:
        print(f"Error calling thinking model for {staged_dir}: {e}", file=sys.stderr)
        traceback.print_exc()

    if noteframe is None:
        # Fallback to extractive summary
        noteframe = build_extractive_noteframe(content_text, str(staged_dir))
        noteframe["__fallback"] = True

    # Save NoteFrame to file
    out_path = staged_dir / "noteframe.json"
    try:
        out_path.write_text(json.dumps(noteframe, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        return {"ok": False, "path": str(staged_dir), "error": f"failed to write noteframe: {e}"}

    # Write a short preview file for human inspection
    try:
        preview_path = staged_dir / "noteframe_preview.txt"
        with preview_path.open("w", encoding="utf-8") as f:
            f.write("NoteFrame Preview\n\n")
            facts = noteframe.get("facts", [])
            for i, fact in enumerate(facts, 1):
                f.write(f"{i}. {fact}\n")
            f.write("\nSummary:\n")
            f.write(noteframe.get("summary", "") + "\n")
            if noteframe.get("__fallback"):
                f.write("\n[NOTE] This NoteFrame was generated with an extractive fallback; model output was not valid JSON.\n")
    except Exception:
        pass

    return {"ok": True, "path": str(staged_dir), "noteframe": noteframe}


def main():
    if not STAGING_ROOT.exists():
        print(f"No staging root found at {STAGING_ROOT}; exiting.")
        return

    staged_dirs = sorted([d for d in STAGING_ROOT.iterdir() if d.is_dir()])
    if not staged_dirs:
        print("No staged pages found; exiting.")
        return

    results = []
    for d in staged_dirs:
        print(f"Processing staged item: {d}")
        try:
            res = process_staged_item(d)
            results.append(res)
            if res.get("ok"):
                print(f"  -> NoteFrame written for {d}")
            else:
                print(f"  -> Failed for {d}: {res.get('error')}")
        except Exception as e:
            print(f"Unhandled error processing {d}: {e}", file=sys.stderr)
            traceback.print_exc()
            results.append({"ok": False, "path": str(d), "error": str(e)})

    print("\nSummary:")
    for r in results:
        print(json.dumps(r, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
