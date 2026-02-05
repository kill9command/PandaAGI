"""
Context Schema Versioning & Migration System

Manages schema evolution for LiveSessionContext with automatic migration
of older context files to the current schema version.

Schema History:
- v0: Original schema (no version field)
- v1: Added summarization fields (fact_summaries, action_summary, last_summarized_turn)
- v2: Added extraction metadata (extraction_confidence, extraction_method, entities)
- v3: Added cross-session learning (user_cluster, learning_feedback)
- v4: Added conversation history tracking (recent_turns) [2025-11-11]
- v5: Cleaned up noisy preference keys [2025-11-12]
- v6: Added code operations state (current_repo, code_state) [2025-11-13]
- v7: Added LLM turn summarizer support (last_turn_summary) [2025-11-26]

Author: Panda Team
Created: 2025-11-10
"""

from typing import Dict, Any, Callable
import json
import re

# Current schema version
CURRENT_SCHEMA_VERSION = 7


class ContextMigration:
    """Manages schema migrations for LiveSessionContext"""

    def __init__(self):
        # Registry of migration functions (version -> migration_function)
        self.migrations: Dict[int, Callable] = {
            1: self._migrate_v0_to_v1,
            2: self._migrate_v1_to_v2,
            3: self._migrate_v2_to_v3,
            4: self._migrate_v3_to_v4,
            5: self._migrate_v4_to_v5,
            6: self._migrate_v5_to_v6,
            7: self._migrate_v6_to_v7,
        }

    def migrate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Migrate context data to current schema version.

        Args:
            data: Context data dict (any version)

        Returns:
            Migrated data dict at CURRENT_SCHEMA_VERSION
        """
        current_version = data.get("schema_version", 0)

        if current_version == CURRENT_SCHEMA_VERSION:
            return data  # Already at current version

        if current_version > CURRENT_SCHEMA_VERSION:
            raise ValueError(
                f"Context schema version {current_version} is newer than "
                f"supported version {CURRENT_SCHEMA_VERSION}. Please upgrade."
            )

        # Apply migrations sequentially
        migrated = data.copy()
        for version in range(current_version + 1, CURRENT_SCHEMA_VERSION + 1):
            if version not in self.migrations:
                raise ValueError(f"No migration path for version {version}")

            print(f"[Migration] Migrating context from v{version-1} to v{version}")
            migrated = self.migrations[version](migrated)
            migrated["schema_version"] = version

        return migrated

    def _migrate_v0_to_v1(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        v0 → v1: Add summarization support

        Original schema (v0):
        - session_id, preferences, current_topic, recent_actions,
          discovered_facts, pending_tasks, turn_count, timestamps

        v1 adds:
        - schema_version (int)
        - fact_summaries (Dict[str, str]): Compressed fact summaries per domain
        - action_summary (Optional[str]): Compressed action history
        - last_summarized_turn (int): When last summarization occurred
        """
        migrated = data.copy()

        # Add new fields with defaults
        migrated.setdefault("schema_version", 1)
        migrated.setdefault("fact_summaries", {})
        migrated.setdefault("action_summary", None)
        migrated.setdefault("last_summarized_turn", 0)

        print(f"  ✓ Added summarization fields")
        return migrated

    def _migrate_v1_to_v2(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        v1 → v2: Add extraction metadata

        v2 adds:
        - extraction_confidence (Dict[str, float]): Confidence score per preference
        - extraction_method (Dict[str, str]): How each preference was extracted (regex/llm/learned)
        - entities (List[str]): Extracted entities from LLM
        """
        migrated = data.copy()

        # Add extraction metadata fields
        migrated.setdefault("extraction_confidence", {})
        migrated.setdefault("extraction_method", {})
        migrated.setdefault("entities", [])

        # Populate with defaults for existing preferences
        for pref_key in migrated.get("preferences", {}).keys():
            migrated["extraction_confidence"][pref_key] = 0.8  # Assume regex extraction
            migrated["extraction_method"][pref_key] = "regex"

        print(f"  ✓ Added extraction metadata for {len(migrated.get('preferences', {}))} preferences")
        return migrated

    def _migrate_v2_to_v3(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        v2 → v3: Add cross-session learning metadata

        v3 adds:
        - user_cluster (Optional[str]): User behavior cluster ID
        - learning_feedback (List[Dict]): User corrections and feedback
        """
        migrated = data.copy()

        migrated.setdefault("user_cluster", None)
        migrated.setdefault("learning_feedback", [])

        print(f"  ✓ Added cross-session learning fields")
        return migrated

    def _migrate_v3_to_v4(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        v3 → v4: Add conversation history tracking

        v4 adds:
        - recent_turns (List[Dict]): Recent conversation turns for pronoun resolution
        """
        migrated = data.copy()

        migrated.setdefault("recent_turns", [])

        print(f"  ✓ Added conversation history tracking (recent_turns)")
        return migrated

    def _migrate_v4_to_v5(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        v4 → v5: Clean up noisy preference keys.
        
        This migration addresses an issue where preferences were stored with noisy,
        descriptive keys instead of clean key-value pairs.
        
        Example: "User's Favorite Hamster - Syrian Hamster": ""
        Becomes: "favorite_hamster": "Syrian Hamster"
        """
        migrated = data.copy()
        
        if "preferences" not in migrated or not isinstance(migrated["preferences"], dict):
            return migrated
            
        original_prefs = migrated["preferences"]
        cleaned_prefs = {}
        cleaned_count = 0
        
        for key, value in original_prefs.items():
            # Rule for "User's Favorite Hamster"
            if "User's Favorite Hamster" in key:
                # Try to extract value from the key
                parts = key.split(" - ")
                if len(parts) > 1 and parts[1]:
                    cleaned_prefs["favorite_hamster"] = parts[1].strip()
                    cleaned_count += 1
                elif value: # If value is in the value field
                    cleaned_prefs["favorite_hamster"] = str(value).strip()
                    cleaned_count += 1
                continue

            # Rule for "User memory (memory):" prefix
            if key.startswith("User memory (memory):"):
                new_key = key.replace("User memory (memory):", "").strip()
                # Further clean the new key if possible
                if "Favorite Hamster" in new_key:
                    parts = new_key.split(" - ")
                    if len(parts) > 1 and parts[1]:
                         cleaned_prefs["favorite_hamster"] = parts[1].strip()
                         cleaned_count += 1
                    elif value:
                         cleaned_prefs["favorite_hamster"] = str(value).strip()
                         cleaned_count += 1
                else:
                    # A generic memory, clean it as best as possible
                    simple_key = new_key.lower().replace(" ", "_").replace("-", "_")
                    simple_key = re.sub(r'[^a-z0-9_]', '', simple_key)
                    if simple_key and value:
                        cleaned_prefs[simple_key] = str(value).strip()
                        cleaned_count += 1
                continue

            # If no rules match, keep the original preference
            cleaned_prefs[key] = value

        if cleaned_count > 0:
            migrated["preferences"] = cleaned_prefs
            print(f"  ✓ Cleaned up {cleaned_count} noisy preference keys.")

        return migrated

    def _migrate_v5_to_v6(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        v5 → v6: Add code operations state

        v6 adds:
        - current_repo (Optional[str]): Current repository path
        - code_state (Dict[str, Any]): Code operation state (branch, modified files, etc.)
        """
        migrated = data.copy()

        migrated.setdefault("current_repo", None)
        migrated.setdefault("code_state", {})

        print(f"  ✓ Added code operations state fields")
        return migrated

    def _migrate_v6_to_v7(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        v6 → v7: Add LLM turn summarizer support

        v7 adds:
        - last_turn_summary (Optional[Dict[str, Any]]): LLM-generated turn summary
          containing: short_summary, key_findings, preferences_learned, topic,
          satisfaction_estimate, next_turn_hints, tokens_used

        This field stores the output of /context.summarize_turn for injection
        into the next turn's context.
        """
        migrated = data.copy()

        migrated.setdefault("last_turn_summary", None)

        print(f"  ✓ Added LLM turn summarizer support (last_turn_summary)")
        return migrated

    def validate_schema(self, data: Dict[str, Any]) -> bool:
        """
        Validate that context matches current schema.

        Args:
            data: Context data dict

        Returns:
            True if valid, False otherwise
        """
        # Required fields for v3 schema
        required_fields_v3 = [
            # v0 core fields
            "session_id", "preferences", "current_topic",
            "recent_actions", "discovered_facts", "pending_tasks",
            "turn_count", "last_updated", "created_at",
            # v1 summarization fields
            "schema_version", "fact_summaries", "action_summary",
            "last_summarized_turn",
            # v2 extraction metadata
            "extraction_confidence", "extraction_method", "entities",
            # v3 learning fields
            "user_cluster", "learning_feedback"
        ]

        missing_fields = [field for field in required_fields_v3 if field not in data]

        if missing_fields:
            print(f"[Validation] Missing fields: {missing_fields}")
            return False

        # Validate schema_version
        if data.get("schema_version") != CURRENT_SCHEMA_VERSION:
            print(f"[Validation] Schema version mismatch: {data.get('schema_version')} != {CURRENT_SCHEMA_VERSION}")
            return False

        return True

    def get_schema_info(self, version: int = CURRENT_SCHEMA_VERSION) -> Dict[str, Any]:
        """
        Get information about a schema version.

        Args:
            version: Schema version to describe

        Returns:
            Dict with version info
        """
        schema_info = {
            0: {
                "version": 0,
                "description": "Original schema (no versioning)",
                "fields": [
                    "session_id", "preferences", "current_topic",
                    "recent_actions", "discovered_facts", "pending_tasks",
                    "turn_count", "last_updated", "created_at"
                ]
            },
            1: {
                "version": 1,
                "description": "Added summarization support",
                "added_fields": [
                    "schema_version", "fact_summaries",
                    "action_summary", "last_summarized_turn"
                ]
            },
            2: {
                "version": 2,
                "description": "Added extraction metadata",
                "added_fields": [
                    "extraction_confidence", "extraction_method", "entities"
                ]
            },
            3: {
                "version": 3,
                "description": "Added cross-session learning",
                "added_fields": [
                    "user_cluster", "learning_feedback"
                ]
            }
        }

        return schema_info.get(version, {"version": version, "description": "Unknown version"})


# Global migration manager instance
_migration_manager = ContextMigration()


def migrate_context(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Migrate context data to current schema version.

    Args:
        data: Context data dict (any version)

    Returns:
        Migrated data at current schema version
    """
    return _migration_manager.migrate(data)


def validate_context(data: Dict[str, Any]) -> bool:
    """
    Validate context against current schema.

    Args:
        data: Context data dict

    Returns:
        True if valid, False otherwise
    """
    return _migration_manager.validate_schema(data)


def get_current_schema_version() -> int:
    """Get the current schema version."""
    return CURRENT_SCHEMA_VERSION


def get_schema_info(version: int = CURRENT_SCHEMA_VERSION) -> Dict[str, Any]:
    """Get information about a schema version."""
    return _migration_manager.get_schema_info(version)
