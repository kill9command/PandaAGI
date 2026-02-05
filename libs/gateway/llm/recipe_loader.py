"""
Recipe Loader for v4.0 Document-Driven Architecture

Loads YAML recipes that define role I/O contracts.

Author: v4.0 Migration
Date: 2025-11-16
"""

import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

# Base directories
RECIPES_DIR = Path("apps/recipes/recipes")
PROMPTS_DIR = Path("apps/prompts")


class RecipeNotFoundError(Exception):
    """Raised when requested recipe doesn't exist"""
    pass


class RecipeValidationError(Exception):
    """Raised when recipe fails validation"""
    pass


@dataclass
class TokenBudget:
    """Token budget specification"""
    total: int
    prompt: int
    input_docs: int
    output: int
    buffer: int = 0

    def validate(self):
        """Validate budget adds up correctly"""
        allocated = self.prompt + self.input_docs + self.output + self.buffer
        if allocated != self.total:
            raise RecipeValidationError(
                f"Token budget doesn't add up: "
                f"total={self.total}, allocated={allocated} "
                f"(prompt={self.prompt} + input_docs={self.input_docs} + "
                f"output={self.output} + buffer={self.buffer})"
            )


@dataclass(frozen=True)
class TrimStrategy:
    """Trimming strategy for docs that exceed budget"""
    method: str  # truncate_end | truncate_start | drop_oldest | summarize
    field: Optional[str] = None  # Field to apply strategy to
    target: Optional[int] = None  # Target token count


@dataclass(frozen=True)
class DocSpec:
    """Document specification from recipe"""
    path: str  # e.g., "context.md"
    optional: bool = False
    max_tokens: Optional[int] = None
    trim_strategy: Optional[TrimStrategy] = None
    path_type: str = "turn"  # "turn" | "repo" | "absolute" | "session"

    @classmethod
    def from_string(cls, spec_str: str) -> 'DocSpec':
        """
        Parse doc spec from string (legacy format).

        Examples:
        - "user_query.md" → DocSpec(path="user_query.md")
        - "context.md (optional)" → DocSpec(path="...", optional=True)
        - "context.md (max 500 tokens)" → DocSpec(path="...", max_tokens=500)
        """
        path = spec_str.strip()
        optional = False
        max_tokens = None

        # Check for annotations
        if "(" in path:
            path, annotation = path.split("(", 1)
            path = path.strip()
            annotation = annotation.rstrip(")")

            if "optional" in annotation.lower():
                optional = True

            if "max" in annotation.lower():
                # Extract number: "max 500 tokens" → 500
                import re
                match = re.search(r'(\d+)', annotation)
                if match:
                    max_tokens = int(match.group(1))

        return cls(path=path, optional=optional, max_tokens=max_tokens, path_type="turn")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DocSpec':
        """
        Parse doc spec from dictionary (new structured format).

        Example:
        {
            "path": "context.md",
            "optional": false,
            "max_tokens": 400,
            "path_type": "repo"
        }
        """
        return cls(
            path=data["path"],
            optional=data.get("optional", False),
            max_tokens=data.get("max_tokens"),
            path_type=data.get("path_type", "turn")
        )


@dataclass
class Recipe:
    """
    Recipe definition loaded from YAML.

    Defines what a role can read (input_docs) and write (output_docs),
    with hard token budgets enforced by Doc Pack Builder.
    """
    name: str
    role: str  # guide | coordinator | context_manager | system
    phase: Optional[str] = None  # strategic | synthesis (for guide)
    mode: Optional[str] = None  # chat | code (if mode-specific)

    prompt_fragments: List[str] = field(default_factory=list)
    input_docs: List[DocSpec] = field(default_factory=list)
    output_docs: List[str] = field(default_factory=list)

    token_budget: Optional[TokenBudget] = None
    trimming_strategy: Optional[TrimStrategy] = None
    output_schema: Optional[str] = None  # TICKET, PLAN, CAPSULE, etc.

    # Parsed from YAML
    _raw_spec: Dict[str, Any] = field(default_factory=dict, repr=False)

    def get_prompt_paths(self) -> List[Path]:
        """Get full paths to prompt fragments"""
        paths = []
        for fragment in self.prompt_fragments:
            # Fragment format: "prompts/guide/common.md (290 tokens)"
            # Extract just the path
            path_str = fragment.split("(")[0].strip()
            full_path = Path(path_str)
            if not full_path.exists():
                raise RecipeValidationError(f"Prompt fragment not found: {full_path}")
            paths.append(full_path)
        return paths

    def get_prompt(self) -> str:
        """
        Get the combined prompt text from all prompt fragments.

        Returns:
            Combined prompt text from all fragments, joined with newlines.
        """
        fragments = []
        for fragment_path in self.get_prompt_paths():
            fragments.append(fragment_path.read_text())
        return "\n\n".join(fragments)

    def validate(self):
        """Validate recipe specification"""
        # Required fields
        if not self.name:
            raise RecipeValidationError("Recipe missing 'name'")
        if not self.role:
            raise RecipeValidationError("Recipe missing 'role'")

        # Token budget validation
        if self.token_budget:
            self.token_budget.validate()

        # Validate prompt fragments exist
        for fragment_path in self.get_prompt_paths():
            if not fragment_path.exists():
                raise RecipeValidationError(f"Prompt fragment not found: {fragment_path}")

        logger.debug(f"[Recipe] Validated {self.name}")

    def __str__(self):
        return f"Recipe({self.name}, role={self.role}, budget={self.token_budget.total if self.token_budget else 'N/A'})"


