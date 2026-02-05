"""Intent classification for query routing.

Simplified LLM-friendly classifier with minimal regex patterns as fallback.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class IntentType(Enum):
    """Types of user intent for query classification."""

    RETRY = "retry"         # User wants to re-execute with fresh data
    INFORMATIONAL = "informational"  # User wants to learn
    TRANSACTIONAL = "transactional"  # User wants to buy
    NAVIGATIONAL = "navigational"    # User wants a specific site
    CODE = "code"           # User wants to work with code
    RECALL = "recall"       # User asking about past conversations
    SELF_EXTENSION = "self_extension"  # User wants to build new skills/tools
    UNKNOWN = "unknown"


@dataclass
class IntentSignal:
    """Signal indicating a specific intent."""

    intent: IntentType
    confidence: float  # 0.0 to 1.0
    reason: str


class IntentClassifier:
    """
    Simplified intent classifier using minimal keyword patterns.

    Designed to be fast for routing decisions. Detailed classification
    happens later in the LLM-based flow.
    """

    # Core patterns for quick intent detection (reduced from 49 to ~15)
    RETRY_KEYWORDS = [
        "retry", "refresh", "again", "redo", "still not", "didn't work",
        "any other", "more options", "show me more"
    ]

    RECALL_KEYWORDS = [
        "do you remember", "what is my", "my favorite", "have we talked",
        "earlier you said", "did we discuss", "remind me"
    ]

    CODE_KEYWORDS = [
        "file", "code", "git", "commit", "function", "class", "debug",
        "repository", "codebase", "script"
    ]

    TRANSACTIONAL_KEYWORDS = [
        "buy", "purchase", "order", "for sale", "cheapest", "best price",
        "where to buy", "shopping"
    ]

    NAVIGATIONAL_KEYWORDS = [
        "go to", "visit", "website", "site", ".com", ".org", ".net"
    ]

    SELF_EXTENSION_KEYWORDS = [
        "build a skill", "create a skill", "make a skill", "new skill",
        "build a tool", "create a tool", "make a tool", "new tool",
        "teach yourself", "learn to do", "add capability",
        "extend yourself", "self-improve", "build capability",
        "create workflow", "build workflow", "automate this"
    ]

    def classify(self, query: str, context: str = "") -> IntentSignal:
        """
        Classify a query into an intent type using simple keyword matching.

        Args:
            query: The user's query text
            context: Additional context (e.g., mode)

        Returns:
            IntentSignal with the detected intent and confidence
        """
        text = f"{query} {context}".lower()

        # Priority order: RETRY > RECALL > CODE > TRANSACTIONAL > NAVIGATIONAL > INFORMATIONAL

        # Check RETRY (highest priority - user wants fresh results)
        if self._has_keyword(text, self.RETRY_KEYWORDS):
            return IntentSignal(
                intent=IntentType.RETRY,
                confidence=0.8,
                reason="Retry/refresh keywords detected"
            )

        # Check RECALL (memory queries)
        if self._has_keyword(text, self.RECALL_KEYWORDS):
            return IntentSignal(
                intent=IntentType.RECALL,
                confidence=0.8,
                reason="Memory/recall keywords detected"
            )

        # Check SELF_EXTENSION (skill/tool building)
        if self._has_keyword(text, self.SELF_EXTENSION_KEYWORDS):
            return IntentSignal(
                intent=IntentType.SELF_EXTENSION,
                confidence=0.85,
                reason="Self-extension/skill-building keywords detected"
            )

        # Check CODE (only in code mode or with explicit keywords)
        if "code" in context or self._has_keyword(text, self.CODE_KEYWORDS):
            if self._has_keyword(text, self.CODE_KEYWORDS):
                return IntentSignal(
                    intent=IntentType.CODE,
                    confidence=0.7,
                    reason="Code-related keywords detected"
                )

        # Check TRANSACTIONAL (commerce)
        if self._has_keyword(text, self.TRANSACTIONAL_KEYWORDS):
            return IntentSignal(
                intent=IntentType.TRANSACTIONAL,
                confidence=0.7,
                reason="Purchase/commerce keywords detected"
            )

        # Check NAVIGATIONAL (specific site)
        if self._has_keyword(text, self.NAVIGATIONAL_KEYWORDS):
            return IntentSignal(
                intent=IntentType.NAVIGATIONAL,
                confidence=0.6,
                reason="Navigation keywords detected"
            )

        # Default to INFORMATIONAL
        return IntentSignal(
            intent=IntentType.INFORMATIONAL,
            confidence=0.5,
            reason="Default informational intent"
        )

    def _has_keyword(self, text: str, keywords: list) -> bool:
        """Check if any keyword is present in text."""
        return any(kw in text for kw in keywords)
