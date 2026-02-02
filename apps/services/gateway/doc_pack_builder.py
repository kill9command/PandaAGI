"""
Document Pack Builder with Auto-Trimming

Builds document packs with automatic token budget enforcement through
priority-based trimming.

Quality Agent Requirement: Auto-trim low-priority sections when budget tight,
never trim critical sections (user query, system prompts).
"""
import logging
from typing import Dict, Any, Optional
from apps.services.gateway.token_utils import count_tokens_safe

logger = logging.getLogger(__name__)


class DocPackBuilder:
    """
    Builds document packs with automatic token budget enforcement.

    Priority Levels:
        10 (Critical): Core system prompts, user query (NEVER trim)
        9 (High): Session state, recent memory (trim only if desperate)
        8 (Important): Capsule summaries, key claims (truncate if needed)
        7 (Useful): RAG context, related facts
        5 (Nice-to-have): Statistics, metadata
        3 (Optional): Debug info, verbose logs
        1 (Lowest): Examples, documentation
    """

    def __init__(self, max_tokens: int, model_id: str = "gpt-3.5-turbo"):
        """
        Initialize doc pack builder.

        Args:
            max_tokens: Maximum tokens for assembled doc pack
            model_id: Model ID for accurate token counting
        """
        self.max_tokens = max_tokens
        self.model_id = model_id
        self.current_tokens = 0
        self.sections = {}

    def add_section(
        self,
        section_name: str,
        content: str,
        priority: int = 5
    ) -> bool:
        """
        Add a section to the doc pack.

        Args:
            section_name: Section identifier (e.g., "unified_context")
            content: Section content
            priority: 1-10, higher = more important (10 = never trim)

        Returns:
            True if added/truncated successfully, False if couldn't fit
        """

        if content is None:
            content = ""

        tokens = count_tokens_safe(content, model_id=self.model_id)

        if self.current_tokens + tokens <= self.max_tokens:
            # Fits perfectly - add it
            self.sections[section_name] = {
                "content": content,
                "tokens": tokens,
                "priority": priority,
                "truncated": False
            }
            self.current_tokens += tokens
            logger.debug(
                f"[DocPack] Added {section_name} ({tokens} tokens, priority {priority})"
            )
            return True

        # Would exceed budget - need to make room
        available = self.max_tokens - self.current_tokens

        if priority >= 8:
            # High priority - try to make room by trimming lower priority sections
            freed = self._trim_to_fit(needed=tokens, min_priority=priority)

            if self.current_tokens + tokens <= self.max_tokens:
                # Successfully made room
                self.sections[section_name] = {
                    "content": content,
                    "tokens": tokens,
                    "priority": priority,
                    "truncated": False
                }
                self.current_tokens += tokens
                logger.info(
                    f"[DocPack] Made room for {section_name} by trimming "
                    f"{freed} tokens from lower priority sections"
                )
                return True

        # Can't fit even after trimming - try truncation
        if available >= 100:  # At least 100 tokens available
            from apps.services.gateway.token_utils import truncate_to_budget

            truncated = truncate_to_budget(
                content,
                max_tokens=available,
                model_id=self.model_id
            )
            truncated_tokens = count_tokens_safe(truncated, model_id=self.model_id)

            self.sections[section_name] = {
                "content": truncated,
                "tokens": truncated_tokens,
                "priority": priority,
                "truncated": True,
                "original_tokens": tokens
            }
            self.current_tokens += truncated_tokens

            logger.warning(
                f"[DocPack] Truncated {section_name} from {tokens} → {truncated_tokens} tokens "
                f"(priority {priority})"
            )
            return True

        # Cannot fit at all
        logger.warning(
            f"[DocPack] Insufficient budget for {section_name} "
            f"({tokens} tokens, {available} available, priority {priority})"
        )
        return False

    def _trim_to_fit(self, needed: int, min_priority: int) -> int:
        """
        Remove low-priority sections to free up tokens.

        Args:
            needed: Tokens needed
            min_priority: Minimum priority to keep (trim everything below)

        Returns:
            Tokens freed
        """

        # Sort sections by priority (lowest first)
        sorted_sections = sorted(
            self.sections.items(),
            key=lambda x: x[1]["priority"]
        )

        freed = 0
        removed = []

        for name, section in sorted_sections:
            if section["priority"] < min_priority:
                freed += section["tokens"]
                removed.append(name)
                logger.info(
                    f"[DocPack] Trimmed {name} (priority {section['priority']}) "
                    f"to free {section['tokens']} tokens"
                )

                if freed >= needed:
                    break

        # Remove sections
        for name in removed:
            del self.sections[name]

        self.current_tokens -= freed
        return freed

    def build(self) -> str:
        """
        Assemble final document pack.

        Returns:
            Assembled document pack string
        """

        # Sort sections by priority (highest first)
        sorted_sections = sorted(
            self.sections.items(),
            key=lambda x: x[1]["priority"],
            reverse=True
        )

        parts = []
        for name, section in sorted_sections:
            parts.append(f"# {name}")

            if section.get("truncated"):
                original = section.get("original_tokens", "unknown")
                current = section["tokens"]
                parts.append(
                    f"⚠️  TRUNCATED: {original} tokens → {current} tokens "
                    f"(due to budget constraint)"
                )

            parts.append(section["content"])
            parts.append("")  # Blank line between sections

        assembled = "\n".join(parts)

        logger.info(
            f"[DocPack] Built pack: {len(self.sections)} sections, "
            f"{self.current_tokens}/{self.max_tokens} tokens "
            f"({self.current_tokens / self.max_tokens * 100:.1f}% utilization)"
        )

        return assembled

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the doc pack.

        Returns:
            Statistics dictionary
        """

        truncated_count = sum(1 for s in self.sections.values() if s.get("truncated"))

        return {
            "sections": len(self.sections),
            "total_tokens": self.current_tokens,
            "max_tokens": self.max_tokens,
            "utilization": f"{self.current_tokens / self.max_tokens * 100:.1f}%",
            "truncated_sections": truncated_count,
            "breakdown": {
                name: {
                    "tokens": section["tokens"],
                    "priority": section["priority"],
                    "truncated": section.get("truncated", False)
                }
                for name, section in self.sections.items()
            }
        }

    def has_section(self, section_name: str) -> bool:
        """Check if section exists in pack."""
        return section_name in self.sections

    def get_section(self, section_name: str) -> Optional[str]:
        """Get content of a specific section."""
        section = self.sections.get(section_name)
        return section["content"] if section else None

    def remove_section(self, section_name: str) -> bool:
        """
        Remove a section from the pack.

        Returns:
            True if section was removed, False if it didn't exist
        """
        if section_name in self.sections:
            tokens = self.sections[section_name]["tokens"]
            del self.sections[section_name]
            self.current_tokens -= tokens
            logger.info(f"[DocPack] Removed {section_name} ({tokens} tokens)")
            return True
        return False