def load_recipe(name: str, recipes_dir: Optional[Path] = None) -> Recipe:
    """
    Load recipe from YAML file.

    Args:
        name: Recipe name (e.g., "guide_strategic_chat")
        recipes_dir: Optional override for recipes directory

    Returns:
        Recipe instance

    Raises:
        RecipeNotFoundError: If recipe file doesn't exist
        RecipeValidationError: If recipe is invalid
    """
    if recipes_dir is None:
        recipes_dir = RECIPES_DIR

    recipe_path = recipes_dir / f"{name}.yaml"

    if not recipe_path.exists():
        raise RecipeNotFoundError(f"Recipe not found: {recipe_path}")

    # Load YAML
    with open(recipe_path, 'r') as f:
        spec = yaml.safe_load(f)

    # Parse input_docs with support for both formats
    input_docs = []
    for doc_item in spec.get("input_docs", []):
        if isinstance(doc_item, str):
            # Legacy string format: "doc.md (optional)" or "doc.md (max 400 tokens)"
            input_docs.append(DocSpec.from_string(doc_item))
        elif isinstance(doc_item, dict):
            # New structured format: {path, optional, max_tokens, path_type}
            input_docs.append(DocSpec.from_dict(doc_item))
        else:
            raise RecipeValidationError(f"Invalid input_doc format: {doc_item}")

    # Parse into Recipe object
    recipe = Recipe(
        name=spec.get("name", name),
        role=spec["role"],
        phase=spec.get("phase"),
        mode=spec.get("mode"),
        prompt_fragments=spec.get("prompt_fragments", []),
        input_docs=input_docs,
        output_docs=spec.get("output_docs", []),
        output_schema=spec.get("output_schema"),
        _raw_spec=spec
    )

    # Parse token budget
    if "token_budget" in spec:
        budget_spec = spec["token_budget"]
        recipe.token_budget = TokenBudget(
            total=budget_spec["total"],
            prompt=budget_spec["prompt"],
            input_docs=budget_spec["input_docs"],
            output=budget_spec["output"],
            buffer=budget_spec.get("buffer", 0)
        )

    # Parse trimming strategy
    if "trimming_strategy" in spec:
        trim_spec = spec["trimming_strategy"]
        if isinstance(trim_spec, dict):
            recipe.trimming_strategy = TrimStrategy(
                method=trim_spec["method"],
                field=trim_spec.get("field"),
                target=trim_spec.get("target")
            )
        elif isinstance(trim_spec, str):
            recipe.trimming_strategy = TrimStrategy(method=trim_spec)

    # Validate
    recipe.validate()

    logger.info(f"[Recipe] Loaded {recipe.name} ({recipe.role}, budget={recipe.token_budget.total if recipe.token_budget else 'N/A'})")

    return recipe


