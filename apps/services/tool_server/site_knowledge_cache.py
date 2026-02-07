"""
orchestrator/site_knowledge_cache.py

Site Knowledge Cache with JSON Schema

Stores structured site knowledge for domains including:
- Navigation tips (human-readable)
- Page type classification
- Success/failure tracking for confidence adjustment

ARCHITECTURAL DECISION (2025-12-30):
Upgraded from plain text to JSON schema for better structure,
confidence tracking, and future DOM selector support.
"""
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)

# Default cache directory
DEFAULT_CACHE_DIR = Path(
    os.getenv("SITE_KNOWLEDGE_DIR", "panda_system_docs/site_knowledge")
)


@dataclass
class ActionTrace:
    """Record of a single action taken on a site.

    Used for learning what works/fails for specific goals.
    """
    goal: str                    # What we were trying to do (e.g., "find products", "sort by price")
    action: str                  # What we did (e.g., "click", "type", "search")
    target_text: str = ""        # Text of element clicked/typed into
    target_type: str = ""        # Type of element (e.g., "link", "button", "input")
    input_text: str = ""         # Text typed (for type actions)
    outcome: str = "unknown"     # "success" or "failure"
    reached_page_type: str = ""  # Page type after action (for successes)
    failure_reason: str = ""     # Why it failed (for failures)
    frequency: int = 1           # How many times this action trace was observed
    last_used: str = ""          # ISO timestamp

    def __post_init__(self):
        if not self.last_used:
            self.last_used = datetime.now().isoformat()

    def matches(self, other: "ActionTrace") -> bool:
        """Check if two traces represent the same action."""
        return (
            self.goal == other.goal and
            self.action == other.action and
            self.target_text == other.target_text and
            self.target_type == other.target_type and
            self.input_text == other.input_text
        )


