"""
Skill Registry - Discovery, loading, and management of Agent Skills.

This module implements skill discovery and loading for Pandora's self-extension
capability. Skills are folders containing SKILL.md files that provide
instructions, scripts, and resources for specific tasks.

Based on the Agent Skills format: https://agentskills.io

Usage:
    registry = get_skill_registry()

    # Discover all skills
    await registry.scan_skills()

    # Get available skills for prompts
    xml = registry.get_available_skills_xml()

    # Match a query to a skill
    skill = registry.match_skill("review this code")

    # Load full skill content
    content = await registry.load_skill("code-review")
"""

import logging
import re
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# Default skills directory
DEFAULT_SKILLS_DIR = Path("panda_system_docs/skills")


@dataclass
class SkillMetadata:
    """
    Metadata parsed from SKILL.md frontmatter.

    Loaded at startup for all skills (progressive disclosure).
    """
    name: str
    description: str
    path: Path  # Absolute path to skill directory

    # Optional fields
    license: Optional[str] = None
    compatibility: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)
    allowed_tools: List[str] = field(default_factory=list)

    # Runtime tracking
    loaded_at: Optional[datetime] = None
    use_count: int = 0
    last_used: Optional[datetime] = None

    @property
    def skill_md_path(self) -> Path:
        """Path to the SKILL.md file."""
        return self.path / "SKILL.md"

    @property
    def category(self) -> str:
        """Determine skill category from path."""
        if "core" in str(self.path):
            return "core"
        elif "generated" in str(self.path):
            return "generated"
        elif "user" in str(self.path):
            return "user"
        return "unknown"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "path": str(self.path),
            "category": self.category,
            "license": self.license,
            "compatibility": self.compatibility,
            "metadata": self.metadata,
            "allowed_tools": self.allowed_tools,
            "use_count": self.use_count,
            "last_used": self.last_used.isoformat() if self.last_used else None,
        }


@dataclass
class LoadedSkill:
    """
    A fully loaded skill with instructions.

    Created when a skill is activated (on-demand loading).
    """
    metadata: SkillMetadata
    instructions: str  # Full SKILL.md body content

    # Optional loaded resources
    scripts: Dict[str, str] = field(default_factory=dict)  # name -> content
    references: Dict[str, str] = field(default_factory=dict)  # name -> content

    def get_full_content(self) -> str:
        """Get full skill content for LLM context."""
        return self.instructions