def select_recipe(
    role: str,
    mode: str,
    phase: Optional[str] = None,
    content_type: Optional[str] = None
) -> Recipe:
    """
    Select appropriate recipe based on role, mode, phase, and content_type.

    Uses canonical role names (2026-01-24):
    - context_builder: Memory read layer
    - reflection: Strategic gate
    - planner: Strategic planning (STRATEGIC_PLAN with goals)
    - executor: Tactical execution (natural language commands to Coordinator)
    - coordinator: Tool Expert (translates commands to tool calls)
    - researcher: Internet research (MCP sub-system)
    - verifier: Evidence evaluation
    - synthesizer: Response generation
    - summarizer: Turn summary + memory write

    Args:
        role: Canonical role name (see above)
        mode: "chat" | "code"
        phase: Optional phase hint (deprecated, use role name directly)
        content_type: Optional content type for commerce queries ("electronics" | "pets" | "general")
                      Enables content-type-specific prompts for planner and synthesizer.

    Returns:
        Recipe instance

    Examples:
        - select_recipe("planner", "chat") → planner_chat.yaml
        - select_recipe("planner", "chat", content_type="electronics") → planner_chat_electronics.yaml (if exists)
        - select_recipe("planner", "chat", content_type="pets") → planner_chat_pets.yaml (if exists)
        - select_recipe("synthesizer", "code") → synthesizer_code.yaml
        - select_recipe("verifier", "chat") → verifier.yaml (unified)
        - select_recipe("context_builder", "chat") → context_builder.yaml
    """
    # Role mapping: old names → canonical names (for backward compatibility)
    ROLE_ALIASES = {
        "guide": "planner",  # guide_strategic → planner
        "guide_strategic": "planner",
        "guide_synthesis": "synthesizer",
        "context_manager": "verifier",
        "turn_summarizer": "summarizer",
        "research": "researcher",
        "meta_reflection": "reflection",
    }

    # Resolve alias if needed
    canonical_role = ROLE_ALIASES.get(role, role)

    # Handle legacy phase-based selection
    if role == "guide" and phase == "strategic":
        canonical_role = "planner"
    elif role == "guide" and phase == "synthesis":
        canonical_role = "synthesizer"

    # Unified recipes (no mode suffix)
    UNIFIED_ROLES = {
        "context_builder",
        "reflection",
        "verifier",
        "summarizer",
        "researcher",
    }

    # Mode-specific recipes (have _chat and _code variants)
    MODE_SPECIFIC_ROLES = {
        "planner",
        "executor",      # NEW: 3-tier architecture (Planner → Executor → Coordinator)
        "coordinator",
        "synthesizer",
    }

    # Roles that support content-type specialization
    # These roles can have content-type-specific variants (e.g., planner_chat_electronics)
    CONTENT_TYPE_ROLES = {"planner", "synthesizer"}

    if canonical_role in UNIFIED_ROLES:
        recipe_name = canonical_role
    elif canonical_role in MODE_SPECIFIC_ROLES:
        base_recipe_name = f"{canonical_role}_{mode}"

        # Try content-type-specific recipe first (only for certain roles)
        if content_type and content_type != "general" and canonical_role in CONTENT_TYPE_ROLES:
            specialized_name = f"{canonical_role}_{mode}_{content_type}"
            try:
                logger.info(f"[Recipe] Trying content-type-specific recipe: {specialized_name}")
                return load_recipe(specialized_name)
            except (FileNotFoundError, RecipeNotFoundError):
                logger.info(f"[Recipe] Content-type recipe not found ({specialized_name}), falling back to {base_recipe_name}")

        recipe_name = base_recipe_name
    else:
        # Unknown role - try direct lookup
        recipe_name = canonical_role

    return load_recipe(recipe_name)


def list_recipes(recipes_dir: Optional[Path] = None) -> List[str]:
    """
    List all available recipes.

    Args:
        recipes_dir: Optional override for recipes directory

    Returns:
        List of recipe names (without .yaml extension)
    """
    if recipes_dir is None:
        recipes_dir = RECIPES_DIR

    if not recipes_dir.exists():
        return []

    return [
        f.stem for f in recipes_dir.glob("*.yaml")
        if f.stem != "README"
    ]


def validate_all_recipes(recipes_dir: Optional[Path] = None) -> Dict[str, bool]:
    """
    Validate all recipes in directory.

    Args:
        recipes_dir: Optional override for recipes directory

    Returns:
        Dict of {recipe_name: is_valid}
    """
    if recipes_dir is None:
        recipes_dir = RECIPES_DIR

    results = {}
    for recipe_name in list_recipes(recipes_dir):
        try:
            load_recipe(recipe_name, recipes_dir)
            results[recipe_name] = True
        except (RecipeNotFoundError, RecipeValidationError) as e:
            logger.error(f"[Recipe] Validation failed for {recipe_name}: {e}")
            results[recipe_name] = False

    return results
