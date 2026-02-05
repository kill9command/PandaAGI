"""Intent-based context weighting for unified context allocation.

This module defines weights for different context sources based on query intent,
enabling dynamic allocation of the 4,300 token context budget.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict


@dataclass
class IntentWeights:
    """Weights for different context sources based on intent."""

    memory: float = 1.0
    history: float = 1.0
    rag: float = 1.0
    claims: float = 1.0

    def get_weight(self, source: str) -> float:
        """Get weight for a specific source type."""
        weights_map = {
            "memory": self.memory,
            "long_term_memory": self.memory,
            "baseline_memory": self.memory,
            "recall_memory": self.memory,
            "history": self.history,
            "living_context": self.history,
            "rag": self.rag,
            "doc_search": self.rag,
            "claims": self.claims,
            "recent_claims": self.claims,
        }
        return weights_map.get(source, 1.0)


# Intent-based weight profiles (based on quality-agent recommendations)
INTENT_WEIGHT_PROFILES: Dict[str, IntentWeights] = {
    "recall": IntentWeights(
        memory=1.8,   # Strong boost (80% increase) - past conversations are critical
        history=1.5,  # Moderate boost (50% increase) - recent context helps
        rag=0.3,      # Heavy penalty (70% reduction) - docs not relevant
        claims=0.5    # Moderate penalty - cached results less relevant
    ),

    "informational": IntentWeights(
        rag=1.5,      # Moderate boost - documentation is key
        claims=1.2,   # Slight boost - cached answers help
        memory=1.0,   # Neutral - may have relevant context
        history=0.7   # Slight penalty - less relevant
    ),

    "transactional": IntentWeights(
        claims=1.5,   # Moderate boost - recent pricing/offers matter
        memory=1.2,   # Slight boost - user preferences matter
        rag=0.6,      # Moderate penalty - docs less relevant
        history=1.0   # Neutral - keep for context
    ),

    "navigational": IntentWeights(
        rag=1.3,      # Slight boost - directory info useful
        claims=1.0,   # Neutral
        memory=0.7,   # Slight penalty - less relevant
        history=0.7   # Slight penalty - less relevant
    ),

    "code": IntentWeights(
        memory=1.3,   # Slight boost - remember past edits
        history=1.5,  # Moderate boost - recent changes critical
        rag=0.5,      # Moderate penalty - usually not needed
        claims=0.3    # Heavy penalty - rarely relevant
    ),

    "unknown": IntentWeights(
        # Balanced weights for unclear intent
        memory=1.0,
        history=1.0,
        rag=1.0,
        claims=1.0
    )
}


def get_intent_weights(intent: str) -> IntentWeights:
    """Get intent weights for a classified intent.

    Args:
        intent: Intent type (recall, informational, transactional, navigational, code, unknown)

    Returns:
        IntentWeights object with multipliers for each context source
    """
    return INTENT_WEIGHT_PROFILES.get(intent, INTENT_WEIGHT_PROFILES["unknown"])


# Minimum allocation guarantees (tokens)
# Even with penalties, ensure some context from each source
MINIMUM_ALLOCATIONS = {
    "memory": 100,    # Always include some memory
    "history": 200,   # Always include some recent context
    "rag": 0,         # Can be zero if not relevant
    "claims": 0,      # Can be zero if not relevant
}

# Total context budget (tokens)
TOTAL_CONTEXT_BUDGET = 4300

# Per-source maximum allocations (tokens)
# Prevent any single source from dominating
MAXIMUM_ALLOCATIONS = {
    "memory": 2500,
    "history": 2000,
    "rag": 2500,
    "claims": 2000,
}
