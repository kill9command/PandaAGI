"""
Skill Generator MCP - Creates new skills and MCP tools.

This MCP tool implements Pandora's self-extension capability. It generates
skills (SKILL.md + supporting files) from specifications provided by the LLM.

The generation process:
1. Validate the skill specification
2. Apply templates to generate files
3. Write files (requires approval via tool_approval hooks)
4. Register with SkillRegistry for immediate use

Usage:
    mcp = get_skill_generator_mcp()

    # Generate a skill
    result = await mcp.generate_skill(
        name="code-review",
        description="Review code for bugs, style, and best practices",
        instructions="## When to Use\\n...",
    )

    # Validate a skill
    result = await mcp.validate_skill("/path/to/skill")
"""

import logging
import re
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

# Paths
SKILLS_BASE_DIR = Path("panda_system_docs/skills")
GENERATED_SKILLS_DIR = SKILLS_BASE_DIR / "generated"
TEMPLATES_DIR = SKILLS_BASE_DIR / "core/skill-builder/templates"

# Validation constraints (from Agent Skills spec)
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
NAME_PATTERN = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')


@dataclass
class SkillSpec:
    """Specification for a skill to generate."""
    name: str
    description: str
    instructions: str

    # Optional
    author: str = "pandora-generated"
    version: str = "1.0"
    source: str = ""  # URL or concept the skill was derived from
    license: str = ""
    compatibility: str = ""
    allowed_tools: List[str] = None

    # Additional files
    scripts: Dict[str, str] = None  # filename -> content
    references: Dict[str, str] = None  # filename -> content


@dataclass
class GenerationResult:
    """Result of skill generation."""
    status: str  # "success", "error", "pending_approval"
    skill_name: str
    skill_path: Optional[str] = None
    files_created: List[str] = None
    error: Optional[str] = None
    validation_errors: List[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "skill_name": self.skill_name,
            "skill_path": self.skill_path,
            "files_created": self.files_created or [],
            "error": self.error,
            "validation_errors": self.validation_errors or [],
        }


