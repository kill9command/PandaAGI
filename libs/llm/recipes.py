"""Recipe system for phase configuration."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from libs.core.config import get_settings


@dataclass
class TokenBudget:
    """Token budget for a phase."""

    total: int
    prompt: int
    input: int
    output: int

    def validate(self, prompt_tokens: int, input_tokens: int) -> bool:
        """Check if tokens are within budget."""
        return (
            prompt_tokens <= self.prompt and
            input_tokens <= self.input and
            (prompt_tokens + input_tokens) <= (self.total - self.output)
        )


@dataclass
class Recipe:
    """Configuration recipe for a phase."""

    name: str
    model: str
    token_budget: TokenBudget
    temperature: float = 0.7
    max_tokens: int = 2000
    system_prompt: str = ""
    user_prompt_template: str = ""
    output_schema: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path) -> "Recipe":
        """Load recipe from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)

        budget_data = data.get("token_budget", {})
        token_budget = TokenBudget(
            total=budget_data.get("total", 8000),
            prompt=budget_data.get("prompt", 2000),
            input=budget_data.get("input", 4000),
            output=budget_data.get("output", 2000),
        )

        return cls(
            name=data.get("name", path.stem),
            model=data.get("model", "mind"),
            token_budget=token_budget,
            temperature=data.get("temperature", 0.7),
            max_tokens=data.get("max_tokens", 2000),
            system_prompt=data.get("system_prompt", ""),
            user_prompt_template=data.get("user_prompt_template", ""),
            output_schema=data.get("output_schema", {}),
            extra=data.get("extra", {}),
        )


class RecipeLoader:
    """Loads and caches recipe configurations."""

    def __init__(self):
        self.settings = get_settings()
        self.recipes_dir = self.settings.project_root / "apps" / "recipes"
        self._cache: dict[str, Recipe] = {}

    def load(self, name: str) -> Recipe:
        """
        Load a recipe by name.

        Args:
            name: Recipe name (without .yaml extension)

        Returns:
            Recipe configuration

        Raises:
            FileNotFoundError: If recipe file doesn't exist
        """
        if name in self._cache:
            return self._cache[name]

        path = self.recipes_dir / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Recipe not found: {path}")

        recipe = Recipe.from_yaml(path)
        self._cache[name] = recipe
        return recipe

    def load_phase_recipe(self, phase: int, mode: str = "chat") -> Recipe:
        """
        Load recipe for a specific phase.

        Args:
            phase: Phase number (0-indexed: 0-7 maps to architecture phases 1-8)
            mode: 'chat' or 'code'

        Returns:
            Recipe for the phase

        Note: Phase 8 (Save) is procedural and has no recipe.
        """
        recipe_names = {
            0: "query_analyzer",           # Phase 1: Query Analyzer
            1: "query_analyzer_validator", # Phase 1.5: Query Validator (legacy: reflection)
            2: f"context_gatherer_{mode}", # Phase 2: Context Gatherer
            3: f"planner_{mode}",          # Phase 3: Planner
            4: f"executor_{mode}",         # Phase 4: Executor
            5: f"coordinator_{mode}",      # Phase 5: Coordinator
            6: f"synthesizer_{mode}",      # Phase 6: Synthesis
            7: "validator",                # Phase 7: Validation
        }

        name = recipe_names.get(phase)
        if not name:
            raise ValueError(f"No recipe defined for phase {phase}")

        return self.load(name)

    def clear_cache(self):
        """Clear recipe cache."""
        self._cache.clear()


# Singleton instance
_recipe_loader: RecipeLoader | None = None


def get_recipe_loader() -> RecipeLoader:
    """Get recipe loader singleton."""
    global _recipe_loader
    if _recipe_loader is None:
        _recipe_loader = RecipeLoader()
    return _recipe_loader
