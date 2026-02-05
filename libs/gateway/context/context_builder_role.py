"""
Context Builder Role - Consolidated Context Assembly

Assembles relevant context from all sources into context.md for downstream roles.
This role runs FIRST in every turn, before Planner/Coordinator.

Sources:
1. Prior turn summary (from LiveSessionContext)
2. Memory documents (user_preferences, user_facts, system_learnings, etc.)
3. Recent claims (from ClaimRegistry, domain-filtered)
4. Session state (current topic, preferences, discovered facts)

Author: Panda System Architecture
Date: 2025-12-06 (Consolidated from UnifiedContextManager + ContextBuilderRole)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from apps.services.gateway.session_context import LiveSessionContext
    from apps.services.tool_server.shared_state.claims import ClaimRegistry

from libs.gateway.llm.recipe_loader import load_recipe, RecipeNotFoundError

logger = logging.getLogger(__name__)

# Memory storage base path
MEMORY_BASE = Path("panda_system_docs/memory")

# Token budget for context.md
DEFAULT_MAX_TOKENS = 1500

# Domain mapping for claim filtering
DOMAIN_MAP = {
    "buy": ["pricing", "commerce", "shopping", "availability"],
    "find": ["research", "specifications", "comparison", "pricing"],
    "compare": ["comparison", "specifications", "pricing"],
    "recall": ["memory", "preferences", "facts"],
    "explain": ["general", "facts", "research"],
}


@dataclass
class MemoryDocument:
    """A memory document loaded from storage"""
    name: str
    content: str
    path: Path
    tokens: int = 0
    relevance: float = 0.0


@dataclass
class ContextSources:
    """All sources available for context building"""
    # Memory documents
    user_preferences: Optional[MemoryDocument] = None
    user_facts: Optional[MemoryDocument] = None
    system_learnings: Optional[MemoryDocument] = None
    domain_knowledge: Optional[MemoryDocument] = None
    lessons: List[MemoryDocument] = field(default_factory=list)

    # Session state
    prior_turn_summary: Optional[Dict[str, Any]] = None
    session_preferences: Dict[str, str] = field(default_factory=dict)
    current_topic: Optional[str] = None
    turn_count: int = 0
    discovered_facts: Dict[str, List[str]] = field(default_factory=dict)

    # Claims
    recent_claims: List[Dict[str, Any]] = field(default_factory=list)

    def to_summary(self) -> Dict[str, Any]:
        """Summary for logging/debugging"""
        return {
            "memory_docs": {
                "user_preferences": self.user_preferences is not None,
                "user_facts": self.user_facts is not None,
                "system_learnings": self.system_learnings is not None,
                "domain_knowledge": self.domain_knowledge is not None,
                "lessons_count": len(self.lessons),
            },
            "session": {
                "has_prior_turn": self.prior_turn_summary is not None,
                "preferences_count": len(self.session_preferences),
                "current_topic": self.current_topic,
                "turn_count": self.turn_count,
                "facts_categories": list(self.discovered_facts.keys()),
            },
            "claims_count": len(self.recent_claims),
        }


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (4 chars per token)"""
    return len(text) // 4


def load_memory_documents(base_path: Optional[Path] = None) -> Dict[str, MemoryDocument]:
    """
    Load memory documents from storage.

    Returns dict with keys: user_preferences, user_facts, system_learnings,
    domain_knowledge, lessons (list)
    """
    base = base_path or MEMORY_BASE
    docs = {}

    doc_files = {
        "user_preferences": base / "user_preferences.md",
        "user_facts": base / "user_facts.md",
        "system_learnings": base / "system_learnings.md",
        "domain_knowledge": base / "domain_knowledge.md",
    }

    for name, path in doc_files.items():
        if path.exists():
            try:
                content = path.read_text()
                # Skip placeholder content
                if "_No " in content and len(content) < 500:
                    continue
                docs[name] = MemoryDocument(
                    name=name,
                    content=content,
                    path=path,
                    tokens=_estimate_tokens(content)
                )
            except Exception as e:
                logger.warning(f"[ContextBuilder] Failed to load {name}: {e}")

    # Load lessons
    lessons_dir = base / "lessons"
    docs["lessons"] = []
    if lessons_dir.exists():
        for lesson_file in lessons_dir.glob("*.md"):
            try:
                content = lesson_file.read_text()
                docs["lessons"].append(MemoryDocument(
                    name=lesson_file.stem,
                    content=content,
                    path=lesson_file,
                    tokens=_estimate_tokens(content)
                ))
            except Exception as e:
                logger.warning(f"[ContextBuilder] Failed to load lesson {lesson_file}: {e}")

    return docs