class SkillGeneratorMCP:
    """
    Generates skills and MCP tools from specifications.

    This is the core tool for Pandora's self-extension capability.
    It creates new skills that can be immediately used after generation.

    Methods:
        generate_skill: Create SKILL.md + supporting files
        validate_spec: Check a specification before generation
        validate_skill: Check an existing skill against the spec
        list_templates: Show available templates
    """

    def __init__(self, session_id: Optional[str] = None):
        """
        Initialize the skill generator.

        Args:
            session_id: Optional session identifier for tracking
        """
        self.session_id = session_id
        self.skills_dir = GENERATED_SKILLS_DIR

        # Ensure directories exist
        self.skills_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[SkillGeneratorMCP] Initialized (session={session_id})")

    def validate_spec(self, spec: SkillSpec) -> List[str]:
        """
        Validate a skill specification before generation.

        Args:
            spec: SkillSpec to validate

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Validate name
        if not spec.name:
            errors.append("name is required")
        elif len(spec.name) > MAX_NAME_LENGTH:
            errors.append(f"name must be <= {MAX_NAME_LENGTH} characters")
        elif not NAME_PATTERN.match(spec.name):
            errors.append("name must be lowercase letters, numbers, and hyphens only")

        # Validate description
        if not spec.description:
            errors.append("description is required")
        elif len(spec.description) > MAX_DESCRIPTION_LENGTH:
            errors.append(f"description must be <= {MAX_DESCRIPTION_LENGTH} characters")

        # Validate instructions
        if not spec.instructions:
            errors.append("instructions are required")
        elif len(spec.instructions) < 50:
            errors.append("instructions should be at least 50 characters")

        # Check for duplicate name
        skill_dir = self.skills_dir / spec.name
        if skill_dir.exists():
            errors.append(f"skill '{spec.name}' already exists at {skill_dir}")

        return errors

    async def generate_skill(
        self,
        name: str,
        description: str,
        instructions: str,
        author: str = "pandora-generated",
        version: str = "1.0",
        source: str = "",
        license: str = "",
        compatibility: str = "",
        allowed_tools: List[str] = None,
        scripts: Dict[str, str] = None,
        references: Dict[str, str] = None,
    ) -> GenerationResult:
        """
        Generate a complete skill package.

        Creates:
        - SKILL.md with frontmatter and instructions
        - scripts/ directory if scripts provided
        - references/ directory if references provided

        Args:
            name: Skill name (lowercase, hyphens)
            description: What the skill does and when to use it
            instructions: Full instructions for using the skill
            author: Skill author (default: pandora-generated)
            version: Skill version (default: 1.0)
            source: URL or concept the skill was derived from
            license: License (e.g., Apache-2.0)
            compatibility: Environment requirements
            allowed_tools: Pre-approved tools the skill can use
            scripts: Dict of script filename -> content
            references: Dict of reference filename -> content

        Returns:
            GenerationResult with status and details
        """
        logger.info(f"[SkillGeneratorMCP] Generating skill: {name}")

        # Build spec
        spec = SkillSpec(
            name=name,
            description=description,
            instructions=instructions,
            author=author,
            version=version,
            source=source,
            license=license,
            compatibility=compatibility,
            allowed_tools=allowed_tools or [],
            scripts=scripts or {},
            references=references or {},
        )

        # Validate
        errors = self.validate_spec(spec)
        if errors:
            logger.warning(f"[SkillGeneratorMCP] Validation failed: {errors}")
            return GenerationResult(
                status="error",
                skill_name=name,
                error="Validation failed",
                validation_errors=errors,
            )

        # Create skill directory
        skill_dir = self.skills_dir / name
        try:
            skill_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"[SkillGeneratorMCP] Failed to create directory: {e}")
            return GenerationResult(
                status="error",
                skill_name=name,
                error=f"Failed to create directory: {e}",
            )

        files_created = []

        try:
            # Generate SKILL.md
            skill_md_content = self._generate_skill_md(spec)
            skill_md_path = skill_dir / "SKILL.md"
            skill_md_path.write_text(skill_md_content)
            files_created.append(str(skill_md_path))
            logger.info(f"[SkillGeneratorMCP] Created: {skill_md_path}")

            # Generate scripts/ if provided
            if spec.scripts:
                scripts_dir = skill_dir / "scripts"
                scripts_dir.mkdir(exist_ok=True)
                for filename, content in spec.scripts.items():
                    script_path = scripts_dir / filename
                    script_path.write_text(content)
                    files_created.append(str(script_path))
                    logger.info(f"[SkillGeneratorMCP] Created: {script_path}")

            # Generate references/ if provided
            if spec.references:
                refs_dir = skill_dir / "references"
                refs_dir.mkdir(exist_ok=True)
                for filename, content in spec.references.items():
                    ref_path = refs_dir / filename
                    ref_path.write_text(content)
                    files_created.append(str(ref_path))
                    logger.info(f"[SkillGeneratorMCP] Created: {ref_path}")

            # Register with SkillRegistry for immediate use
            await self._register_skill(skill_dir)

            logger.info(f"[SkillGeneratorMCP] Skill generated successfully: {name}")
            return GenerationResult(
                status="success",
                skill_name=name,
                skill_path=str(skill_dir),
                files_created=files_created,
            )

        except Exception as e:
            logger.error(f"[SkillGeneratorMCP] Generation failed: {e}")
            # Cleanup on failure
            try:
                import shutil
                if skill_dir.exists():
                    shutil.rmtree(skill_dir)
            except Exception:
                pass
            return GenerationResult(
                status="error",
                skill_name=name,
                error=f"Generation failed: {e}",
            )

    def _generate_skill_md(self, spec: SkillSpec) -> str:
        """Generate SKILL.md content from spec."""
        # Build frontmatter
        frontmatter = {
            "name": spec.name,
            "description": spec.description,
        }

        if spec.license:
            frontmatter["license"] = spec.license
        if spec.compatibility:
            frontmatter["compatibility"] = spec.compatibility
        if spec.allowed_tools:
            frontmatter["allowed-tools"] = " ".join(spec.allowed_tools)

        # Always include metadata
        frontmatter["metadata"] = {
            "author": spec.author,
            "version": spec.version,
            "generated_at": datetime.now().isoformat(),
        }
        if spec.source:
            frontmatter["metadata"]["generated_from"] = spec.source

        # Build YAML frontmatter
        import yaml
        yaml_content = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)

        # Combine frontmatter and instructions
        content = f"""---
{yaml_content.strip()}
---

