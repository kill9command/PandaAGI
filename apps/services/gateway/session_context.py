"""
Living Session Context - Continuously Updated Conversation Memory

This module implements a living, evolving context that persists across requests
and updates as the conversation progresses. Unlike static context snapshots,
this provides a "running list of what we just did" that grows with each turn.

Key Concepts:
- Session-scoped: One context per user session
- Persistent: Saved to disk, survives server restarts
- Cumulative: Each turn adds to the context
- Summarized: Automatically compresses when it gets too large
- Queryable: Can extract relevant subsets for different LLM calls
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional
from pathlib import Path
import json
import time
import logging
import shutil

from apps.services.gateway.context_migrations import (
    migrate_context,
    validate_context,
    CURRENT_SCHEMA_VERSION
)

logger = logging.getLogger(__name__)


@dataclass
class LiveSessionContext:
    """
    Living, continuously-updated context for a user session.

    This is the "running memory" of what's happened in the conversation.
    It gets richer and more specific as the user talks to the system.

    Unlike traditional conversation history (raw message logs), this is:
    - Structured: Organized by type (preferences, facts, actions, tasks)
    - Compressed: Summarizes instead of storing everything
    - Cumulative: Builds knowledge over time
    - Smart: Knows what's important vs noise
    """

    session_id: str

    # v0 Core fields - What we've learned about the user
    preferences: Dict[str, str] = field(default_factory=dict)
    # Example: {"favorite_hamster": "Syrian", "budget": "under $50", "location": "California"}

    # Current conversation state
    current_topic: Optional[str] = None
    # Example: "shopping for Syrian hamster"

    # Recent actions taken (last 5)
    recent_actions: List[Dict[str, Any]] = field(default_factory=list)
    # Example: [
    #   {"action": "search", "query": "Syrian hamster for sale", "results": 5, "timestamp": 1762815500.0},
    #   {"action": "filter", "criteria": "under $50", "remaining": 3, "timestamp": 1762815510.0}
    # ]

    # Facts discovered during conversation
    discovered_facts: Dict[str, List[str]] = field(default_factory=dict)
    # Example: {
    #   "pricing": ["Syrian hamster: $35.50", "Cage: $60-$120"],
    #   "care": ["needs 800 sq inch cage", "diet: pellets + fresh vegetables"]
    # }

    # Tasks pending completion
    pending_tasks: List[str] = field(default_factory=list)
    # Example: ["Find suitable cage", "Research care requirements", "Compare breeders"]

    # v0 Metadata
    last_updated: float = field(default_factory=time.time)
    turn_count: int = 0
    created_at: float = field(default_factory=time.time)

    # v1 Summarization fields (added 2025-11-10)
    schema_version: int = CURRENT_SCHEMA_VERSION
    fact_summaries: Dict[str, str] = field(default_factory=dict)
    # Example: {"pricing": "Syrian hamsters cost $15-40, cages $50-150, monthly supplies ~$20"}
    action_summary: Optional[str] = None
    # Example: "User searched for hamsters, filtered by budget, compared 3 breeders"
    last_summarized_turn: int = 0

    # v2 Extraction metadata fields (added 2025-11-10)
    extraction_confidence: Dict[str, float] = field(default_factory=dict)
    # Example: {"budget": 0.95, "location": 0.7}
    extraction_method: Dict[str, str] = field(default_factory=dict)
    # Example: {"budget": "regex", "temperament": "llm", "location": "learned_pattern"}
    entities: List[str] = field(default_factory=list)
    # Example: ["Syrian hamster", "Boston", "PetSmart"]

    # v3 Cross-session learning fields (added 2025-11-10)
    user_cluster: Optional[str] = None
    # Example: "shopping_for_pets_budget_conscious"
    learning_feedback: List[Dict[str, Any]] = field(default_factory=list)
    # Example: [{"turn": 3, "corrected_preference": {"location": "Cambridge not Boston"}, "timestamp": 123456}]

    # v4 Conversation history tracking (added 2025-11-11)
    recent_turns: List[Dict[str, Any]] = field(default_factory=list)
    # Example: [{"turn": 3, "user": "do you know my favorite hamster?", "assistant": "Syrian hamster", "timestamp": 123456}]

    # v5 Unified long-term memory store (added 2025-11-12)
    long_term_memories: List[Dict[str, Any]] = field(default_factory=list)
    # Example: [{"key": "favorite_hamster", "value": "Syrian"}, {"key": "project_goal", "value": "Build a context-aware AI"}]

    # v6 Code operations state (added 2025-11-13)
    current_repo: Optional[str] = None
    # Example: "/home/user/project"
    code_state: Dict[str, Any] = field(default_factory=dict)
    # Example: {"branch": "main", "modified": ["auth.py"], "test_status": "12/14 passed"}

    # v7 LLM turn summarizer support (added 2025-11-26)
    last_turn_summary: Optional[Dict[str, Any]] = None
    # Example: {
    #   "short_summary": "Found 4 laptops with NVIDIA GPUs under $700",
    #   "key_findings": ["HP Victus $549", "Lenovo LOQ $649"],
    #   "preferences_learned": {"budget": "under $700"},
    #   "topic": "laptop shopping",
    #   "satisfaction_estimate": 0.8,
    #   "next_turn_hints": ["User focused on NVIDIA requirement"],
    #   "tokens_used": 450
    # }

    def update_from_turn(self, turn_data: Dict[str, Any]):
        """
        Update context based on what happened in this turn.

        This is called at the END of each request to record what was learned.

        Args:
            turn_data: Dictionary with keys like:
                - preferences: Dict of new preferences discovered
                - topic: New conversation topic
                - action: Action taken this turn
                - facts: New facts discovered
                - completed_task: Task that was completed
                - new_tasks: New tasks identified
        """
        self.turn_count += 1
        self.last_updated = time.time()

        # Update preferences (merge, don't overwrite)
        if "preferences" in turn_data and turn_data["preferences"]:
            self.preferences.update(turn_data["preferences"])
            logger.info(f"[LiveContext] {self.session_id}: Added {len(turn_data['preferences'])} preferences")

        # Update current topic
        if "topic" in turn_data and turn_data["topic"]:
            old_topic = self.current_topic
            self.current_topic = turn_data["topic"]
            if old_topic != self.current_topic:
                logger.info(f"[LiveContext] {self.session_id}: Topic changed: {old_topic} → {self.current_topic}")

        # Record action taken
        if "action" in turn_data and turn_data["action"]:
            self.recent_actions.append(turn_data["action"])
            # Keep only last 5 actions
            self.recent_actions = self.recent_actions[-5:]
            logger.info(f"[LiveContext] {self.session_id}: Recorded action: {turn_data['action'].get('action', 'unknown')}")

        # Accumulate discovered facts
        if "facts" in turn_data and turn_data["facts"]:
            for category, facts_list in turn_data["facts"].items():
                if category not in self.discovered_facts:
                    self.discovered_facts[category] = []
                # Add new facts, avoiding duplicates
                for fact in facts_list:
                    if fact not in self.discovered_facts[category]:
                        self.discovered_facts[category].append(fact)
                # Keep only last 10 facts per category
                self.discovered_facts[category] = self.discovered_facts[category][-10:]
            logger.info(f"[LiveContext] {self.session_id}: Added facts to {len(turn_data['facts'])} categories")

        # Update pending tasks
        if "completed_task" in turn_data and turn_data["completed_task"]:
            task = turn_data["completed_task"]
            if task in self.pending_tasks:
                self.pending_tasks.remove(task)
                logger.info(f"[LiveContext] {self.session_id}: Completed task: {task}")

        if "new_tasks" in turn_data and turn_data["new_tasks"]:
            for task in turn_data["new_tasks"]:
                if task not in self.pending_tasks:
                    self.pending_tasks.append(task)
            # Keep only last 10 tasks
            self.pending_tasks = self.pending_tasks[-10:]
            logger.info(f"[LiveContext] {self.session_id}: Added {len(turn_data['new_tasks'])} new tasks")

        # Track conversation turns (v4 feature)
        if "user_message" in turn_data and "assistant_response" in turn_data:
            turn_record = {
                "turn": self.turn_count,
                "user": self._truncate_at_word_boundary(turn_data["user_message"], 200),  # PHASE 3
                "assistant": self._truncate_at_word_boundary(turn_data["assistant_response"], 200),  # PHASE 3
                "timestamp": time.time()
            }
            self.recent_turns.append(turn_record)
            # Keep only last 5 turns
            self.recent_turns = self.recent_turns[-5:]
            logger.info(f"[LiveContext] {self.session_id}: Recorded turn {self.turn_count}")

        # Update code state (v6 feature)
        if "code_repo" in turn_data and turn_data["code_repo"]:
            self.current_repo = turn_data["code_repo"]
            logger.info(f"[LiveContext] {self.session_id}: Updated repo: {self.current_repo}")

        if "code_state_updates" in turn_data and turn_data["code_state_updates"]:
            self.code_state.update(turn_data["code_state_updates"])
            logger.info(f"[LiveContext] {self.session_id}: Updated code state: {list(turn_data['code_state_updates'].keys())}")

    def _truncate_at_word_boundary(self, text: str, max_chars: int) -> str:
        """
        Truncate text at word/sentence boundary, not mid-word.

        PHASE 2+3: Improved truncation to prevent breaking words/sentences.

        Args:
            text: Text to truncate
            max_chars: Maximum characters

        Returns:
            Truncated text ending at word boundary with "..." if truncated
        """
        if len(text) <= max_chars:
            return text

        truncated = text[:max_chars]

        # Try to break at sentence boundary first (best)
        last_sentence = max(
            truncated.rfind('.'),
            truncated.rfind('!'),
            truncated.rfind('?')
        )
        if last_sentence > max_chars * 0.6:
            return text[:last_sentence+1]

        # Fall back to word boundary (good)
        last_space = truncated.rfind(' ')
        if last_space > max_chars * 0.8:
            return truncated[:last_space] + "..."

        # Last resort: break at punctuation (acceptable)
        last_punct = max(
            truncated.rfind(','),
            truncated.rfind(';'),
            truncated.rfind(':')
        )
        if last_punct > max_chars * 0.7:
            return truncated[:last_punct+1] + "..."

        # Absolute fallback: hard truncate but ensure "..." fits within budget
        return truncated[:max_chars-3].rstrip() + "..."

    async def maybe_summarize(self, summarizer: 'ContextSummarizer') -> bool:
        """
        Check and perform summarization if needed.

        This is called periodically (e.g., every 5 turns) to compress
        accumulated context before it hits token limits.

        Args:
            summarizer: ContextSummarizer instance

        Returns:
            True if summarization was performed
        """
        if not await summarizer.should_summarize(self):
            return False

        logger.info(f"[LiveSessionContext] {self.session_id}: Starting summarization at turn {self.turn_count}")

        # Summarize facts per domain
        session_ctx = f"Turn {self.turn_count}, Topic: {self.current_topic}"
        summaries = await summarizer.summarize_facts(self.discovered_facts, session_ctx)

        # Replace verbose facts with summaries
        for domain, summary_result in summaries.items():
            # Store the summary
            self.fact_summaries[domain] = summary_result.summary

            # Replace fact list with key points only
            self.discovered_facts[domain] = summary_result.key_points

            logger.info(
                f"[LiveSessionContext] {self.session_id}: "
                f"Compressed {domain} by {1 - summary_result.compression_ratio:.0%}"
            )

        # Summarize actions
        if len(self.recent_actions) > 5:
            self.action_summary = await summarizer.summarize_actions(
                self.recent_actions,
                session_ctx
            )
            # Keep only last 3 actions
            self.recent_actions = self.recent_actions[-3:]
            logger.info(f"[LiveSessionContext] {self.session_id}: Compressed actions to last 3 + summary")

        self.last_summarized_turn = self.turn_count
        logger.info(f"[LiveSessionContext] {self.session_id}: Summarization complete")

        return True

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation (1 token ≈ 4 chars for natural language)."""
        return len(text) // 4

    def to_context_block(self, max_tokens: int = 200) -> str:
        """
        Convert to text block for LLM injection.

        PHASE 2: Optimized version with stricter budgets and priority ordering.
        PHASE 6: Now returns a JSON string for better LLM parsing.
        PHASE 7: Added previous turn summary for follow-up query handling.

        This is what gets injected into meta-reflection and Guide prompts.
        It's a compressed, human-readable summary of the session state.

        Args:
            max_tokens: Approximate token budget for the context block (default 200)

        Returns:
            Formatted JSON string ready for LLM injection
        """
        context_data: Dict[str, Any] = {}

        # Helper to check budget after adding a section
        def check_budget(current_data: Dict[str, Any]) -> bool:
            return self._estimate_tokens(json.dumps(current_data, separators=(',', ':'))) <= max_tokens

        # PRIORITY 0: Previous Turn Summary (HIGHEST - needed for follow-up questions)
        # This helps the LLM understand what "those options" or "the first one" refers to
        logger.info(f"[LiveContext] to_context_block: last_turn_summary={'present' if self.last_turn_summary else 'MISSING'}")
        if self.last_turn_summary:
            logger.info(f"[LiveContext] Adding previous_turn with summary: {self.last_turn_summary.get('short_summary', 'N/A')[:50]}...")
            prev_turn = {}
            if self.last_turn_summary.get("short_summary"):
                prev_turn["summary"] = self._truncate_at_word_boundary(
                    self.last_turn_summary["short_summary"], 100
                )
            if self.last_turn_summary.get("key_findings"):
                # Include up to 3 key findings
                prev_turn["findings"] = self.last_turn_summary["key_findings"][:3]
            if self.last_turn_summary.get("next_turn_hints"):
                prev_turn["hints"] = self.last_turn_summary["next_turn_hints"][:2]

            if prev_turn:
                context_data["previous_turn"] = prev_turn
                if not check_budget(context_data):
                    # Try with just summary
                    if "findings" in prev_turn:
                        del prev_turn["findings"]
                    if "hints" in prev_turn:
                        del prev_turn["hints"]
                    if not check_budget(context_data):
                        del context_data["previous_turn"]

        # PRIORITY 1: Recent Conversation (needed for pronoun resolution)
        if self.recent_turns:
            recent_conversation_list = []
            for turn in self.recent_turns[-2:]:  # Last 2 turns
                # Skip malformed turns that don't have user/assistant keys
                if "user" not in turn or "assistant" not in turn:
                    continue
                user_text = self._truncate_at_word_boundary(turn["user"], 60)
                assistant_text = self._truncate_at_word_boundary(turn["assistant"], 60)
                recent_conversation_list.append({
                    "turn": turn["turn"],
                    "user": user_text,
                    "assistant": assistant_text
                })
            if recent_conversation_list:  # Only add if we have valid turns
                context_data["recent_conversation"] = recent_conversation_list
            if not check_budget(context_data):
                del context_data["recent_conversation"] # Roll back if over budget

        # PRIORITY 2: User Preferences
        if self.preferences:
            # Prioritize important preference keys
            priority_keys = ["favorite_hamster", "favorite_breed", "favorite", "budget", "location"]

            # Separate preferences into priority and non-priority
            priority_prefs = {}
            other_prefs = {}
            for k, v in self.preferences.items():
                # Check if key matches any priority pattern
                is_priority = any(pk in k.lower() for pk in priority_keys)
                if is_priority:
                    priority_prefs[k] = v
                else:
                    other_prefs[k] = v

            # Combine: priority first, then others (up to 5 total to stay within budget)
            user_preferences_dict = {}
            user_preferences_dict.update(priority_prefs)
            remaining_slots = 5 - len(priority_prefs)
            if remaining_slots > 0:
                for k, v in list(other_prefs.items())[:remaining_slots]:
                    user_preferences_dict[k] = v

            # Only add if there are actual preferences
            if user_preferences_dict:
                context_data["user_preferences"] = user_preferences_dict
                if not check_budget(context_data):
                    del context_data["user_preferences"] # Roll back

        # PRIORITY 3: Current Topic
        if self.current_topic:
            context_data["current_topic"] = self._truncate_at_word_boundary(self.current_topic, 100)
            if not check_budget(context_data):
                del context_data["current_topic"] # Roll back

        # PRIORITY 4: Recent Activity (summary or last action)
        if self.action_summary:
            context_data["recent_activity_summary"] = self._truncate_at_word_boundary(self.action_summary, 80)
            if not check_budget(context_data):
                del context_data["recent_activity_summary"] # Roll back
        elif self.recent_actions:
            latest_action = self.recent_actions[-1] # Only the very last action
            context_data["last_action"] = {
                "action": latest_action.get('action', 'unknown'),
                "summary": self._truncate_at_word_boundary(latest_action.get('summary', ''), 40)
            }
            if not check_budget(context_data):
                del context_data["last_action"] # Roll back

        # PRIORITY 5: Known Facts (summaries or preview)
        if self.fact_summaries:
            fact_summaries_dict = {}
            for domain, summary in list(self.fact_summaries.items())[:2]: # Max 2 domains
                fact_summaries_dict[domain] = self._truncate_at_word_boundary(summary, 60)
            if fact_summaries_dict:
                context_data["known_fact_summaries"] = fact_summaries_dict
                if not check_budget(context_data):
                    del context_data["known_fact_summaries"] # Roll back
        elif self.discovered_facts:
            discovered_facts_dict = {}
            for category, facts_list in list(self.discovered_facts.items())[:2]: # Max 2 categories
                discovered_facts_dict[category] = [self._truncate_at_word_boundary(f, 60) for f in facts_list[:1]] # Only first fact
            if discovered_facts_dict:
                context_data["known_facts_preview"] = discovered_facts_dict
                if not check_budget(context_data):
                    del context_data["known_facts_preview"] # Roll back

        # PRIORITY 6: Pending Tasks
        if self.pending_tasks:
            context_data["pending_tasks"] = [self._truncate_at_word_boundary(task, 50) for task in self.pending_tasks[:2]] # Top 2 tasks
            if not check_budget(context_data):
                del context_data["pending_tasks"] # Roll back

        # Log compression stats
        if context_data:
            final_json_str = json.dumps(context_data, separators=(',', ':'))
            final_tokens = self._estimate_tokens(final_json_str)
            logger.debug(
                f"[LiveContext] {self.session_id}: Context block: "
                f"{final_tokens}/{max_tokens} tokens ({len(context_data)} sections)"
            )
            return final_json_str

        return "" # Return empty string if nothing fit in the budget

    def to_code_context_block(self, max_tokens: int = 200) -> str:
        """
        Convert code state to text block for LLM injection (code mode only).

        This is injected when the user is in code mode to track repository
        state, git status, test results, etc.

        Args:
            max_tokens: Approximate token budget for the context block (default 200)

        Returns:
            Formatted text block for code operations context
        """
        if not self.current_repo:
            return ""

        # Build compact code context
        lines = []
        lines.append(f"**Repository:** {self.current_repo}")

        if self.code_state.get("branch"):
            lines.append(f"**Branch:** {self.code_state['branch']}")

        if self.code_state.get("modified"):
            modified_files = self.code_state["modified"]
            if isinstance(modified_files, list):
                count = len(modified_files)
                lines.append(f"**Modified:** {count} file{'s' if count != 1 else ''}")

        if self.code_state.get("test_status"):
            lines.append(f"**Last Test:** {self.code_state['test_status']}")

        if self.code_state.get("last_action"):
            action = self._truncate_at_word_boundary(self.code_state["last_action"], 60)
            lines.append(f"**Last Action:** {action}")

        context_text = "\n".join(lines)

        # Respect token budget
        if self._estimate_tokens(context_text) > max_tokens:
            # Fall back to just repo + branch
            context_text = f"**Repository:** {self.current_repo}\n"
            if self.code_state.get("branch"):
                context_text += f"**Branch:** {self.code_state['branch']}"

        return context_text

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage with current schema version"""
        data = asdict(self)
        data["schema_version"] = CURRENT_SCHEMA_VERSION
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LiveSessionContext':
        """
        Deserialize from storage with automatic migration.

        This handles loading contexts from any schema version and
        automatically migrating them to the current version.
        """
        # Migrate to current version if needed
        migrated = migrate_context(data)

        # Create instance (filter to only known fields)
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in migrated.items() if k in known_fields}

        return cls(**filtered_data)

    def cleanup_duplicate_preferences(self) -> None:
        """
        Clean up duplicate/conflicting preference keys.

        Priority rules:
        1. Prefer shorter, more specific keys: "favorite_hamster" over "favorite_hamster_breed"
        2. Prefer keys without underscores when semantically equivalent
        3. Remove keys that are subsumed by more specific keys

        Example: If both "favorite_hamster" and "favorite_hamster_breed" exist,
        keep only "favorite_hamster" (it's more specific and canonical).
        """
        if not self.preferences:
            return

        # Define conflicting key groups (prefer first key in each group)
        conflict_groups = [
            ("favorite_hamster", "favorite_hamster_breed", "favorite_breed"),
            ("favorite", "favorite_item", "favorite_thing"),
        ]

        for group in conflict_groups:
            # Find which keys from this group exist
            existing = [k for k in group if k in self.preferences]
            if len(existing) > 1:
                # Keep only the first one (highest priority)
                primary = existing[0]
                for duplicate in existing[1:]:
                    logger.info(
                        f"[SessionContext] {self.session_id}: Removing duplicate preference "
                        f"'{duplicate}' (keeping '{primary}': {self.preferences[primary]})"
                    )
                    del self.preferences[duplicate]

                    # Also remove from extraction metadata if present
                    if hasattr(self, 'extraction_confidence') and duplicate in self.extraction_confidence:
                        del self.extraction_confidence[duplicate]
                    if hasattr(self, 'extraction_method') and duplicate in self.extraction_method:
                        del self.extraction_method[duplicate]

    def get_summary_stats(self) -> Dict[str, int]:
        """Get statistics about this context"""
        return {
            "turn_count": self.turn_count,
            "preferences": len(self.preferences),
            "recent_actions": len(self.recent_actions),
            "fact_categories": len(self.discovered_facts),
            "total_facts": sum(len(facts) for facts in self.discovered_facts.values()),
            "pending_tasks": len(self.pending_tasks),
            "age_seconds": int(time.time() - self.created_at)
        }

    def write_document(self, turn_dir: 'TurnDirectory') -> Path:
        """
        Write session_state.md to turn directory (v4.0 document-driven).

        Args:
            turn_dir: TurnDirectory instance

        Returns:
            Path to written file
        """
        from libs.gateway.doc_writers import write_markdown_doc

        sections = {}

        # Current state
        state_lines = []
        if self.current_topic:
            state_lines.append(f"- **Current Topic:** {self.current_topic}")
        if self.current_repo:
            state_lines.append(f"- **Current Repo:** {self.current_repo}")
        state_lines.append(f"- **Turn Count:** {self.turn_count}")
        sections["Current State"] = "\n".join(state_lines)

        # Preferences
        if self.preferences:
            pref_lines = [f"- **{k}:** {v}" for k, v in self.preferences.items()]
            sections["User Preferences"] = "\n".join(pref_lines)

        # Recent actions
        if self.recent_actions:
            action_lines = []
            for action in self.recent_actions[-5:]:  # Last 5
                action_str = f"- {action.get('action', 'unknown')}"
                if 'query' in action:
                    action_str += f": {action['query']}"
                action_lines.append(action_str)
            sections["Recent Actions"] = "\n".join(action_lines)

        # Discovered facts
        if self.discovered_facts:
            fact_lines = []
            for category, facts in self.discovered_facts.items():
                fact_lines.append(f"**{category}:**")
                for fact in facts[:3]:  # Top 3 per category
                    fact_lines.append(f"  - {fact}")
            sections["Discovered Facts"] = "\n".join(fact_lines)

        # Pending tasks
        if self.pending_tasks:
            sections["Pending Tasks"] = "\n".join([f"- {task}" for task in self.pending_tasks])

        # Code state
        if self.code_state:
            code_lines = [f"- **{k}:** {v}" for k, v in self.code_state.items()]
            sections["Code Operations State"] = "\n".join(code_lines)

        metadata = {
            "Session ID": self.session_id[:16] + "...",
            "Last Updated": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.last_updated))
        }

        path = turn_dir.doc_path("session_state.md")
        from libs.gateway.doc_writers import write_markdown_doc
        write_markdown_doc(path, "Live Session Context", sections, metadata)

        logger.info(f"[LiveContext] Wrote session_state.md ({len(sections)} sections)")
        return path


class SessionContextManager:
    """
    Manages persistent session contexts.

    This is the singleton that handles loading, saving, and caching
    of session contexts across requests.
    """

    def __init__(self, storage_dir: Path):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, LiveSessionContext] = {}
        logger.info(f"[SessionContextManager] Initialized with storage at {self.storage_dir}")

    def get(self, session_id: str) -> LiveSessionContext:
        """
        Load or create session context.

        This is called at the START of each request to get the current
        session state.

        Args:
            session_id: Unique session identifier (usually user profile ID)

        Returns:
            LiveSessionContext with current session state
        """
        # Check in-memory cache first
        if session_id in self._cache:
            logger.debug(f"[SessionContextManager] Cache hit for {session_id}")
            return self._cache[session_id]

        # Try to load from disk
        ctx_path = self.storage_dir / f"{session_id}.json"
        if ctx_path.exists():
            try:
                with open(ctx_path, 'r') as f:
                    data = json.load(f)

                # Check schema version
                version = data.get("schema_version", 0)
                if version < CURRENT_SCHEMA_VERSION:
                    logger.info(f"[SessionContextManager] Migrating {session_id} from v{version} to v{CURRENT_SCHEMA_VERSION}")

                # from_dict handles migration automatically
                ctx = LiveSessionContext.from_dict(data)
                logger.info(f"[SessionContextManager] Loaded {session_id} from disk (turn {ctx.turn_count}, schema v{ctx.schema_version})")

            except Exception as e:
                logger.error(f"[SessionContextManager] Error loading {session_id}: {e}")

                # Backup corrupted file
                backup_path = self.storage_dir / f"{session_id}.backup.{int(time.time())}.json"
                try:
                    shutil.copy(ctx_path, backup_path)
                    logger.info(f"[SessionContextManager] Backed up corrupted context to {backup_path}")
                except Exception as backup_error:
                    logger.error(f"[SessionContextManager] Failed to backup: {backup_error}")

                # Create new on error
                ctx = LiveSessionContext(session_id=session_id)
        else:
            # Create new context
            ctx = LiveSessionContext(session_id=session_id)
            logger.info(f"[SessionContextManager] Created new context for {session_id}")

        # Clean up any duplicate preference keys
        ctx.cleanup_duplicate_preferences()

        # Cache it
        self._cache[session_id] = ctx
        return ctx

    def save(self, ctx: LiveSessionContext):
        """
        Persist session context to disk.

        This is called at the END of each request after updating context.

        Args:
            ctx: LiveSessionContext to persist
        """
        try:
            # Ensure schema version is current
            ctx.schema_version = CURRENT_SCHEMA_VERSION

            ctx_path = self.storage_dir / f"{ctx.session_id}.json"
            with open(ctx_path, 'w') as f:
                json.dump(ctx.to_dict(), f, indent=2)

            # Update cache
            self._cache[ctx.session_id] = ctx

            stats = ctx.get_summary_stats()
            logger.info(f"[SessionContextManager] Saved {ctx.session_id}: {stats} (schema v{ctx.schema_version})")
        except Exception as e:
            logger.error(f"[SessionContextManager] Error saving {ctx.session_id}: {e}")

    def update_and_save(self, session_id: str, turn_data: Dict[str, Any]) -> LiveSessionContext:
        """
        Update context with new turn data and persist.

        This is a convenience method that combines get, update, and save.

        Args:
            session_id: Session identifier
            turn_data: What happened this turn

        Returns:
            Updated LiveSessionContext
        """
        ctx = self.get(session_id)
        ctx.update_from_turn(turn_data)
        self.save(ctx)
        return ctx

    def update_from_cm(self, session_id: str, cm_output: Dict[str, Any]) -> LiveSessionContext:
        """
        Update session context using Context Manager's decisions.

        This is the NEW method that uses CM's memory processing output.
        Replaces the old update_from_turn() for memory updates.

        Args:
            session_id: Session identifier
            cm_output: Context Manager's memory update decisions

        Returns:
            Updated LiveSessionContext
        """
        ctx = self.get(session_id)

        # 1. Update preferences (with CM's reasoning)
        preference_updates = cm_output.get("preferences_updated", {})
        for key, update_data in preference_updates.items():
            old_value = ctx.preferences.get(key)
            new_value = update_data["value"]

            # Update preference
            ctx.preferences[key] = new_value

            # Log change with reasoning
            reasoning = cm_output.get("preference_reasoning", {}).get(key, "No reasoning")
            requires_audit = update_data.get("requires_audit", False)

            if old_value and old_value != new_value:
                log_level = logging.WARNING if requires_audit else logging.INFO
                logger.log(
                    log_level,
                    f"[SessionContext] {session_id}: Preference changed: "
                    f"{key} '{old_value}' → '{new_value}' (CM: {reasoning})"
                )

                # Track in history
                if not hasattr(ctx, 'preference_history'):
                    ctx.preference_history = []
                ctx.preference_history.append({
                    "turn": ctx.turn_count + 1,
                    "key": key,
                    "old_value": old_value,
                    "new_value": new_value,
                    "reasoning": reasoning,
                    "update_type": update_data.get("update_type", "unknown"),
                    "confidence": update_data.get("confidence", 0.0),
                    "timestamp": time.time()
                })
            else:
                logger.info(f"[SessionContext] {session_id}: Set {key} = {new_value} (CM: {reasoning})")

        # Log preserved preferences (stability)
        preserved = cm_output.get("preferences_preserved", {})
        if preserved:
            logger.info(f"[SessionContext] {session_id}: Preserved preferences: {list(preserved.keys())}")

        # 2. Update topic
        if cm_output.get("topic"):
            old_topic = ctx.current_topic
            ctx.current_topic = cm_output["topic"]
            if old_topic != ctx.current_topic:
                logger.info(f"[SessionContext] {session_id}: Topic: '{old_topic}' → '{ctx.current_topic}'")

        # 3. Add facts
        for domain, facts in cm_output.get("facts", {}).items():
            if domain not in ctx.discovered_facts:
                ctx.discovered_facts[domain] = []
            ctx.discovered_facts[domain].extend(facts)
            # Keep last 10
            ctx.discovered_facts[domain] = ctx.discovered_facts[domain][-10:]

        # 4. Add turn summary (compressed)
        turn_summary = cm_output.get("turn_summary", {})
        if turn_summary:
            ctx.recent_turns.append({
                "turn": ctx.turn_count + 1,
                "summary": turn_summary.get("short", ""),
                "bullets": turn_summary.get("bullets", []),
                "topic": cm_output.get("topic", ""),
                "timestamp": time.time()
            })
            ctx.recent_turns = ctx.recent_turns[-5:]  # Keep last 5

        # 5. Update metadata
        ctx.turn_count += 1
        ctx.last_updated = time.time()

        # 5.5. Clean up any duplicate preference keys
        ctx.cleanup_duplicate_preferences()

        # 6. Save to disk
        self.save(ctx)

        logger.info(f"[SessionContext-CM] Updated {session_id}: turn {ctx.turn_count}, {len(preference_updates)} pref updates, topic='{ctx.current_topic}'")

        return ctx

    def clear(self, session_id: str):
        """Clear a session context (delete from disk and cache)"""
        ctx_path = self.storage_dir / f"{session_id}.json"
        if ctx_path.exists():
            ctx_path.unlink()
        if session_id in self._cache:
            del self._cache[session_id]
        logger.info(f"[SessionContextManager] Cleared context for {session_id}")

    def list_sessions(self) -> List[str]:
        """Get all session IDs with saved contexts"""
        return [p.stem for p in self.storage_dir.glob("*.json")]

    def get_stats(self) -> Dict[str, Any]:
        """Get overall statistics"""
        sessions = self.list_sessions()
        return {
            "total_sessions": len(sessions),
            "cached_sessions": len(self._cache),
            "storage_dir": str(self.storage_dir)
        }