def extract_session_context(live_ctx: Optional['LiveSessionContext']) -> Dict[str, Any]:
    """
    Extract relevant context from LiveSessionContext.
    """
    if live_ctx is None:
        return {}

    return {
        "prior_turn_summary": live_ctx.last_turn_summary,
        "session_preferences": live_ctx.preferences,
        "current_topic": live_ctx.current_topic,
        "turn_count": live_ctx.turn_count,
        "discovered_facts": live_ctx.discovered_facts,
        "entities": live_ctx.entities,
    }


def get_recent_claims(
    claim_registry: Optional['ClaimRegistry'],
    session_id: str,
    query_intent: str = "find",
    max_claims: int = 10,
) -> List[Dict[str, Any]]:
    """
    Get recent claims from ClaimRegistry, filtered by domain.
    """
    if claim_registry is None:
        return []

    try:
        # Get allowed domains for this intent
        allowed_domains = DOMAIN_MAP.get(query_intent, ["general"])

        # Query claims - use get_claims_for_topics if available, else get all
        # For now, get all claims for session and filter
        claims = []

        # Try to get claims by session
        if hasattr(claim_registry, 'get_claims_by_type'):
            claim_rows = claim_registry.get_claims_by_type(session_id, claim_type=None)
            for row in claim_rows[:max_claims]:
                claims.append({
                    "statement": row.statement,
                    "confidence": row.confidence,
                    "evidence": list(row.evidence) if row.evidence else [],
                    "metadata": row.metadata,
                })

        logger.info(f"[ContextBuilder] Retrieved {len(claims)} claims for session {session_id}")
        return claims

    except Exception as e:
        logger.warning(f"[ContextBuilder] Failed to get claims: {e}")
        return []


def gather_all_sources(
    user_query: str,
    live_ctx: Optional['LiveSessionContext'] = None,
    claim_registry: Optional['ClaimRegistry'] = None,
    session_id: str = "default",
    query_intent: str = "find",
) -> ContextSources:
    """
    Gather context from all sources.
    """
    sources = ContextSources()

    # 1. Load memory documents
    memory_docs = load_memory_documents()
    sources.user_preferences = memory_docs.get("user_preferences")
    sources.user_facts = memory_docs.get("user_facts")
    sources.system_learnings = memory_docs.get("system_learnings")
    sources.domain_knowledge = memory_docs.get("domain_knowledge")
    sources.lessons = memory_docs.get("lessons", [])

    # 2. Extract session context
    if live_ctx:
        session_data = extract_session_context(live_ctx)
        sources.prior_turn_summary = session_data.get("prior_turn_summary")
        sources.session_preferences = session_data.get("session_preferences", {})
        sources.current_topic = session_data.get("current_topic")
        sources.turn_count = session_data.get("turn_count", 0)
        sources.discovered_facts = session_data.get("discovered_facts", {})

    # 3. Get recent claims
    sources.recent_claims = get_recent_claims(
        claim_registry, session_id, query_intent
    )

    logger.info(f"[ContextBuilder] Gathered sources: {sources.to_summary()}")
    return sources