{spec.instructions}
"""
        return content

    async def _register_skill(self, skill_dir: Path):
        """Register the skill with SkillRegistry."""
        try:
            from libs.gateway.skill_registry import get_skill_registry
            registry = get_skill_registry()
            await registry.register_skill(skill_dir)
        except Exception as e:
            logger.warning(f"[SkillGeneratorMCP] Failed to register skill: {e}")
            # Non-fatal - skill still exists on disk

    async def validate_skill(self, skill_path: str) -> Dict[str, Any]:
        """
        Validate an existing skill against the Agent Skills spec.

        Args:
            skill_path: Path to skill directory

        Returns:
            Validation result with errors and warnings
        """
        skill_dir = Path(skill_path)
        errors = []
        warnings = []

        # Check directory exists
        if not skill_dir.exists():
            return {
                "valid": False,
                "errors": [f"Skill directory not found: {skill_path}"],
                "warnings": [],
            }

        # Check SKILL.md exists
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return {
                "valid": False,
                "errors": ["SKILL.md not found"],
                "warnings": [],
            }

        # Parse and validate SKILL.md
        content = skill_md.read_text()

        # Check frontmatter
        frontmatter_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
        if not frontmatter_match:
            errors.append("Missing YAML frontmatter")
        else:
            try:
                import yaml
                fm = yaml.safe_load(frontmatter_match.group(1))

                if not fm.get("name"):
                    errors.append("Missing required field: name")
                elif not NAME_PATTERN.match(fm["name"]):
                    errors.append("Invalid name format")

                if not fm.get("description"):
                    errors.append("Missing required field: description")
                elif len(fm["description"]) < 10:
                    warnings.append("Description is very short")

            except yaml.YAMLError as e:
                errors.append(f"Invalid YAML frontmatter: {e}")

        # Check body content
        body_match = re.match(r'^---\s*\n.*?\n---\s*\n(.*)$', content, re.DOTALL)
        if body_match:
            body = body_match.group(1).strip()
            if len(body) < 100:
                warnings.append("Instructions body is very short")
        else:
            warnings.append("No body content after frontmatter")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "path": str(skill_dir),
        }

    def list_templates(self) -> Dict[str, Any]:
        """
        List available templates.

        Returns:
            Dict with template names and descriptions
        """
        templates = {}

        if TEMPLATES_DIR.exists():
            for template_file in TEMPLATES_DIR.iterdir():
                if template_file.suffix in [".md", ".py"]:
                    templates[template_file.name] = {
                        "path": str(template_file),
                        "type": "skill" if template_file.suffix == ".md" else "mcp_tool",
                    }

        return {
            "templates_dir": str(TEMPLATES_DIR),
            "templates": templates,
        }

    async def delete_skill(self, name: str) -> Dict[str, Any]:
        """
        Delete a generated skill.

        Only works for skills in the generated/ directory.

        Args:
            name: Skill name

        Returns:
            Deletion result
        """
        skill_dir = self.skills_dir / name

        if not skill_dir.exists():
            return {
                "status": "error",
                "error": f"Skill not found: {name}",
            }

        # Safety check - only delete from generated/
        if "generated" not in str(skill_dir):
            return {
                "status": "error",
                "error": "Can only delete skills from generated/ directory",
            }

        try:
            import shutil
            shutil.rmtree(skill_dir)

            # Unregister from registry
            from libs.gateway.skill_registry import get_skill_registry
            registry = get_skill_registry()
            await registry.unregister_skill(name)

            logger.info(f"[SkillGeneratorMCP] Deleted skill: {name}")
            return {
                "status": "success",
                "skill_name": name,
                "message": f"Skill '{name}' deleted",
            }
        except Exception as e:
            logger.error(f"[SkillGeneratorMCP] Failed to delete skill: {e}")
            return {
                "status": "error",
                "error": f"Failed to delete skill: {e}",
            }


# =============================================================================
# Singleton Instance
# =============================================================================

_skill_generator_mcp: Optional[SkillGeneratorMCP] = None


def get_skill_generator_mcp(session_id: Optional[str] = None) -> SkillGeneratorMCP:
    """Get or create the SkillGeneratorMCP instance."""
    global _skill_generator_mcp
    if _skill_generator_mcp is None:
        _skill_generator_mcp = SkillGeneratorMCP(session_id=session_id)
    return _skill_generator_mcp


# =============================================================================
# Tool Manifest (for Orchestrator/Planner)
# =============================================================================

TOOL_MANIFEST = {
    "name": "skill.generator",
    "description": "Generate new skills for Pandora. Use when asked to build, create, or implement new capabilities, workflows, or domain expertise.",
    "methods": [
        {
            "name": "generate_skill",
            "description": "Generate a new skill with SKILL.md and optional scripts/references",
            "parameters": {
                "name": {"type": "string", "required": True, "description": "Skill name (lowercase, hyphens)"},
                "description": {"type": "string", "required": True, "description": "What the skill does and when to use it"},
                "instructions": {"type": "string", "required": True, "description": "Full instructions markdown"},
                "author": {"type": "string", "required": False, "default": "pandora-generated"},
                "version": {"type": "string", "required": False, "default": "1.0"},
                "source": {"type": "string", "required": False, "description": "Source URL or concept"},
                "scripts": {"type": "object", "required": False, "description": "Dict of script files"},
                "references": {"type": "object", "required": False, "description": "Dict of reference files"},
            },
        },
        {
            "name": "validate_skill",
            "description": "Validate an existing skill against the Agent Skills spec",
            "parameters": {
                "skill_path": {"type": "string", "required": True, "description": "Path to skill directory"},
            },
        },
        {
            "name": "list_templates",
            "description": "List available skill and MCP tool templates",
            "parameters": {},
        },
        {
            "name": "delete_skill",
            "description": "Delete a generated skill (only from generated/ directory)",
            "parameters": {
                "name": {"type": "string", "required": True, "description": "Skill name to delete"},
            },
        },
    ],
}
