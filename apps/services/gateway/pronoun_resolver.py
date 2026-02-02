"""
Pronoun Resolution for Context-Aware Query Handling

Resolves pronouns and elliptical references in user queries using conversation context.
"""

import re
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


def resolve_pronouns(
    query: str,
    recent_turns: List[Dict[str, Any]],
    preferences: Dict[str, str]
) -> tuple[str, bool]:
    """
    Resolve pronouns and elliptical references using conversation context.

    Args:
        query: User's query (may contain pronouns like "some", "them", "it")
        recent_turns: Recent conversation history with user/assistant turns
        preferences: User preferences that might provide context

    Returns:
        tuple: (resolved_query, was_resolved)
            - resolved_query: Query with pronouns replaced with entities
            - was_resolved: True if any pronoun was resolved

    Examples:
        Query: "find some for sale"
        Recent: "Syrian hamster is my favorite"
        → "find Syrian hamsters for sale"

        Query: "what about them?"
        Recent: Last discussed "dwarf hamsters"
        → "what about dwarf hamsters?"
    """
    resolved = query
    was_resolved = False

    # Extract entity from recent conversation (last 3 turns)
    entity = _extract_primary_entity(recent_turns, preferences)

    if not entity:
        logger.debug("[PronounResolver] No entity found in context, cannot resolve")
        return query, False

    logger.info(f"[PronounResolver] Extracted entity from context: '{entity}'")

    # Pronoun patterns to resolve
    patterns = [
        # "some" → entity
        (r'\b(find|search for|get|buy|looking for)\s+some\b', r'\1 ' + entity),
        (r'\bsome\s+(for sale|online|near me)\b', entity + r' \1'),

        # "them"/"those" → entity (plural)
        (r'\b(about|for|with)\s+(them|those)\b', r'\1 ' + entity),
        (r'\b(them|those)\s+(are|were|have)\b', entity + r' \2'),

        # "it"/"that" → entity (singular)
        (r'\b(about|for|with)\s+(it|that)\b', r'\1 ' + entity),
        (r'\b(it|that)\s+(is|was|has)\b', entity + r' \2'),

        # "one" → entity
        (r'\bfind\s+one\b', 'find ' + entity),
        (r'\bget\s+one\b', 'get ' + entity),
    ]

    for pattern, replacement in patterns:
        new_resolved = re.sub(pattern, replacement, resolved, flags=re.IGNORECASE)
        if new_resolved != resolved:
            logger.info(f"[PronounResolver] Resolved: '{resolved}' → '{new_resolved}'")
            resolved = new_resolved
            was_resolved = True

    return resolved, was_resolved


def _extract_primary_entity(
    recent_turns: List[Dict[str, Any]],
    preferences: Dict[str, str]
) -> Optional[str]:
    """
    Extract the primary entity being discussed from recent conversation.

    Priority:
    1. Most recent assistant response (what we just talked about)
    2. User's stated favorite/preference
    3. Most recent user query mentioning an entity

    Args:
        recent_turns: Recent conversation history
        preferences: User preferences

    Returns:
        Entity string (e.g., "Syrian hamster") or None
    """
    # Priority 1: Check last assistant response for entities
    if recent_turns:
        last_turn = recent_turns[-1]
        assistant_text = last_turn.get("assistant", "")

        # Extract entities from assistant response
        entity = _extract_entity_from_text(assistant_text)
        if entity:
            return entity

    # Priority 2: Check user's favorite preference
    for key, value in preferences.items():
        if "favorite" in key and value:
            # favorite_hamster: "Syrian" → "Syrian hamster"
            category = key.replace("favorite_", "")
            return f"{value} {category}" if category != value else value

    # Priority 3: Check recent user queries (last 2 turns)
    for turn in reversed(recent_turns[-2:]):
        user_text = turn.get("user", "")
        entity = _extract_entity_from_text(user_text)
        if entity:
            return entity

    return None


def _extract_entity_from_text(text: str) -> Optional[str]:
    """
    Extract main entity from text using patterns.

    Patterns:
    - "Syrian hamster" (adjective + noun)
    - "dwarf hamster" (type + noun)
    - "hamster cage" (noun + noun)

    Args:
        text: Text to extract entity from

    Returns:
        Entity string or None
    """
    text_lower = text.lower()

    # Common pet/product patterns
    patterns = [
        # Syrian hamster, dwarf hamster, etc.
        r'\b(syrian|dwarf|roborovski|chinese|campbell|winter white)\s+(hamster)s?\b',

        # hamster + product (hamster cage, hamster food)
        r'\b(hamster)\s+(cage|food|wheel|bedding|toy)s?\b',

        # Generic hamster mention
        r'\b(hamster)s?\b',

        # Other pets
        r'\b(guinea pig|rabbit|gerbil|mouse|rat)s?\b',
    ]

    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            entity = match.group(0)
            # Capitalize properly: "syrian hamster" → "Syrian hamster"
            return ' '.join(word.capitalize() if i == 0 else word
                          for i, word in enumerate(entity.split()))

    return None


def has_pronoun(query: str) -> bool:
    """
    Check if query contains pronouns that might need resolution.

    Args:
        query: User's query

    Returns:
        True if query contains pronouns
    """
    pronoun_patterns = [
        r'\bsome\b',
        r'\bthem\b',
        r'\bthose\b',
        r'\bit\b',
        r'\bthat\b',
        r'\bone\b',
    ]

    query_lower = query.lower()
    for pattern in pronoun_patterns:
        if re.search(pattern, query_lower):
            return True

    return False
