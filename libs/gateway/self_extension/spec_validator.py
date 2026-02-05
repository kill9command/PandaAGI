"""
Tool Spec Validator - Validates tool specifications before creation.

Architecture Reference:
- architecture/concepts/TOOL_SYSTEM.md
- architecture/concepts/SELF_BUILDING_SYSTEM.md

Required fields: name, entrypoint, inputs, outputs
Optional fields: version, description, mode_required, dependencies, constraints, tests
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ValidationError:
    """Represents a validation error."""
    field: str
    message: str
    severity: str = "error"  # "error" or "warning"


@dataclass
class ValidationResult:
    """Result of spec validation."""
    valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)
    parsed_spec: Optional[Dict[str, Any]] = None

    def add_error(self, field: str, message: str):
        self.errors.append(ValidationError(field, message, "error"))
        self.valid = False

    def add_warning(self, field: str, message: str):
        self.warnings.append(ValidationError(field, message, "warning"))


class ToolSpecValidator:
    """
    Validates tool specifications.

    Checks:
    - Required fields present (name, entrypoint, inputs, outputs)
    - Valid mode_required value (code, chat, or null)
    - Valid input/output schema
    - Valid Python identifier for entrypoint
    """

    REQUIRED_FIELDS = ["name", "entrypoint", "inputs", "outputs"]
    VALID_MODES = ["code", "chat", None, "null", ""]
    VALID_INPUT_TYPES = ["string", "int", "float", "bool", "list", "dict", "any"]

    def validate_spec_content(self, spec_content: str) -> ValidationResult:
        """
        Validate a tool spec from markdown content with YAML frontmatter.

        Args:
            spec_content: Markdown content with YAML frontmatter

        Returns:
            ValidationResult with errors/warnings
        """
        result = ValidationResult(valid=True)

        # Parse YAML frontmatter
        parsed = self._parse_frontmatter(spec_content)
        if parsed is None:
            result.add_error("format", "Could not parse YAML frontmatter. Expected '---' delimiters.")
            return result

        result.parsed_spec = parsed
        return self.validate_spec_dict(parsed, result)

    def validate_spec_dict(
        self,
        spec: Dict[str, Any],
        result: Optional[ValidationResult] = None
    ) -> ValidationResult:
        """
        Validate a parsed tool spec dictionary.

        Args:
            spec: Parsed spec dictionary
            result: Existing result to append to (optional)

        Returns:
            ValidationResult with errors/warnings
        """
        if result is None:
            result = ValidationResult(valid=True, parsed_spec=spec)

        # Check required fields
        for field in self.REQUIRED_FIELDS:
            if field not in spec or spec[field] is None:
                result.add_error(field, f"Required field '{field}' is missing")

        if not result.valid:
            return result  # Stop early if required fields missing

        # Validate name format (tool.name or just name)
        name = spec.get("name", "")
        if not self._is_valid_tool_name(name):
            result.add_error("name", f"Invalid tool name '{name}'. Use format 'category.action' or valid identifier.")

        # Validate entrypoint is valid Python identifier
        entrypoint = spec.get("entrypoint", "")
        if not self._is_valid_identifier(entrypoint):
            result.add_error("entrypoint", f"Invalid entrypoint '{entrypoint}'. Must be valid Python identifier.")

        # Validate mode_required
        mode = spec.get("mode_required")
        if mode is not None and mode not in self.VALID_MODES:
            result.add_error("mode_required", f"Invalid mode_required '{mode}'. Must be 'code', 'chat', or null.")

        # Validate inputs schema
        inputs = spec.get("inputs", [])
        if not isinstance(inputs, list):
            result.add_error("inputs", "Inputs must be a list of input definitions")
        else:
            for i, inp in enumerate(inputs):
                self._validate_input_output(inp, f"inputs[{i}]", result)

        # Validate outputs schema
        outputs = spec.get("outputs", [])
        if not isinstance(outputs, list):
            result.add_error("outputs", "Outputs must be a list of output definitions")
        else:
            for i, out in enumerate(outputs):
                self._validate_input_output(out, f"outputs[{i}]", result)

        # Optional: validate version format
        version = spec.get("version")
        if version is not None and not self._is_valid_version(str(version)):
            result.add_warning("version", f"Version '{version}' doesn't follow semver format")

        # Optional: validate dependencies
        deps = spec.get("dependencies", [])
        if deps and not isinstance(deps, list):
            result.add_warning("dependencies", "Dependencies should be a list of package names")

        return result

    def _parse_frontmatter(self, content: str) -> Optional[Dict[str, Any]]:
        """Parse YAML frontmatter from markdown content."""
        content = content.strip()

        if not content.startswith("---"):
            return None

        # Find end of frontmatter
        end_match = re.search(r'\n---\s*\n', content[3:])
        if not end_match:
            # Try just '---' at end
            end_match = re.search(r'\n---\s*$', content[3:])
            if not end_match:
                return None

        yaml_content = content[3:end_match.start() + 3]

        try:
            return yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            logger.warning(f"[SpecValidator] YAML parse error: {e}")
            return None

    def _is_valid_tool_name(self, name: str) -> bool:
        """Check if tool name is valid (category.action or identifier)."""
        if not name:
            return False
        # Allow dotted names like "spreadsheet.read"
        parts = name.split(".")
        return all(self._is_valid_identifier(p) for p in parts)

    def _is_valid_identifier(self, name: str) -> bool:
        """Check if name is a valid Python identifier."""
        if not name:
            return False
        return name.isidentifier() or re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name) is not None

    def _is_valid_version(self, version: str) -> bool:
        """Check if version follows semver-ish format."""
        return bool(re.match(r'^\d+(\.\d+)*(-\w+)?$', version))

    def _validate_input_output(self, item: Any, path: str, result: ValidationResult):
        """Validate a single input/output definition."""
        if isinstance(item, str):
            # Simple string format: "param_name"
            if not self._is_valid_identifier(item):
                result.add_error(path, f"Invalid parameter name '{item}'")
            return

        if not isinstance(item, dict):
            result.add_error(path, f"Must be string or dict, got {type(item).__name__}")
            return

        # Dict format: {name: ..., type: ..., required: ...}
        name = item.get("name")
        if not name:
            result.add_error(path, "Missing 'name' field")
        elif not self._is_valid_identifier(name):
            result.add_error(path, f"Invalid parameter name '{name}'")

        param_type = item.get("type")
        if param_type and param_type not in self.VALID_INPUT_TYPES:
            result.add_warning(f"{path}.type", f"Unknown type '{param_type}'")


# Module-level singleton
_validator: Optional[ToolSpecValidator] = None


def get_spec_validator() -> ToolSpecValidator:
    """Get or create the singleton validator."""
    global _validator
    if _validator is None:
        _validator = ToolSpecValidator()
    return _validator


def validate_tool_spec(spec_content: str) -> ValidationResult:
    """Convenience function to validate a tool spec."""
    return get_spec_validator().validate_spec_content(spec_content)
