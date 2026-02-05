"""
orchestrator/shared_state/context_fingerprint.py

Unified context fingerprinting for all cache layers.
Centralizes session_id + normalized preferences logic to prevent fingerprint mismatches.
"""
import hashlib
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass


@dataclass
class FingerprintResult:
    """Result of fingerprint computation with versioning."""
    primary: str  # Current version hash
    legacy: Optional[str]  # Backward compatibility hash
    version: str  # Fingerprint algorithm version
    components: Dict[str, Any]  # Components used in hash


class ContextFingerprint:
    """
    Unified fingerprinting for cache keys across all cache layers.

    Features:
    - Consistent normalization of session context
    - Version-aware hashing for backward compatibility
    - Excludes volatile fields (timestamps, metadata)
    - Supports both v1 (legacy) and v2 (current) algorithms
    """

    # Fields to exclude from fingerprinting (volatile/non-semantic)
    VOLATILE_FIELDS = {
        "created_at", "updated_at", "last_access", "metadata",
        "session_start_time", "turn_count", "cache_hits"
    }

    # Preference fields that should be normalized
    PREFERENCE_FIELDS = {
        "preferred_vendors", "budget_constraints", "excluded_brands",
        "quality_threshold", "delivery_timeframe", "user_preferences"
    }

    def __init__(self, version: str = "v2"):
        """
        Initialize fingerprint generator.

        Args:
            version: Fingerprint algorithm version ("v1" or "v2")
        """
        self.version = version

    def compute(
        self,
        session_id: str,
        context: Optional[Dict[str, Any]] = None,
        query: Optional[str] = None,
        intent: Optional[str] = None,  # NEW: Quality Agent requirement
        include_legacy: bool = True
    ) -> FingerprintResult:
        """
        Compute context fingerprint with optional legacy fallback.

        Args:
            session_id: Session identifier
            context: Session context dict (preferences, facts, etc.)
            query: Optional query string to include in fingerprint
            intent: Optional intent type (transactional, informational, navigational)
                   Quality Agent Requirement: Include to prevent cross-intent cache pollution
            include_legacy: Whether to compute legacy v1 hash for backward compatibility

        Returns:
            FingerprintResult with primary hash and optional legacy hash

        Quality Agent Note: Including intent prevents cache hits where intent differs
        (e.g., transactional query returning informational cache).
        """
        # Normalize context
        normalized = self._normalize_context(context or {})

        # Build components (EXCLUDING preferences to prevent cache misses on preference updates)
        components = {
            "session_id": session_id,
            # NOTE: Preferences excluded - preference changes shouldn't invalidate cached research
            # "preferences": normalized.get("preferences", {}),  # REMOVED
            "query": query or "",
            "intent": intent or "unknown"  # NEW: Include intent in fingerprint
        }

        # Compute primary hash (v2)
        primary = self._compute_v2(components)

        # Compute legacy hash if requested (without intent for backward compatibility)
        legacy = None
        if include_legacy and self.version == "v2":
            legacy = self._compute_v1(session_id, context, query)

        return FingerprintResult(
            primary=primary,
            legacy=legacy,
            version=self.version,
            components=components
        )

    def _normalize_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize context by removing volatile fields and sorting keys.

        Args:
            context: Raw session context

        Returns:
            Normalized context suitable for fingerprinting
        """
        normalized = {}

        for key, value in context.items():
            # Skip volatile fields
            if key in self.VOLATILE_FIELDS:
                continue

            # Normalize preference dicts
            if key in self.PREFERENCE_FIELDS and isinstance(value, dict):
                normalized[key] = self._normalize_dict(value)
            elif key in self.PREFERENCE_FIELDS and isinstance(value, list):
                normalized[key] = sorted(value) if all(isinstance(x, str) for x in value) else value
            else:
                normalized[key] = value

        return normalized

    def _normalize_dict(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively normalize dict by sorting keys."""
        result = {}
        for key in sorted(d.keys()):
            value = d[key]
            if isinstance(value, dict):
                result[key] = self._normalize_dict(value)
            elif isinstance(value, list):
                result[key] = sorted(value) if all(isinstance(x, str) for x in value) else value
            else:
                result[key] = value
        return result

    def _compute_v2(self, components: Dict[str, Any]) -> str:
        """
        Compute v2 fingerprint hash.

        V2 improvements:
        - Strict JSON serialization with sorted keys
        - Excludes all volatile fields
        - Normalized preference handling

        Args:
            components: Normalized components dict

        Returns:
            SHA256 hash hex string (first 16 chars)
        """
        # Create stable JSON representation
        stable_json = json.dumps(components, sort_keys=True, separators=(',', ':'))

        # Hash and truncate
        hash_obj = hashlib.sha256(stable_json.encode('utf-8'))
        return hash_obj.hexdigest()[:16]

    def _compute_v1(
        self,
        session_id: str,
        context: Optional[Dict[str, Any]],
        query: Optional[str]
    ) -> str:
        """
        Compute legacy v1 fingerprint for backward compatibility.

        This matches the original response_cache fingerprint logic.

        Args:
            session_id: Session identifier
            context: Raw session context
            query: Query string

        Returns:
            SHA256 hash hex string (first 16 chars)
        """
        # Legacy logic from response_cache
        components = {
            "session": session_id,
            "prefs": context.get("preferences", {}) if context else {},
            "q": query or ""
        }

        # Less strict serialization (matches old behavior)
        legacy_json = json.dumps(components, sort_keys=True)
        hash_obj = hashlib.sha256(legacy_json.encode('utf-8'))
        return hash_obj.hexdigest()[:16]

    def verify(self, fingerprint: str, **kwargs) -> bool:
        """
        Verify if a fingerprint matches the given parameters.

        Args:
            fingerprint: Fingerprint to verify
            **kwargs: Parameters to compute fingerprint from

        Returns:
            True if fingerprint matches
        """
        result = self.compute(**kwargs)
        return fingerprint == result.primary or fingerprint == result.legacy


# Global instance for convenience
fingerprint = ContextFingerprint(version="v2")


def compute_fingerprint(
    session_id: str,
    context: Optional[Dict[str, Any]] = None,
    query: Optional[str] = None,
    intent: Optional[str] = None,  # NEW: Quality Agent requirement
    include_legacy: bool = True
) -> FingerprintResult:
    """
    Convenience function to compute context fingerprint.

    Args:
        session_id: Session identifier
        context: Session context dict
        query: Optional query string
        intent: Optional intent type (transactional, informational, navigational)
        include_legacy: Whether to include legacy v1 hash

    Returns:
        FingerprintResult with hashes

    Quality Agent Requirement: Include intent to prevent cross-intent cache pollution.
    """
    return fingerprint.compute(session_id, context, query, intent, include_legacy)
