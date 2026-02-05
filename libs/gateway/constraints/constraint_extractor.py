"""
Constraint Extractor - Extracts constraints from natural language queries.

Implements Phase 2.5 constraint extraction for the constraint pipeline:
1. Parse query for explicit constraints (file size, budget, etc.)
2. Normalize constraint values to standard units
3. Write constraints.json to turn directory

Architecture Reference:
- This is part of the vertical slice for constraint enforcement
- Constraints flow: Extraction (Phase 2.5) -> Enforcement (Phase 5) -> Validation (Phase 7)
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from libs.gateway.persistence.turn_manager import TurnDirectory

logger = logging.getLogger(__name__)


class ConstraintExtractor:
    """
    Extracts constraints from natural language queries.

    Currently supports:
    - File size constraints: "under 50KB", "less than 1MB", "max 100KB"

    Future extensions:
    - Budget constraints: "under $100", "max budget $50"
    - Time constraints: "within 5 minutes"
    - Location constraints: "files in /tmp only"
    """

    # Unit multipliers for converting to bytes
    UNIT_MULTIPLIERS = {
        'b': 1,
        'byte': 1,
        'bytes': 1,
        'kb': 1024,
        'kilobyte': 1024,
        'kilobytes': 1024,
        'mb': 1024 * 1024,
        'megabyte': 1024 * 1024,
        'megabytes': 1024 * 1024,
        'gb': 1024 * 1024 * 1024,
        'gigabyte': 1024 * 1024 * 1024,
        'gigabytes': 1024 * 1024 * 1024,
    }

    def extract_from_query(self, query: str, context: str = "") -> List[Dict[str, Any]]:
        """
        Extract constraints from a natural language query and gathered context.

        Args:
            query: The user's query string
            context: Optional gathered context (§1) that may contain
                     session preferences or prior-turn constraints

        Returns:
            List of constraint dictionaries with:
            - id: Unique identifier for the constraint
            - type: Constraint type (e.g., "file_size", "budget", "time")
            - max_bytes/max_amount/max_minutes: Constraint value
            - source: How the constraint was detected ("extracted" or "context")
            - original_text: The matched text from the query/context
        """
        constraints = []

        # Extract from query
        file_size_constraints = self._extract_file_size_constraints(query)
        constraints.extend(file_size_constraints)

        budget_constraints = self._extract_budget_constraints(query)
        constraints.extend(budget_constraints)

        time_constraints = self._extract_time_constraints(query)
        constraints.extend(time_constraints)

        # Also extract from gathered context (session preferences, prior turns)
        if context:
            ctx_file_size = self._extract_file_size_constraints(context)
            ctx_budget = self._extract_budget_constraints(context)
            ctx_time = self._extract_time_constraints(context)

            for c in ctx_file_size + ctx_budget + ctx_time:
                # Mark as context-sourced and avoid duplicates
                c["source"] = "context"
                if not self._is_duplicate(c, constraints):
                    constraints.append(c)

        return constraints

    def _is_duplicate(self, candidate: Dict[str, Any], existing: List[Dict[str, Any]]) -> bool:
        """Check if a constraint is a duplicate of an existing one."""
        ctype = candidate.get("type")
        for c in existing:
            if c.get("type") != ctype:
                continue
            if ctype == "file_size" and c.get("max_bytes") == candidate.get("max_bytes"):
                return True
            if ctype == "budget" and c.get("max_amount") == candidate.get("max_amount"):
                return True
            if ctype == "time" and c.get("max_minutes") == candidate.get("max_minutes"):
                return True
        return False

    def _extract_file_size_constraints(self, query: str) -> List[Dict[str, Any]]:
        """
        Extract file size constraints from query.

        Patterns matched:
        - "under 50KB"
        - "less than 1MB"
        - "max 100 bytes"
        - "maximum 500KB"
        - "at most 2MB"
        - "no more than 100KB"
        - "output must be under 50KB"
        - "file size limit 1MB"
        """
        constraints = []

        # Pattern: "under/less than/max/maximum/at most X KB/MB/bytes"
        size_patterns = [
            # "under 50KB", "less than 1MB"
            r'(?:under|less\s+than)\s+(\d+(?:\.\d+)?)\s*(KB|MB|GB|bytes?|kilobytes?|megabytes?|gigabytes?)',
            # "max 100KB", "maximum 500KB"
            r'(?:max(?:imum)?)\s+(\d+(?:\.\d+)?)\s*(KB|MB|GB|bytes?|kilobytes?|megabytes?|gigabytes?)',
            # "at most 2MB"
            r'at\s+most\s+(\d+(?:\.\d+)?)\s*(KB|MB|GB|bytes?|kilobytes?|megabytes?|gigabytes?)',
            # "no more than 100KB"
            r'no\s+more\s+than\s+(\d+(?:\.\d+)?)\s*(KB|MB|GB|bytes?|kilobytes?|megabytes?|gigabytes?)',
            # "file size limit 1MB", "size limit of 500KB"
            r'(?:file\s+)?size\s+limit(?:\s+of)?\s+(\d+(?:\.\d+)?)\s*(KB|MB|GB|bytes?|kilobytes?|megabytes?|gigabytes?)',
            # "must be under 50KB"
            r'must\s+be\s+under\s+(\d+(?:\.\d+)?)\s*(KB|MB|GB|bytes?|kilobytes?|megabytes?|gigabytes?)',
        ]

        for pattern in size_patterns:
            matches = re.finditer(pattern, query, re.IGNORECASE)

            for match in matches:
                value_str, unit = match.groups()
                value = float(value_str)
                bytes_value = self._to_bytes(value, unit)

                constraint = {
                    "id": f"file_size_{len(constraints) + 1}",
                    "type": "file_size",
                    "max_bytes": bytes_value,
                    "source": "extracted",
                    "original_text": match.group(0),
                    "original_value": value,
                    "original_unit": unit.upper(),
                }

                # Avoid duplicates (same max_bytes)
                if not any(c["max_bytes"] == bytes_value for c in constraints):
                    constraints.append(constraint)
                    logger.info(
                        f"[ConstraintExtractor] Extracted file size constraint: "
                        f"{value} {unit} = {bytes_value} bytes"
                    )

        return constraints

    def _extract_budget_constraints(self, query: str) -> List[Dict[str, Any]]:
        """
        Extract budget constraints from query.

        Patterns matched:
        - "under $100"
        - "budget of $500"
        - "max budget $200"
        - "spend less than $50"
        - "no more than $1000"
        """
        constraints = []

        budget_patterns = [
            # "under $100", "less than $50"
            r'(?:under|less\s+than)\s+\$(\d+(?:,\d{3})*(?:\.\d{2})?)',
            # "budget of $500", "budget $200"
            r'budget(?:\s+of)?\s+\$(\d+(?:,\d{3})*(?:\.\d{2})?)',
            # "max budget $200", "maximum budget $500"
            r'(?:max(?:imum)?)\s+(?:budget\s+)?\$(\d+(?:,\d{3})*(?:\.\d{2})?)',
            # "spend less than $50", "spend under $100"
            r'spend\s+(?:less\s+than|under)\s+\$(\d+(?:,\d{3})*(?:\.\d{2})?)',
            # "no more than $1000"
            r'no\s+more\s+than\s+\$(\d+(?:,\d{3})*(?:\.\d{2})?)',
            # "$500 budget", "$200 max"
            r'\$(\d+(?:,\d{3})*(?:\.\d{2})?)\s+(?:budget|max(?:imum)?)',
            # "within $100"
            r'within\s+\$(\d+(?:,\d{3})*(?:\.\d{2})?)',
        ]

        for pattern in budget_patterns:
            matches = re.finditer(pattern, query, re.IGNORECASE)

            for match in matches:
                value_str = match.group(1).replace(',', '')
                value = float(value_str)

                constraint = {
                    "id": f"budget_{len(constraints) + 1}",
                    "type": "budget",
                    "max_amount": value,
                    "currency": "USD",
                    "source": "extracted",
                    "original_text": match.group(0),
                }

                # Avoid duplicates
                if not any(c.get("max_amount") == value for c in constraints):
                    constraints.append(constraint)
                    logger.info(
                        f"[ConstraintExtractor] Extracted budget constraint: ${value}"
                    )

        return constraints

    def _extract_time_constraints(self, query: str) -> List[Dict[str, Any]]:
        """
        Extract time constraints from query.

        Patterns matched:
        - "within 2 hours"
        - "under 30 minutes"
        - "max 1 hour"
        - "no more than 45 minutes"
        - "less than 3 hours"
        """
        constraints = []

        time_patterns = [
            # "within 2 hours", "within 30 minutes"
            (r'within\s+(\d+(?:\.\d+)?)\s*(hour|hr|minute|min)s?', 1),
            # "under 30 minutes", "less than 2 hours"
            (r'(?:under|less\s+than)\s+(\d+(?:\.\d+)?)\s*(hour|hr|minute|min)s?', 1),
            # "max 1 hour", "maximum 45 minutes"
            (r'(?:max(?:imum)?)\s+(\d+(?:\.\d+)?)\s*(hour|hr|minute|min)s?', 1),
            # "no more than 45 minutes"
            (r'no\s+more\s+than\s+(\d+(?:\.\d+)?)\s*(hour|hr|minute|min)s?', 1),
            # "2 hour limit", "30 minute limit"
            (r'(\d+(?:\.\d+)?)\s*(hour|hr|minute|min)s?\s+limit', 1),
        ]

        for pattern, _ in time_patterns:
            matches = re.finditer(pattern, query, re.IGNORECASE)

            for match in matches:
                value = float(match.group(1))
                unit = match.group(2).lower()

                # Convert to minutes
                if unit in ('hour', 'hr'):
                    minutes = value * 60
                else:
                    minutes = value

                constraint = {
                    "id": f"time_{len(constraints) + 1}",
                    "type": "time",
                    "max_minutes": minutes,
                    "source": "extracted",
                    "original_text": match.group(0),
                    "original_value": value,
                    "original_unit": unit,
                }

                # Avoid duplicates
                if not any(c.get("max_minutes") == minutes for c in constraints):
                    constraints.append(constraint)
                    logger.info(
                        f"[ConstraintExtractor] Extracted time constraint: {minutes} minutes"
                    )

        return constraints

    def _to_bytes(self, value: float, unit: str) -> int:
        """
        Convert a size value to bytes.

        Args:
            value: Numeric value
            unit: Unit string (KB, MB, bytes, etc.)

        Returns:
            Size in bytes (integer)
        """
        unit_lower = unit.lower()
        multiplier = self.UNIT_MULTIPLIERS.get(unit_lower, 1)
        return int(value * multiplier)

    def write_constraints(
        self,
        turn_dir: "TurnDirectory",
        constraints: List[Dict[str, Any]],
        query: str
    ) -> Path:
        """
        Write constraints.json to turn directory.

        Args:
            turn_dir: Turn directory to write to
            constraints: List of extracted constraints
            query: Original query (for reference)

        Returns:
            Path to the written constraints.json file
        """
        constraints_path = turn_dir.path / "constraints.json"

        payload = {
            "constraints": constraints,
            "query": query,
            "extraction_source": "constraint_extractor",
        }

        constraints_path.write_text(json.dumps(payload, indent=2))
        logger.info(
            f"[ConstraintExtractor] Wrote {len(constraints)} constraints to "
            f"{constraints_path}"
        )

        return constraints_path


# Module-level singleton
_extractor: Optional[ConstraintExtractor] = None


def get_constraint_extractor() -> ConstraintExtractor:
    """Get or create the singleton ConstraintExtractor instance."""
    global _extractor
    if _extractor is None:
        _extractor = ConstraintExtractor()
    return _extractor


def extract_constraints_from_query(query: str, context: str = "") -> List[Dict[str, Any]]:
    """Convenience function to extract constraints from a query and context."""
    return get_constraint_extractor().extract_from_query(query, context=context)