@dataclass
class SiteKnowledgeEntry:
    """Structured site knowledge entry.

    Stores navigation knowledge, page classification, and reliability metrics
    for a domain or specific URL pattern.

    NEW: Also stores action traces for goal-based learning.
    """
    domain: str
    page_type: str = "unknown"  # product_listing, product_detail, search_results, navigation
    navigation_tips: str = ""   # Human-readable navigation tips (legacy)
    selectors: Dict[str, str] = field(default_factory=dict)  # CSS selectors (legacy)
    confidence: float = 0.7     # Reliability score 0.0-1.0
    success_count: int = 0      # Times this knowledge led to success
    failure_count: int = 0      # Times this knowledge failed
    created_at: str = ""        # ISO timestamp
    updated_at: str = ""        # ISO timestamp

    # NEW: Action trace learning
    successful_actions: List[Dict[str, Any]] = field(default_factory=list)
    failed_actions: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def add_action_trace(self, trace: ActionTrace):
        """Add an action trace, merging with existing if found."""
        trace_dict = asdict(trace)
        trace_dict["last_used"] = datetime.now().isoformat()

        target_list = self.successful_actions if trace.outcome == "success" else self.failed_actions

        # Check if we already have this trace
        for existing in target_list:
            existing_trace = ActionTrace(**{k: v for k, v in existing.items() if k in ActionTrace.__dataclass_fields__})
            if existing_trace.matches(trace):
                # Update existing trace
                existing["frequency"] = existing.get("frequency", 1) + 1
                existing["last_used"] = trace_dict["last_used"]
                if trace.outcome == "success":
                    existing["reached_page_type"] = trace.reached_page_type
                else:
                    existing["failure_reason"] = trace.failure_reason
                self.updated_at = datetime.now().isoformat()
                return

        # New trace - add it
        target_list.append(trace_dict)
        self.updated_at = datetime.now().isoformat()

        # Keep lists bounded (max 20 each)
        if len(target_list) > 20:
            # Sort by frequency and recency, keep top 20
            target_list.sort(key=lambda x: (x.get("frequency", 1), x.get("last_used", "")), reverse=True)
            if trace.outcome == "success":
                self.successful_actions = target_list[:20]
            else:
                self.failed_actions = target_list[:20]

    def get_actions_for_goal(self, goal: str) -> Dict[str, List[Dict]]:
        """Get successful and failed actions for a specific goal."""
        return {
            "successful": [a for a in self.successful_actions if a.get("goal") == goal],
            "failed": [a for a in self.failed_actions if a.get("goal") == goal]
        }

    def format_for_llm(self) -> str:
        """Format site knowledge for LLM context."""
        lines = [f"## Site Knowledge for {self.domain}"]

        if self.successful_actions:
            lines.append("\n### What has worked:")
            for action in self.successful_actions[:10]:
                goal = action.get("goal", "unknown")
                act = action.get("action", "unknown")
                target = action.get("target_text", action.get("input_text", ""))
                freq = action.get("frequency", 1)
                lines.append(f"- {goal}: {act} '{target}' (worked {freq}x)")

        if self.failed_actions:
            lines.append("\n### What has NOT worked:")
            for action in self.failed_actions[:5]:
                goal = action.get("goal", "unknown")
                act = action.get("action", "unknown")
                target = action.get("target_text", action.get("input_text", ""))
                reason = action.get("failure_reason", "didn't help")
                lines.append(f"- {goal}: {act} '{target}' - {reason}")

        # Legacy tips if no action traces
        if not self.successful_actions and not self.failed_actions and self.navigation_tips:
            lines.append(f"\n### Navigation tips:\n{self.navigation_tips}")

        return "\n".join(lines)

    def format_for_goal(self, goal: str) -> str:
        """
        Format site knowledge specifically for a goal.

        More targeted than format_for_llm - only includes actions relevant to the goal.
        """
        lines = [f"## Prior Knowledge for {self.domain} (goal: {goal})"]

        actions = self.get_actions_for_goal(goal)

        if actions["successful"]:
            lines.append("\n### What has worked for this goal:")
            for action in actions["successful"][:5]:
                act = action.get("action", "unknown")
                target = action.get("target_text", action.get("input_text", ""))
                result = action.get("reached_page_type", "success")
                freq = action.get("frequency", 1)
                lines.append(f"- {act} '{target}' → {result} (worked {freq}x)")

        if actions["failed"]:
            lines.append("\n### What has NOT worked (avoid these):")
            for action in actions["failed"][:3]:
                act = action.get("action", "unknown")
                target = action.get("target_text", action.get("input_text", ""))
                reason = action.get("failure_reason", "didn't help")
                lines.append(f"- {act} '{target}' → {reason}")

        # Add overall success rate if we have data
        total_success = len(self.successful_actions)
        total_fail = len(self.failed_actions)
        if total_success + total_fail > 0:
            rate = total_success / (total_success + total_fail)
            lines.append(f"\nOverall success rate on this site: {rate:.0%}")

        # Legacy tips as fallback
        if not actions["successful"] and not actions["failed"] and self.navigation_tips:
            lines.append(f"\n### General navigation tips:\n{self.navigation_tips}")

        return "\n".join(lines)

    def get_reliable_patterns(self, min_frequency: int = 2) -> List[Dict]:
        """
        Get patterns that have been reliably successful.

        Returns actions that have worked multiple times.
        """
        return [
            a for a in self.successful_actions
            if a.get("frequency", 1) >= min_frequency
        ]

    def record_success(self):
        """Record a successful use of this knowledge."""
        self.success_count += 1
        self._update_confidence()
        self.updated_at = datetime.now().isoformat()

    def record_failure(self):
        """Record a failed use of this knowledge."""
        self.failure_count += 1
        self._update_confidence()
        self.updated_at = datetime.now().isoformat()

    def _update_confidence(self):
        """Recalculate confidence based on success/failure ratio."""
        total = self.success_count + self.failure_count
        if total > 0:
            # Base confidence from success ratio, with smoothing
            raw_confidence = (self.success_count + 1) / (total + 2)  # Laplace smoothing
            # Weight by sample size (more data = more reliable)
            weight = min(1.0, total / 10)
            self.confidence = 0.5 + (raw_confidence - 0.5) * weight

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SiteKnowledgeEntry":
        """Create from dictionary (JSON deserialization)."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class SiteKnowledgeCache:
    """
    Site knowledge cache with JSON storage.

    Stores structured knowledge including:
    - Navigation tips (human-readable)
    - Page type classification
    - Success/failure tracking

    Supports migration from legacy .txt format to new .json format.
    """

    def __init__(self, cache_dir: Path = None):
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, domain: str) -> Optional[str]:
        """
        Get navigation knowledge for a domain.

        For backwards compatibility, returns just the navigation_tips string.
        Use get_entry() for full structured data.

        Args:
            domain: e.g., "example-shop.com"

        Returns:
            Navigation knowledge text, or None if not cached
        """
        entry = self.get_entry(domain)
        if entry:
            return entry.navigation_tips
        return None

    def get_entry(self, domain: str) -> Optional[SiteKnowledgeEntry]:
        """
        Get full structured knowledge entry for a domain.

        Args:
            domain: e.g., "example-shop.com"

        Returns:
            SiteKnowledgeEntry or None if not cached
        """
        safe_domain = self._sanitize_domain(domain)

        # Try JSON first (new format)
        json_path = self.cache_dir / f"{safe_domain}.json"
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text())
                logger.debug(f"[SiteKnowledge] Found JSON knowledge for {domain}")
                return SiteKnowledgeEntry.from_dict(data)
            except Exception as e:
                logger.warning(f"[SiteKnowledge] Error reading JSON cache for {domain}: {e}")

        # Fallback to legacy .txt format and migrate
        txt_path = self.cache_dir / f"{safe_domain}.txt"
        if txt_path.exists():
            try:
                knowledge = txt_path.read_text().strip()
                if knowledge:
                    # Extract just the tip (before "# Learned:" if present)
                    tip = knowledge.split("# Learned:")[0].strip()
                    logger.info(f"[SiteKnowledge] Migrating legacy .txt for {domain}")

                    # Create new entry and save as JSON
                    entry = SiteKnowledgeEntry(
                        domain=domain,
                        navigation_tips=tip,
                        page_type="unknown",
                        success_count=1  # Assume it was useful since it was saved
                    )
                    self.save_entry(entry)

                    # Remove legacy file
                    txt_path.unlink()
                    return entry
            except Exception as e:
                logger.warning(f"[SiteKnowledge] Error migrating .txt for {domain}: {e}")

        return None

    def save(self, domain: str, knowledge: str) -> bool:
        """
        Save navigation knowledge for a domain.

        For backwards compatibility. Use save_entry() for full structured data.

        Args:
            domain: e.g., "example-shop.com"
            knowledge: Navigation tip, e.g., "Products under 'Our Hamsters'"

        Returns:
            True if saved successfully
        """
        if not knowledge or not knowledge.strip():
            return False

        entry = self.get_entry(domain)
        if entry:
            # Update existing entry
            entry.navigation_tips = knowledge.strip()
            entry.updated_at = datetime.now().isoformat()
        else:
            # Create new entry
            entry = SiteKnowledgeEntry(
                domain=domain,
                navigation_tips=knowledge.strip()
            )

        return self.save_entry(entry)

    def save_entry(self, entry: SiteKnowledgeEntry) -> bool:
        """
        Save a full structured knowledge entry.

        Args:
            entry: SiteKnowledgeEntry to save

        Returns:
            True if saved successfully
        """
        safe_domain = self._sanitize_domain(entry.domain)
        path = self.cache_dir / f"{safe_domain}.json"

        try:
            entry.updated_at = datetime.now().isoformat()
            path.write_text(json.dumps(entry.to_dict(), indent=2))
            logger.info(f"[SiteKnowledge] Saved JSON for {entry.domain}")
            return True
        except Exception as e:
            logger.error(f"[SiteKnowledge] Error saving cache for {entry.domain}: {e}")
            return False

    def record_outcome(self, domain: str, success: bool):
        """
        Record success or failure for a domain's knowledge.

        Args:
            domain: Domain to update
            success: True if knowledge led to successful outcome
        """
        entry = self.get_entry(domain)
        if entry:
            if success:
                entry.record_success()
            else:
                entry.record_failure()
            self.save_entry(entry)

    def record_action_trace(
        self,
        domain: str,
        goal: str,
        action: str,
        outcome: str,
        target_text: str = "",
        target_type: str = "",
        input_text: str = "",
        reached_page_type: str = "",
        failure_reason: str = ""
    ):
        """
        Record an action trace for learning.

        Args:
            domain: Domain where action was taken
            goal: What we were trying to do (e.g., "find products", "sort by price")
            action: What we did (e.g., "click", "type", "search")
            outcome: "success" or "failure"
            target_text: Text of element clicked/typed into
            target_type: Type of element (e.g., "link", "button", "input")
            input_text: Text typed (for type actions)
            reached_page_type: Page type after action (for successes)
            failure_reason: Why it failed (for failures)
        """
        entry = self.get_entry(domain)
        if not entry:
            entry = SiteKnowledgeEntry(domain=domain)

        trace = ActionTrace(
            goal=goal,
            action=action,
            target_text=target_text,
            target_type=target_type,
            input_text=input_text,
            outcome=outcome,
            reached_page_type=reached_page_type,
            failure_reason=failure_reason
        )

        entry.add_action_trace(trace)
        self.save_entry(entry)
        logger.info(f"[SiteKnowledge] Recorded {outcome} trace for {domain}: {goal} via {action}")

    def clear(self, domain: str) -> bool:
        """
        Clear cached knowledge for a domain.

        Args:
            domain: e.g., "example-shop.com"

        Returns:
            True if cleared successfully
        """
        safe_domain = self._sanitize_domain(domain)
        cleared = False

        # Remove both .json and .txt if they exist
        for ext in [".json", ".txt"]:
            path = self.cache_dir / f"{safe_domain}{ext}"
            if path.exists():
                try:
                    path.unlink()
                    cleared = True
                except Exception as e:
                    logger.error(f"[SiteKnowledge] Error clearing {path}: {e}")

        if cleared:
            logger.info(f"[SiteKnowledge] Cleared knowledge for {domain}")
        return True

    def list_domains(self) -> list:
        """List all domains with cached knowledge."""
        domains = set()
        for ext in ["*.json", "*.txt"]:
            for path in self.cache_dir.glob(ext):
                domain = path.stem.replace("_", ".")
                domains.add(domain)
        return sorted(domains)

    def _sanitize_domain(self, domain: str) -> str:
        """Convert domain to safe filename."""
        # Remove protocol if present
        if "://" in domain:
            domain = domain.split("://")[1]

        # Remove path and port
        domain = domain.split("/")[0]
        domain = domain.split(":")[0]

        # Replace dots with underscores for filename safety
        safe = domain.replace(".", "_").replace("-", "_")

        # Remove any other special chars
        safe = "".join(c for c in safe if c.isalnum() or c == "_")

        return safe or "unknown"
