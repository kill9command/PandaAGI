"""
Forgiving Parser - Semantic fallback parsing for LLM outputs.

Design principle: Try structured first, fall back gracefully,
never fail hard on parse errors. This allows LLMs to focus on
thinking rather than formatting.

Usage:
    parser = ForgivingParser()
    data, warnings = parser.parse(raw_output, expected_schema)
"""

import json
import re
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    """Result of a parse attempt."""
    data: Dict[str, Any]
    success: bool
    strategy_used: str
    warnings: List[str] = field(default_factory=list)


class ForgivingParser:
    """
    Semantic fallback parsing for LLM outputs.

    Strategies (in order):
    1. Direct JSON parse
    2. JSON repair (trailing commas, quotes, etc.)
    3. Semantic extraction (regex/keyword patterns)
    4. Sensible defaults
    """

    def parse(
        self,
        raw_output: str,
        expected_schema: Optional[Dict[str, Any]] = None,
    ) -> ParseResult:
        """
        Parse LLM output with multiple fallback strategies.

        Args:
            raw_output: Raw text from LLM
            expected_schema: Optional schema with field types and defaults

        Returns:
            ParseResult with data, success flag, strategy used, and warnings
        """
        warnings = []
        schema = expected_schema or {}

        # Strategy 1: Direct JSON parse
        try:
            data = self._extract_json(raw_output)
            if data is not None:
                validated = self._validate_and_default(data, schema)
                return ParseResult(
                    data=validated,
                    success=True,
                    strategy_used="json_direct",
                    warnings=warnings
                )
        except json.JSONDecodeError as e:
            warnings.append(f"JSON parse failed: {e}")

        # Strategy 2: JSON repair
        try:
            repaired = self._repair_json(raw_output)
            data = self._extract_json(repaired)
            if data is not None:
                warnings.append("JSON required repair")
                validated = self._validate_and_default(data, schema)
                return ParseResult(
                    data=validated,
                    success=True,
                    strategy_used="json_repaired",
                    warnings=warnings
                )
        except Exception as e:
            warnings.append(f"JSON repair failed: {e}")

        # Strategy 3: Semantic extraction
        try:
            data = self._semantic_extract(raw_output, schema)
            if data:
                warnings.append("Used semantic extraction")
                return ParseResult(
                    data=data,
                    success=True,
                    strategy_used="semantic",
                    warnings=warnings
                )
        except Exception as e:
            warnings.append(f"Semantic extraction failed: {e}")

        # Strategy 4: Return sensible defaults
        warnings.append("Using all defaults")
        defaults = self._get_defaults(schema)
        return ParseResult(
            data=defaults,
            success=False,
            strategy_used="defaults",
            warnings=warnings
        )

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from text, handling code blocks and mixed content."""
        text = text.strip()

        # Strip markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            text = "\n".join(lines).strip()

        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Find JSON object boundaries
        start = text.find("{")
        end = text.rfind("}") + 1

        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

        # Try array
        start = text.find("[")
        end = text.rfind("]") + 1

        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

        return None

    def _repair_json(self, text: str) -> str:
        """Apply common JSON repairs."""
        repaired = text

        # Strip markdown code blocks
        if "```" in repaired:
            lines = repaired.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            repaired = "\n".join(lines)

        # Fix trailing commas before closing brackets
        repaired = re.sub(r',(\s*[}\]])', r'\1', repaired)

        # Fix single quotes to double quotes (careful with apostrophes)
        # Only replace single quotes that look like JSON delimiters
        repaired = re.sub(r"'(\w+)'(\s*:)", r'"\1"\2', repaired)  # Keys
        repaired = re.sub(r":\s*'([^']*)'", r': "\1"', repaired)   # String values

        # Fix unquoted keys
        repaired = re.sub(r'{\s*([a-zA-Z_]\w*)\s*:', r'{"\1":', repaired)
        repaired = re.sub(r',\s*([a-zA-Z_]\w*)\s*:', r', "\1":', repaired)

        # Fix JavaScript-style comments
        repaired = re.sub(r'//[^\n]*\n', '\n', repaired)
        repaired = re.sub(r'/\*.*?\*/', '', repaired, flags=re.DOTALL)

        # Fix Python-style True/False/None
        repaired = re.sub(r'\bTrue\b', 'true', repaired)
        repaired = re.sub(r'\bFalse\b', 'false', repaired)
        repaired = re.sub(r'\bNone\b', 'null', repaired)

        return repaired

    def _semantic_extract(
        self,
        text: str,
        schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract fields semantically from text using patterns."""
        result = {}
        text_lower = text.lower()

        for field, spec in schema.items():
            field_type = spec.get("type", "string") if isinstance(spec, dict) else "string"
            default = spec.get("default") if isinstance(spec, dict) else None

            # Try to find field mentioned in text
            patterns = [
                rf'{field}[:\s]+["\']?([^"\'\n,}}]+)["\']?',
                rf'"{field}"[:\s]+["\']?([^"\'\n,}}]+)["\']?',
                rf'{field.replace("_", " ")}[:\s]+([^\n,}}]+)',
            ]

            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    value = match.group(1).strip().strip('"\'')
                    result[field] = self._coerce_type(value, field_type)
                    break
            else:
                # No match - use default
                if default is not None:
                    result[field] = default

        return result

    def _validate_and_default(
        self,
        data: Dict[str, Any],
        schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate data against schema, applying defaults for missing fields."""
        if not schema:
            return data

        result = dict(data)  # Copy existing data

        for field, spec in schema.items():
            if isinstance(spec, dict):
                required = spec.get("required", False)
                default = spec.get("default")
                field_type = spec.get("type", "string")
            else:
                required = False
                default = spec
                field_type = "string"

            if field not in result:
                if default is not None:
                    result[field] = default
                elif required:
                    result[field] = self._get_type_default(field_type)

        return result

    def _get_defaults(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Get all defaults from schema."""
        result = {}

        for field, spec in schema.items():
            if isinstance(spec, dict):
                default = spec.get("default")
                field_type = spec.get("type", "string")
            else:
                default = spec
                field_type = "string"

            if default is not None:
                result[field] = default
            else:
                result[field] = self._get_type_default(field_type)

        return result

    def _get_type_default(self, field_type: str) -> Any:
        """Get sensible default for a type."""
        type_defaults = {
            "string": "",
            "int": 0,
            "integer": 0,
            "float": 0.0,
            "number": 0.0,
            "bool": False,
            "boolean": False,
            "array": [],
            "list": [],
            "object": {},
            "dict": {},
        }
        return type_defaults.get(field_type.lower(), None)

    def _coerce_type(self, value: str, target_type: str) -> Any:
        """Coerce a string value to target type."""
        if not isinstance(value, str):
            return value

        target_type = target_type.lower()
        value = value.strip()

        try:
            if target_type in ("int", "integer"):
                # Handle numeric strings with commas
                return int(value.replace(",", ""))
            elif target_type in ("float", "number"):
                return float(value.replace(",", ""))
            elif target_type in ("bool", "boolean"):
                return value.lower() in ("true", "yes", "1", "on")
            elif target_type in ("array", "list"):
                if value.startswith("["):
                    return json.loads(value)
                return [v.strip() for v in value.split(",")]
            elif target_type in ("object", "dict"):
                if value.startswith("{"):
                    return json.loads(value)
                return {}
            else:
                return value
        except (ValueError, json.JSONDecodeError):
            return value

    def evaluate_criterion(
        self,
        criterion: str,
        context: Dict[str, Any]
    ) -> bool:
        """
        Evaluate a success criterion expression.

        Supports:
        - "field is not empty"
        - "field > value"
        - "field == value"
        - "field.subfield exists"
        - "A OR B"
        - "A AND B"
        """
        criterion = criterion.strip()

        # Handle OR
        if " OR " in criterion:
            parts = criterion.split(" OR ")
            return any(self.evaluate_criterion(p.strip(), context) for p in parts)

        # Handle AND
        if " AND " in criterion:
            parts = criterion.split(" AND ")
            return all(self.evaluate_criterion(p.strip(), context) for p in parts)

        # Parse expressions
        if " is not empty" in criterion:
            field = criterion.replace(" is not empty", "").strip()
            value = self._get_nested(context, field)
            if value is None:
                return False
            if isinstance(value, (list, dict)):
                return len(value) > 0
            if isinstance(value, str):
                return len(value.strip()) > 0
            return bool(value)

        if " is empty" in criterion:
            field = criterion.replace(" is empty", "").strip()
            value = self._get_nested(context, field)
            if value is None:
                return True
            if isinstance(value, (list, dict, str)):
                return len(value) == 0
            return not bool(value)

        if " exists" in criterion:
            field = criterion.replace(" exists", "").strip()
            return self._get_nested(context, field) is not None

        # Comparison operators
        for op in [" >= ", " <= ", " > ", " < ", " == ", " != "]:
            if op in criterion:
                left, right = criterion.split(op, 1)
                left_val = self._get_nested(context, left.strip())
                right_val = self._parse_value(right.strip())
                return self._compare(left_val, op.strip(), right_val)

        # Default: treat as boolean field
        return bool(self._get_nested(context, criterion))

    def _get_nested(self, obj: Dict[str, Any], path: str) -> Any:
        """Get nested value using dot notation."""
        parts = path.split(".")
        current = obj

        for part in parts:
            if current is None:
                return None

            # Handle array indexing
            if "[" in part:
                key, idx_str = part.split("[", 1)
                idx = int(idx_str.rstrip("]"))
                if key:
                    current = current.get(key) if isinstance(current, dict) else None
                if isinstance(current, list) and 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return None
            elif isinstance(current, dict):
                current = current.get(part)
            else:
                return None

        return current

    def _parse_value(self, value: str) -> Any:
        """Parse a value from criterion expression."""
        value = value.strip().strip('"\'')

        # Try numeric
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            pass

        # Boolean
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False

        return value

    def _compare(self, left: Any, op: str, right: Any) -> bool:
        """Compare two values with an operator."""
        if left is None:
            return False

        try:
            if op == ">":
                return left > right
            elif op == ">=":
                return left >= right
            elif op == "<":
                return left < right
            elif op == "<=":
                return left <= right
            elif op == "==":
                return left == right
            elif op == "!=":
                return left != right
        except TypeError:
            return False

        return False


# Phase-specific parsing helpers

def parse_phase0_output(raw: str) -> ParseResult:
    """Parse Phase 0 (Query Analyzer) output."""
    schema = {
        "action_needed": {"type": "string", "default": "live_search"},
        "intent": {"type": "string", "default": "informational"},
        "mode": {"type": "string", "default": "chat"},
        "resolved_query": {"type": "string", "default": ""},
    }
    parser = ForgivingParser()
    return parser.parse(raw, schema)


def parse_phase1_output(raw: str) -> ParseResult:
    """Parse Phase 1 (Reflection) output."""
    schema = {
        "decision": {"type": "string", "default": "PROCEED"},
        "reasoning": {"type": "string", "default": ""},
    }
    parser = ForgivingParser()
    result = parser.parse(raw, schema)

    # Semantic fallback for decision
    if not result.data.get("decision"):
        raw_upper = raw.upper()
        if "CLARIFY" in raw_upper:
            result.data["decision"] = "CLARIFY"
        else:
            result.data["decision"] = "PROCEED"

    return result


def parse_phase3_output(raw: str) -> ParseResult:
    """Parse Phase 3 (Planner) output."""
    schema = {
        "route_to": {"type": "string", "default": "executor"},
        "goals": {"type": "array", "default": []},
        "approach": {"type": "string", "default": ""},
    }
    parser = ForgivingParser()
    result = parser.parse(raw, schema)

    # Semantic fallback for route
    if not result.data.get("route_to"):
        raw_lower = raw.lower()
        if "synthesis" in raw_lower or "direct" in raw_lower:
            result.data["route_to"] = "synthesis"
        else:
            result.data["route_to"] = "executor"

    return result


def parse_phase4_output(raw: str) -> ParseResult:
    """Parse Phase 4 (Executor) output."""
    schema = {
        "action": {"type": "string", "default": "COMPLETE"},
        "command": {"type": "string", "default": ""},
        "reasoning": {"type": "string", "default": ""},
    }
    parser = ForgivingParser()
    result = parser.parse(raw, schema)

    # Semantic fallback for action
    if not result.data.get("action"):
        raw_upper = raw.upper()
        if "EXECUTE" in raw_upper or "COMMAND" in raw_upper:
            result.data["action"] = "EXECUTE"
        elif "ANALYZE" in raw_upper:
            result.data["action"] = "ANALYZE"
        elif "BLOCKED" in raw_upper:
            result.data["action"] = "BLOCKED"
        else:
            result.data["action"] = "COMPLETE"

    return result


def parse_phase6_output(raw: str) -> ParseResult:
    """Parse Phase 6 (Validation) output."""
    schema = {
        "decision": {"type": "string", "default": "APPROVE"},
        "feedback": {"type": "string", "default": ""},
        "issues": {"type": "array", "default": []},
    }
    parser = ForgivingParser()
    result = parser.parse(raw, schema)

    # Semantic fallback for decision
    if not result.data.get("decision"):
        raw_upper = raw.upper()
        if "RETRY" in raw_upper:
            result.data["decision"] = "RETRY"
        elif "REVISE" in raw_upper:
            result.data["decision"] = "REVISE"
        elif "FAIL" in raw_upper:
            result.data["decision"] = "FAIL"
        else:
            result.data["decision"] = "APPROVE"

    return result