def build_context_simple(
    user_query: str,
    sources: ContextSources,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    """
    Build context.md using simple concatenation (no LLM).
    Fast fallback when LLM is not needed or available.
    """
    sections = []
    current_tokens = 0

    # Header
    sections.append("# Context for Current Query\n")
    current_tokens += 10

    # === Prior Turn (ALWAYS include if exists) ===
    if sources.prior_turn_summary:
        sections.append("## Prior Turn")
        summary = sources.prior_turn_summary

        if summary.get("short_summary"):
            sections.append(f"Summary: {summary['short_summary']}")
        if summary.get("topic"):
            sections.append(f"Topic: {summary['topic']}")
        if summary.get("key_findings"):
            sections.append("Key findings:")
            for finding in summary["key_findings"][:5]:
                sections.append(f"- {finding}")
        sections.append("")
        current_tokens += 150

    # === Session Preferences ===
    if sources.session_preferences and current_tokens < max_tokens * 0.3:
        prefs = sources.session_preferences
        if prefs:
            sections.append("## Session Preferences")
            for key, value in list(prefs.items())[:5]:
                sections.append(f"- {key}: {value}")
            sections.append("")
            current_tokens += len(prefs) * 10

    # === User Preferences (from memory) ===
    if sources.user_preferences and current_tokens < max_tokens * 0.4:
        sections.append("## User Preferences")
        content = sources.user_preferences.content
        # Extract bullet points only
        for line in content.split("\n"):
            if line.startswith("- ") or line.startswith("* "):
                sections.append(line)
                current_tokens += _estimate_tokens(line)
                if current_tokens > max_tokens * 0.4:
                    break
        sections.append("")

    # === System Knowledge ===
    if sources.system_learnings and current_tokens < max_tokens * 0.6:
        sections.append("## System Knowledge")
        content = sources.system_learnings.content
        for line in content.split("\n"):
            if line.startswith("- ") or line.startswith("* "):
                sections.append(line)
                current_tokens += _estimate_tokens(line)
                if current_tokens > max_tokens * 0.6:
                    break
        sections.append("")

    # === Discovered Facts ===
    if sources.discovered_facts and current_tokens < max_tokens * 0.7:
        sections.append("## Discovered Facts")
        for category, facts in sources.discovered_facts.items():
            sections.append(f"**{category}:**")
            for fact in facts[:3]:
                sections.append(f"- {fact}")
                current_tokens += _estimate_tokens(fact)
        sections.append("")

    # === Current Claims ===
    if sources.recent_claims and current_tokens < max_tokens * 0.9:
        sections.append("## Current Claims")
        for claim in sources.recent_claims[:5]:
            stmt = claim.get("statement", "")
            conf = claim.get("confidence", "medium")
            sections.append(f"- {stmt} (confidence: {conf})")
            current_tokens += _estimate_tokens(stmt) + 10
            if current_tokens > max_tokens * 0.9:
                break
        sections.append("")

    # Footer
    sections.append(f"---\n_Context built: {datetime.now(timezone.utc).isoformat()}_")
    sections.append(f"_Tokens: ~{current_tokens}_")

    return "\n".join(sections)


async def build_context_with_llm(
    user_query: str,
    sources: ContextSources,
    llm_client: Any,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    """
    Build context.md using LLM for intelligent selection and summarization.
    """
    import httpx

    # Load recipe and prompt using the recipe system
    try:
        recipe = load_recipe("memory/context_builder")
        system_prompt = recipe.get_prompt()
        # Override max_tokens from recipe if specified
        if recipe.token_budget and recipe.token_budget.output:
            max_tokens = recipe.token_budget.output
    except RecipeNotFoundError:
        logger.warning("[ContextBuilder] Recipe not found, using fallback prompt")
        system_prompt = "You are the Context Builder. Assemble relevant context for the query."

    # Build user message with all sources
    user_message_parts = [
        "## User Query",
        f"```\n{user_query}\n```",
        "",
    ]

    # Prior turn summary
    if sources.prior_turn_summary:
        user_message_parts.extend([
            "## Prior Turn Summary",
            f"```json\n{json.dumps(sources.prior_turn_summary, indent=2)}\n```",
            "",
        ])

    # Session preferences
    if sources.session_preferences:
        user_message_parts.extend([
            "## Session Preferences",
            f"```json\n{json.dumps(sources.session_preferences, indent=2)}\n```",
            "",
        ])

    # Memory documents (excerpts)
    if sources.user_preferences:
        content = sources.user_preferences.content[:1500]
        user_message_parts.extend([
            "## user_preferences.md (excerpt)",
            f"```\n{content}\n```",
            "",
        ])

    if sources.system_learnings:
        content = sources.system_learnings.content[:1500]
        user_message_parts.extend([
            "## system_learnings.md (excerpt)",
            f"```\n{content}\n```",
            "",
        ])

    # Recent claims
    if sources.recent_claims:
        claims_text = "\n".join([
            f"- {c['statement']} (confidence: {c['confidence']})"
            for c in sources.recent_claims[:5]
        ])
        user_message_parts.extend([
            "## Recent Claims",
            f"```\n{claims_text}\n```",
            "",
        ])

    # Instructions
    user_message_parts.extend([
        "## Instructions",
        f"Create context.md with relevant context for this query.",
        f"Target: ~{max_tokens} tokens maximum.",
        "Follow the format in your system prompt.",
        "Be concise - include only what helps answer this query.",
    ])

    user_message = "\n".join(user_message_parts)

    # Call LLM
    try:
        solver_url = os.getenv("SOLVER_URL", "http://localhost:8000/v1/chat/completions")
        solver_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")
        solver_model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                solver_url,
                headers={
                    "Authorization": f"Bearer {solver_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": solver_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    "temperature": 0.3,
                    "max_tokens": max_tokens,
                    "top_p": 0.8,
                    "stop": ["<|im_end|>", "<|endoftext|>"],
                    "repetition_penalty": 1.05
                }
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return content

    except Exception as e:
        logger.error(f"[ContextBuilder] LLM call failed: {e}")
        raise


async def run_context_builder_role(
    user_query: str,
    turn_dir: Path,
    live_session_context: Optional['LiveSessionContext'] = None,
    claim_registry: Optional['ClaimRegistry'] = None,
    session_id: str = "default",
    query_intent: str = "find",
    use_llm: bool = False,  # Default to simple for speed
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    """
    Run Context Builder role to assemble context.md.

    This is the main entry point - call this at the start of each turn.

    Args:
        user_query: The user's current question
        turn_dir: Directory to write context.md
        live_session_context: Session state with prior turn summary
        claim_registry: Registry for cached claims
        session_id: Session identifier
        query_intent: Query intent for domain filtering (buy, find, compare, etc.)
        use_llm: Whether to use LLM for intelligent selection
        max_tokens: Maximum tokens for context.md

    Returns:
        context.md content (also written to turn_dir/context.md)
    """
    start_time = time.time()
    logger.info(f"[ContextBuilder] Starting context assembly for session {session_id}")

    # Gather all sources
    sources = gather_all_sources(
        user_query=user_query,
        live_ctx=live_session_context,
        claim_registry=claim_registry,
        session_id=session_id,
        query_intent=query_intent,
    )

    # Build context
    if use_llm:
        try:
            context_content = await build_context_with_llm(
                user_query=user_query,
                sources=sources,
                llm_client=None,  # Uses httpx directly
                max_tokens=max_tokens,
            )
        except Exception as e:
            logger.warning(f"[ContextBuilder] LLM failed, using simple: {e}")
            context_content = build_context_simple(
                user_query=user_query,
                sources=sources,
                max_tokens=max_tokens,
            )
    else:
        context_content = build_context_simple(
            user_query=user_query,
            sources=sources,
            max_tokens=max_tokens,
        )

    # Write context.md
    if isinstance(turn_dir, Path):
        context_path = turn_dir / "context.md"
    else:
        # TurnDirectory object
        context_path = turn_dir.doc_path("context.md")

    context_path.write_text(context_content)

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(
        f"[ContextBuilder] Wrote context.md "
        f"({len(context_content)} chars, {_estimate_tokens(context_content)} tokens) "
        f"in {elapsed_ms:.1f}ms"
    )

    # Also write sources summary for debugging
    sources_path = context_path.parent / "context_sources.json"
    sources_path.write_text(json.dumps(sources.to_summary(), indent=2))

    return context_content


# ============================================================================
# Memory Write Utilities (for Summarizer role)
# ============================================================================

def write_memory_document(
    doc_type: str,
    content: str,
    base_path: Optional[Path] = None,
) -> bool:
    """
    Write content to a memory document.
    Used by the Summarizer role to persist memories.
    """
    base = base_path or MEMORY_BASE

    doc_paths = {
        "user_preferences": base / "user_preferences.md",
        "user_facts": base / "user_facts.md",
        "system_learnings": base / "system_learnings.md",
        "domain_knowledge": base / "domain_knowledge.md",
    }

    if doc_type not in doc_paths:
        logger.error(f"[MemoryWrite] Unknown document type: {doc_type}")
        return False

    try:
        doc_paths[doc_type].write_text(content)
        logger.info(f"[MemoryWrite] Updated {doc_type} ({len(content)} chars)")
        return True
    except Exception as e:
        logger.error(f"[MemoryWrite] Failed to write {doc_type}: {e}")
        return False


def append_to_memory_document(
    doc_type: str,
    section: str,
    entry: str,
    base_path: Optional[Path] = None,
) -> bool:
    """
    Append an entry to a specific section of a memory document.
    Used by the Summarizer role to add new memories without overwriting.
    """
    base = base_path or MEMORY_BASE

    doc_paths = {
        "user_preferences": base / "user_preferences.md",
        "user_facts": base / "user_facts.md",
        "system_learnings": base / "system_learnings.md",
        "domain_knowledge": base / "domain_knowledge.md",
    }

    if doc_type not in doc_paths:
        logger.error(f"[MemoryAppend] Unknown document type: {doc_type}")
        return False

    try:
        path = doc_paths[doc_type]
        content = path.read_text() if path.exists() else f"# {doc_type.replace('_', ' ').title()}\n"

        # Find the section and add entry
        if section in content:
            lines = content.split("\n")
            new_lines = []
            section_found = False
            entry_added = False

            for line in lines:
                new_lines.append(line)
                if line.strip() == section:
                    section_found = True
                elif section_found and not entry_added:
                    if line.strip() == "" or line.startswith("_No "):
                        if line.startswith("_No "):
                            new_lines[-1] = entry
                        else:
                            new_lines.append(entry)
                        entry_added = True

            content = "\n".join(new_lines)
        else:
            content += f"\n{section}\n{entry}\n"

        # Update timestamp
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        if "_Last Updated:" in content:
            import re
            content = re.sub(r"_Last Updated: [^_]+_", f"_Last Updated: {timestamp}_", content)
        else:
            content += f"\n_Last Updated: {timestamp}_\n"

        path.write_text(content)
        logger.info(f"[MemoryAppend] Added entry to {doc_type}/{section}")
        return True

    except Exception as e:
        logger.error(f"[MemoryAppend] Failed to append to {doc_type}: {e}")
        return False