class SkillRegistry:
    """
    Manages discovered and generated skills.

    Responsibilities:
    - Scan skills directories for SKILL.md files
    - Parse and cache skill metadata
    - Match user queries to relevant skills
    - Load full skill content on demand
    - Track skill usage statistics
    - Hot-reload new skills without restart
    """

    def __init__(self, skills_dir: Path = None):
        """
        Initialize the skill registry.

        Args:
            skills_dir: Base directory for skills (default: panda_system_docs/skills)
        """
        self.skills_dir = skills_dir or DEFAULT_SKILLS_DIR
        self.skills: Dict[str, SkillMetadata] = {}
        self._loaded_cache: Dict[str, LoadedSkill] = {}

        logger.info(f"[SkillRegistry] Initialized with skills_dir={self.skills_dir}")

    async def scan_skills(self) -> int:
        """
        Discover all skills in the skills directory.

        Scans core/, generated/, and user/ subdirectories.

        Returns:
            Number of skills discovered
        """
        self.skills.clear()
        discovered = 0

        # Scan each subdirectory
        for subdir in ["core", "generated", "user"]:
            subdir_path = self.skills_dir / subdir
            if not subdir_path.exists():
                continue

            # Find all SKILL.md files
            for skill_md in subdir_path.rglob("SKILL.md"):
                skill_dir = skill_md.parent
                try:
                    metadata = self._parse_skill_metadata(skill_dir)
                    if metadata:
                        self.skills[metadata.name] = metadata
                        discovered += 1
                        logger.debug(f"[SkillRegistry] Discovered: {metadata.name} ({metadata.category})")
                except Exception as e:
                    logger.warning(f"[SkillRegistry] Failed to parse {skill_md}: {e}")

        logger.info(f"[SkillRegistry] Scan complete: {discovered} skills discovered")
        return discovered

    def _parse_skill_metadata(self, skill_dir: Path) -> Optional[SkillMetadata]:
        """
        Parse SKILL.md frontmatter to extract metadata.

        Args:
            skill_dir: Directory containing SKILL.md

        Returns:
            SkillMetadata or None if parsing fails
        """
        skill_md_path = skill_dir / "SKILL.md"
        if not skill_md_path.exists():
            return None

        content = skill_md_path.read_text()

        # Extract YAML frontmatter
        frontmatter_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
        if not frontmatter_match:
            logger.warning(f"[SkillRegistry] No frontmatter in {skill_md_path}")
            return None

        try:
            frontmatter = yaml.safe_load(frontmatter_match.group(1))
        except yaml.YAMLError as e:
            logger.warning(f"[SkillRegistry] Invalid YAML in {skill_md_path}: {e}")
            return None

        # Validate required fields
        name = frontmatter.get("name")
        description = frontmatter.get("description")

        if not name or not description:
            logger.warning(f"[SkillRegistry] Missing required fields in {skill_md_path}")
            return None

        # Validate name format
        if not self._validate_skill_name(name):
            logger.warning(f"[SkillRegistry] Invalid skill name: {name}")
            return None

        # Parse allowed-tools
        allowed_tools = []
        if "allowed-tools" in frontmatter:
            allowed_tools = frontmatter["allowed-tools"].split()

        return SkillMetadata(
            name=name,
            description=description,
            path=skill_dir.resolve(),
            license=frontmatter.get("license"),
            compatibility=frontmatter.get("compatibility"),
            metadata=frontmatter.get("metadata", {}),
            allowed_tools=allowed_tools,
            loaded_at=datetime.now(),
        )

    def _validate_skill_name(self, name: str) -> bool:
        """
        Validate skill name against Agent Skills spec.

        Rules:
        - 1-64 characters
        - Lowercase letters, numbers, hyphens only
        - No leading/trailing hyphens
        - No consecutive hyphens
        """
        if not name or len(name) > 64:
            return False
        if not re.match(r'^[a-z0-9]+(-[a-z0-9]+)*$', name):
            return False
        return True

    async def register_skill(self, skill_dir: Path) -> Optional[SkillMetadata]:
        """
        Register a new skill (hot-reload).

        Use this to add skills created by skill-builder without restart.

        Args:
            skill_dir: Path to the skill directory

        Returns:
            SkillMetadata if successful, None otherwise
        """
        metadata = self._parse_skill_metadata(skill_dir)
        if metadata:
            self.skills[metadata.name] = metadata
            # Clear from loaded cache to force reload
            if metadata.name in self._loaded_cache:
                del self._loaded_cache[metadata.name]
            logger.info(f"[SkillRegistry] Registered: {metadata.name}")
        return metadata

    async def unregister_skill(self, name: str) -> bool:
        """
        Unregister a skill.

        Args:
            name: Skill name

        Returns:
            True if skill was unregistered
        """
        if name in self.skills:
            del self.skills[name]
            if name in self._loaded_cache:
                del self._loaded_cache[name]
            logger.info(f"[SkillRegistry] Unregistered: {name}")
            return True
        return False

    def get_skill(self, name: str) -> Optional[SkillMetadata]:
        """Get skill metadata by name."""
        return self.skills.get(name)

    def get_all_skills(self) -> List[SkillMetadata]:
        """Get all registered skills."""
        return list(self.skills.values())

    def get_skills_by_category(self, category: str) -> List[SkillMetadata]:
        """Get skills filtered by category (core, generated, user)."""
        return [s for s in self.skills.values() if s.category == category]

    async def load_skill(self, name: str) -> Optional[LoadedSkill]:
        """
        Load full skill content for execution.

        This implements the progressive disclosure pattern:
        - Metadata is loaded at startup (lightweight)
        - Full content is loaded on-demand (heavier)

        Args:
            name: Skill name

        Returns:
            LoadedSkill with full instructions, or None
        """
        # Check cache first
        if name in self._loaded_cache:
            skill = self._loaded_cache[name]
            skill.metadata.use_count += 1
            skill.metadata.last_used = datetime.now()
            return skill

        # Get metadata
        metadata = self.skills.get(name)
        if not metadata:
            logger.warning(f"[SkillRegistry] Skill not found: {name}")
            return None

        # Load full SKILL.md content
        skill_md_path = metadata.skill_md_path
        if not skill_md_path.exists():
            logger.error(f"[SkillRegistry] SKILL.md missing: {skill_md_path}")
            return None

        content = skill_md_path.read_text()

        # Extract body (after frontmatter)
        body_match = re.match(r'^---\s*\n.*?\n---\s*\n(.*)$', content, re.DOTALL)
        instructions = body_match.group(1) if body_match else content

        # Create loaded skill
        loaded = LoadedSkill(
            metadata=metadata,
            instructions=instructions.strip(),
        )

        # Cache it
        self._loaded_cache[name] = loaded

        # Update usage stats
        metadata.use_count += 1
        metadata.last_used = datetime.now()

        logger.info(f"[SkillRegistry] Loaded skill: {name} ({len(instructions)} chars)")
        return loaded

    def match_skill(self, query: str) -> Optional[SkillMetadata]:
        """
        Find the best matching skill for a query.

        Uses simple keyword matching on skill descriptions.
        For more sophisticated matching, integrate with embeddings.

        Args:
            query: User query

        Returns:
            Best matching SkillMetadata, or None
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())

        best_match = None
        best_score = 0

        for skill in self.skills.values():
            # Score based on keyword overlap
            desc_words = set(skill.description.lower().split())
            overlap = len(query_words & desc_words)

            # Bonus for name match
            if skill.name in query_lower:
                overlap += 5

            # Bonus for explicit "use X skill" pattern
            if f"use the {skill.name}" in query_lower or f"use {skill.name}" in query_lower:
                overlap += 10

            if overlap > best_score:
                best_score = overlap
                best_match = skill

        # Require minimum score to match
        if best_score >= 2:
            logger.debug(f"[SkillRegistry] Matched '{query[:30]}...' to skill '{best_match.name}' (score={best_score})")
            return best_match

        return None

    def get_available_skills_xml(self) -> str:
        """
        Generate <available_skills> XML block for LLM prompts.

        This is injected into system prompts so the LLM knows
        what skills are available.

        Returns:
            XML string suitable for Claude prompts
        """
        if not self.skills:
            return "<available_skills>\n  (No skills available)\n</available_skills>"

        lines = ["<available_skills>"]

        for skill in sorted(self.skills.values(), key=lambda s: s.name):
            lines.append("  <skill>")
            lines.append(f"    <name>{skill.name}</name>")
            lines.append(f"    <description>{skill.description}</description>")
            lines.append(f"    <category>{skill.category}</category>")
            lines.append(f"    <location>{skill.skill_md_path}</location>")
            lines.append("  </skill>")

        lines.append("</available_skills>")
        return "\n".join(lines)

    def get_skills_summary(self) -> Dict[str, Any]:
        """Get summary statistics about registered skills."""
        by_category = {}
        for skill in self.skills.values():
            cat = skill.category
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(skill.name)

        return {
            "total": len(self.skills),
            "by_category": by_category,
            "skills": [s.to_dict() for s in self.skills.values()],
        }


# =============================================================================
# Singleton Instance
# =============================================================================

_skill_registry: Optional[SkillRegistry] = None


def get_skill_registry(skills_dir: Path = None) -> SkillRegistry:
    """Get or create the global SkillRegistry instance."""
    global _skill_registry
    if _skill_registry is None:
        _skill_registry = SkillRegistry(skills_dir=skills_dir)
    return _skill_registry


async def init_skill_registry(skills_dir: Path = None) -> SkillRegistry:
    """Initialize and scan the skill registry."""
    registry = get_skill_registry(skills_dir)
    await registry.scan_skills()
    return registry
