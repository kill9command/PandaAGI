"""
Doc Pack Builder for v4.0 Document-Driven Architecture

Builds document packs from recipes with hard token budget enforcement.

Guarantees:
- Never exceeds recipe.token_budget.total
- Logs all trimming decisions to manifest
- Preserves most important context via trimming strategies

Compression Options (2025-11-26):
- Smart compression via DocumentCompressor for semantic preservation
- Simple truncation fallback for speed
- Configurable via use_smart_compression flag

Author: v4.0 Migration
Date: 2025-11-16
Updated: 2025-11-26 (added smart compression integration)
"""

import tiktoken
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
import logging

from libs.gateway.recipe_loader import Recipe, DocSpec, TrimStrategy

logger = logging.getLogger(__name__)

# Token counter (using tiktoken for accuracy)
try:
    ENCODER = tiktoken.get_encoding("cl100k_base")  # GPT-4 encoding
except Exception:
    logger.warning("[DocPack] tiktoken not available, using rough estimate")
    ENCODER = None


def count_tokens(text: str) -> int:
    """
    Count tokens in text.

    Uses tiktoken if available, otherwise rough estimate (4 chars = 1 token).
    """
    if ENCODER:
        return len(ENCODER.encode(text))
    else:
        # Rough estimate: 4 characters ≈ 1 token
        return len(text) // 4


@dataclass
class DocItem:
    """A document loaded into the pack"""
    name: str
    content: str
    tokens: int
    source: str  # "prompt" | "input_doc"
    trimmed: bool = False
    original_tokens: Optional[int] = None


@dataclass
class DocPack:
    """
    Document pack assembled from recipe.

    Contains all prompts and input docs needed for an LLM call,
    with token budget enforced.
    """
    recipe_name: str
    budget: int
    items: List[DocItem] = field(default_factory=list)
    trimming_log: List[str] = field(default_factory=list)
    output_budget_reserved: int = 0

    @property
    def token_count(self) -> int:
        """Total tokens currently in pack"""
        return sum(item.tokens for item in self.items) + self.output_budget_reserved

    @property
    def remaining_budget(self) -> int:
        """Remaining budget available"""
        return self.budget - self.token_count

    def add_prompt(self, path: Path, content: str):
        """Add a prompt fragment (non-negotiable, always included)"""
        tokens = count_tokens(content)
        self.items.append(DocItem(
            name=path.name,
            content=content,
            tokens=tokens,
            source="prompt"
        ))
        logger.debug(f"[DocPack] Added prompt {path.name} ({tokens} tokens)")

    def add_doc(self, name: str, content: str, budget: Optional[int] = None):
        """Add an input document (may be trimmed with smart or simple truncation)"""
        tokens = count_tokens(content)
        original_tokens = tokens

        # Trim if budget specified and exceeded
        if budget and tokens > budget:
            # CRITICAL DOCS: Use smart compression to preserve all items
            is_critical = name in ("context.md", "bundle.json", "findings.json")

            if is_critical:
                # Use smart compression for critical docs (sync, no LLM)
                try:
                    from apps.services.gateway.document_compressor import DocumentCompressor
                    compressor = DocumentCompressor()
                    result = compressor.compress_sync(content, budget)
                    content = result.compressed_text
                    tokens = result.compressed_tokens
                    self.trimming_log.append(
                        f"Smart-compressed {name}: {original_tokens} → {tokens} tokens "
                        f"(strategy={result.strategy_used.value}, critical=True)"
                    )
                    logger.info(f"[DocPack] Smart-compressed critical doc {name}: {original_tokens} → {tokens} tokens")
                except Exception as e:
                    logger.warning(f"[DocPack] Smart compression failed for {name}: {e}, using truncation")
                    content = self._truncate_to_tokens(content, budget)
                    tokens = count_tokens(content)
                    self.trimming_log.append(
                        f"Trimmed {name}: {original_tokens} → {tokens} tokens (critical fallback)"
                    )
            else:
                content = self._truncate_to_tokens(content, budget)
                tokens = count_tokens(content)
                self.trimming_log.append(
                    f"Trimmed {name}: {original_tokens} → {tokens} tokens (budget: {budget})"
                )
                logger.info(f"[DocPack] Trimmed {name}: {original_tokens} → {tokens} tokens")

        self.items.append(DocItem(
            name=name,
            content=content,
            tokens=tokens,
            source="input_doc",
            trimmed=(tokens < original_tokens),
            original_tokens=original_tokens if tokens < original_tokens else None
        ))

        logger.debug(f"[DocPack] Added doc {name} ({tokens} tokens)")

    def add_doc_smart(
        self,
        name: str,
        content: str,
        budget: Optional[int] = None,
        compression_context: str = "",
    ) -> None:
        """
        Add document with intelligent compression (sync, no LLM).

        Uses key sentence extraction instead of dumb truncation.
        This preserves more semantic meaning when compressing documents.

        Args:
            name: Document name
            content: Document content
            budget: Token budget for this document
            compression_context: Context hint for compression (e.g., "product research")
        """
        tokens = count_tokens(content)
        original_tokens = tokens

        if budget and tokens > budget:
            try:
                from apps.services.gateway.document_compressor import (
                    DocumentCompressor,
                    CompressionStrategy
                )

                compressor = DocumentCompressor()

                # CRITICAL DOCS: Force EXTRACT_KEY strategy (never truncate)
                is_critical = name in ("context.md", "bundle.json", "findings.json")

                if is_critical:
                    # Force key extraction for critical docs - never use truncation
                    result = compressor.compress_sync(
                        content,
                        budget,
                        strategy=CompressionStrategy.EXTRACT_KEY
                    )
                else:
                    result = compressor.compress_sync(content, budget)

                content = result.compressed_text
                tokens = result.compressed_tokens

                self.trimming_log.append(
                    f"Smart-compressed {name}: {original_tokens} → {tokens} tokens "
                    f"(strategy={result.strategy_used.value}, quality={result.quality_estimate:.2f}"
                    f"{', critical=True' if is_critical else ''})"
                )
                logger.info(
                    f"[DocPack] Smart-compressed {name}: {original_tokens} → {tokens} tokens "
                    f"(strategy={result.strategy_used.value}{', critical' if is_critical else ''})"
                )
            except ImportError:
                # Fallback to simple truncation
                logger.warning("[DocPack] DocumentCompressor not available, using truncation")
                content = self._truncate_to_tokens(content, budget)
                tokens = count_tokens(content)
                self.trimming_log.append(
                    f"Truncated {name}: {original_tokens} → {tokens} tokens (fallback)"
                )
            except Exception as e:
                # Any other error, fallback to truncation
                logger.warning(f"[DocPack] Smart compression failed: {e}, using truncation")
                content = self._truncate_to_tokens(content, budget)
                tokens = count_tokens(content)
                self.trimming_log.append(
                    f"Truncated {name}: {original_tokens} → {tokens} tokens (error fallback)"
                )

        self.items.append(DocItem(
            name=name,
            content=content,
            tokens=tokens,
            source="input_doc",
            trimmed=(tokens < original_tokens),
            original_tokens=original_tokens if tokens < original_tokens else None
        ))

        logger.debug(f"[DocPack] Added doc {name} ({tokens} tokens)")

    async def add_doc_llm(
        self,
        name: str,
        content: str,
        budget: Optional[int] = None,
        compression_context: str = "",
    ) -> None:
        """
        Add document with LLM-based compression when needed (async).

        Uses LLM summarization for high-quality compression when the compression
        ratio requires significant reduction. Falls back to key extraction for
        moderate compression.

        Args:
            name: Document name
            content: Document content
            budget: Token budget for this document
            compression_context: Context hint for compression (e.g., "product research")
        """
        tokens = count_tokens(content)
        original_tokens = tokens

        if budget and tokens > budget:
            try:
                from apps.services.gateway.document_compressor import (
                    DocumentCompressor,
                    CompressionStrategy
                )

                compressor = DocumentCompressor()
                compression_ratio = budget / tokens

                # CRITICAL DOCS: Always use LLM for context.md (contains structured claims)
                # Simple truncation would lose products entirely - unacceptable
                is_critical = name in ("context.md", "bundle.json", "findings.json")

                if is_critical or compression_ratio < 0.4:
                    # Critical doc or heavy compression - use LLM SUMMARIZE
                    # For context.md, LLM understands markdown structure and preserves claims
                    result = await compressor.compress(
                        content,
                        budget,
                        context=compression_context or f"compressing {name}",
                        strategy=CompressionStrategy.SUMMARIZE,
                        force_llm=is_critical  # Force LLM even for smaller docs
                    )
                elif compression_ratio < 0.6:
                    # Moderate compression - use key extraction (sync, no LLM)
                    result = compressor.compress_sync(content, budget)
                else:
                    # Light compression - simple truncation
                    result = compressor.compress_sync(
                        content,
                        budget,
                        strategy=CompressionStrategy.TRUNCATE
                    )

                content = result.compressed_text
                tokens = result.compressed_tokens
                llm_cost = result.llm_tokens_used

                # Track LLM token cost for budget awareness
                llm_cost_str = f", llm_cost={llm_cost}" if llm_cost > 0 else ""
                self.trimming_log.append(
                    f"LLM-compressed {name}: {original_tokens} → {tokens} tokens "
                    f"(strategy={result.strategy_used.value}, quality={result.quality_estimate:.2f}{llm_cost_str})"
                )
                logger.info(
                    f"[DocPack] LLM-compressed {name}: {original_tokens} → {tokens} tokens "
                    f"(strategy={result.strategy_used.value}, quality={result.quality_estimate:.2f}{llm_cost_str})"
                )

            except ImportError:
                logger.warning("[DocPack] DocumentCompressor not available, using truncation")
                content = self._truncate_to_tokens(content, budget)
                tokens = count_tokens(content)
                self.trimming_log.append(
                    f"Truncated {name}: {original_tokens} → {tokens} tokens (import fallback)"
                )
            except Exception as e:
                logger.warning(f"[DocPack] LLM compression failed: {e}, using sync fallback")
                try:
                    from apps.services.gateway.document_compressor import DocumentCompressor
                    compressor = DocumentCompressor()
                    result = compressor.compress_sync(content, budget)
                    content = result.compressed_text
                    tokens = result.compressed_tokens
                    self.trimming_log.append(
                        f"Sync-compressed {name}: {original_tokens} → {tokens} tokens "
                        f"(strategy={result.strategy_used.value}, fallback)"
                    )
                except Exception:
                    content = self._truncate_to_tokens(content, budget)
                    tokens = count_tokens(content)
                    self.trimming_log.append(
                        f"Truncated {name}: {original_tokens} → {tokens} tokens (error fallback)"
                    )

        self.items.append(DocItem(
            name=name,
            content=content,
            tokens=tokens,
            source="input_doc",
            trimmed=(tokens < original_tokens),
            original_tokens=original_tokens if tokens < original_tokens else None
        ))

        logger.debug(f"[DocPack] Added doc {name} ({tokens} tokens)")

    def reserve_output_budget(self, tokens: int):
        """Reserve budget for expected output"""
        self.output_budget_reserved = tokens
        logger.debug(f"[DocPack] Reserved {tokens} tokens for output")

    def as_prompt(self) -> str:
        """
        Concatenate all items into final prompt string.

        Order: prompts first, then input docs
        """
        parts = []

        # Add prompts first
        for item in self.items:
            if item.source == "prompt":
                parts.append(item.content)

        # Add input docs
        for item in self.items:
            if item.source == "input_doc":
                parts.append(f"\n---\n# {item.name}\n\n{item.content}")

        return "\n\n".join(parts)

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics"""
        prompt_tokens = sum(item.tokens for item in self.items if item.source == "prompt")
        doc_tokens = sum(item.tokens for item in self.items if item.source == "input_doc")
        trimmed_count = sum(1 for item in self.items if item.trimmed)

        return {
            "recipe": self.recipe_name,
            "total_tokens": self.token_count,
            "budget": self.budget,
            "remaining": self.remaining_budget,
            "items": len(self.items),
            "prompt_tokens": prompt_tokens,
            "doc_tokens": doc_tokens,
            "output_reserved": self.output_budget_reserved,
            "trimmed_items": trimmed_count,
            "trimming_log": self.trimming_log
        }

    def _truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        """
        Truncate text to fit within token budget.

        Simple strategy: remove from end until fits.
        """
        if ENCODER:
            # Use tiktoken for accurate truncation
            tokens = ENCODER.encode(text)
            if len(tokens) <= max_tokens:
                return text
            truncated = tokens[:max_tokens]
            return ENCODER.decode(truncated)
        else:
            # Rough estimate: 4 chars ≈ 1 token
            target_chars = max_tokens * 4
            if len(text) <= target_chars:
                return text
            return text[:target_chars] + "\n[... truncated ...]"


class DocPackBuilder:
    """
    Builds document packs from recipes with hard budget enforcement.

    Usage:
        recipe = load_recipe("planner_chat")
        builder = DocPackBuilder()
        pack = builder.build(recipe, turn_dir)
        prompt = pack.as_prompt()

    Smart Compression (2025-11-26):
        # Use smart compression for better semantic preservation (sync)
        builder = DocPackBuilder(use_smart_compression=True)
        pack = builder.build(recipe, turn_dir)

    LLM Compression (2025-11-27):
        # Use LLM-based compression for highest quality (async)
        builder = DocPackBuilder(use_llm_compression=True)
        pack = await builder.build_async(recipe, turn_dir)
    """

    def __init__(self, use_smart_compression: bool = False, use_llm_compression: bool = False):
        """
        Initialize DocPackBuilder.

        Args:
            use_smart_compression: If True, use key sentence extraction instead
                                   of simple truncation when compressing documents.
                                   Default False for backward compatibility.
            use_llm_compression: If True, use LLM-based summarization for heavy
                                 compression (requires async build_async method).
        """
        self.use_smart_compression = use_smart_compression
        self.use_llm_compression = use_llm_compression

    def build(self, recipe: Recipe, turn_dir: 'TurnDirectory', budget_override: Optional[int] = None) -> DocPack:
        """
        Build document pack following recipe specification.

        Args:
            recipe: Recipe instance
            turn_dir: TurnDirectory instance with input docs
            budget_override: Optional budget override (from token governance reservation)

        Returns:
            DocPack with loaded docs, token counts, trimming log

        Raises:
            BudgetExceededError: If cannot fit within budget
            MissingDocError: If required doc not found
        """
        if not recipe.token_budget:
            raise ValueError(f"Recipe {recipe.name} missing token_budget")

        # Use budget override if provided (token governance enforcement)
        budget = budget_override if budget_override is not None else recipe.token_budget.total

        pack = DocPack(
            recipe_name=recipe.name,
            budget=budget
        )

        # 1. Load prompt fragments (fixed cost, non-negotiable)
        budget_source = "override" if budget_override else "recipe"
        logger.info(f"[DocPack] Building pack for {recipe.name} (budget: {budget} tokens, source: {budget_source})")

        for fragment_path in recipe.get_prompt_paths():
            content = fragment_path.read_text()
            pack.add_prompt(fragment_path, content)

        if pack.token_count > pack.budget:
            raise BudgetExceededError(
                f"Prompt fragments alone exceed budget: "
                f"{pack.token_count} > {pack.budget}"
            )

        logger.info(f"[DocPack] Loaded {len(recipe.prompt_fragments)} prompts ({pack.token_count} tokens)")

        # 2. Reserve output budget
        pack.reserve_output_budget(recipe.token_budget.output)

        # 3. Allocate budgets across input docs
        remaining_budget = pack.remaining_budget - recipe.token_budget.buffer
        doc_budgets = self._allocate_doc_budgets(recipe.input_docs, remaining_budget)

        # 4. Load input docs with budgets
        for doc_spec, doc_budget in doc_budgets.items():
            # Resolve path using doc_spec.path_type
            doc_path = turn_dir.doc_path(doc_spec.path, path_type=doc_spec.path_type)

            # Optional docs: skip if missing
            if not doc_path.exists():
                if doc_spec.optional:
                    pack.trimming_log.append(f"Skipped optional doc: {doc_spec.path} (path_type={doc_spec.path_type})")
                    logger.debug(f"[DocPack] Skipped optional doc: {doc_spec.path} (path_type={doc_spec.path_type})")
                    continue
                else:
                    raise MissingDocError(f"Required doc not found: {doc_spec.path} (path_type={doc_spec.path_type}, resolved={doc_path})")

            # Load content
            content = doc_path.read_text()

            # Add with budget (use smart compression if enabled)
            if self.use_smart_compression:
                pack.add_doc_smart(
                    doc_spec.path,
                    content,
                    budget=doc_budget,
                    compression_context=f"for {recipe.name}"
                )
            else:
                pack.add_doc(doc_spec.path, content, budget=doc_budget)

        # 5. Final budget check
        if pack.token_count > pack.budget:
            # Emergency trim using recipe strategy or default fallback
            strategy = recipe.trimming_strategy
            if not strategy:
                # Default fallback: truncate from end of input docs
                logger.warning(
                    f"[DocPack] No trimming strategy for {recipe.name}, using default truncate_end"
                )
                strategy = TrimStrategy(method="truncate_end", priority=["input_docs"])
            pack = self._apply_emergency_trim(pack, strategy, target=pack.budget)

        logger.info(
            f"[DocPack] Built {recipe.name}: {pack.token_count}/{pack.budget} tokens "
            f"({len(pack.items)} items, {len(pack.trimming_log)} trimmed)"
        )

        return pack

    async def build_async(
        self,
        recipe: Recipe,
        turn_dir: 'TurnDirectory',
        budget_override: Optional[int] = None
    ) -> DocPack:
        """
        Build document pack with LLM-based compression (async).

        Uses LLM summarization when heavy compression is needed (compression ratio < 0.4),
        providing higher quality summaries than simple truncation.

        Args:
            recipe: Recipe instance
            turn_dir: TurnDirectory instance with input docs
            budget_override: Optional budget override (from token governance reservation)

        Returns:
            DocPack with loaded docs, token counts, trimming log

        Raises:
            BudgetExceededError: If cannot fit within budget
            MissingDocError: If required doc not found
        """
        if not recipe.token_budget:
            raise ValueError(f"Recipe {recipe.name} missing token_budget")

        # Use budget override if provided (token governance enforcement)
        budget = budget_override if budget_override is not None else recipe.token_budget.total

        pack = DocPack(
            recipe_name=recipe.name,
            budget=budget
        )

        # 1. Load prompt fragments (fixed cost, non-negotiable)
        budget_source = "override" if budget_override else "recipe"
        logger.info(f"[DocPack] Building async pack for {recipe.name} (budget: {budget} tokens, source: {budget_source})")

        for fragment_path in recipe.get_prompt_paths():
            content = fragment_path.read_text()
            pack.add_prompt(fragment_path, content)

        if pack.token_count > pack.budget:
            raise BudgetExceededError(
                f"Prompt fragments alone exceed budget: "
                f"{pack.token_count} > {pack.budget}"
            )

        logger.info(f"[DocPack] Loaded {len(recipe.prompt_fragments)} prompts ({pack.token_count} tokens)")

        # 2. Reserve output budget
        pack.reserve_output_budget(recipe.token_budget.output)

        # 3. Allocate budgets across input docs
        remaining_budget = pack.remaining_budget - recipe.token_budget.buffer
        doc_budgets = self._allocate_doc_budgets(recipe.input_docs, remaining_budget)

        # 4. Load input docs with budgets (using LLM compression when enabled)
        for doc_spec, doc_budget in doc_budgets.items():
            # Resolve path using doc_spec.path_type
            doc_path = turn_dir.doc_path(doc_spec.path, path_type=doc_spec.path_type)

            # Optional docs: skip if missing
            if not doc_path.exists():
                if doc_spec.optional:
                    pack.trimming_log.append(f"Skipped optional doc: {doc_spec.path} (path_type={doc_spec.path_type})")
                    logger.debug(f"[DocPack] Skipped optional doc: {doc_spec.path} (path_type={doc_spec.path_type})")
                    continue
                else:
                    raise MissingDocError(f"Required doc not found: {doc_spec.path} (path_type={doc_spec.path_type}, resolved={doc_path})")

            # Load content
            content = doc_path.read_text()

            # Use LLM compression when enabled, otherwise fall back to smart/simple
            if self.use_llm_compression:
                await pack.add_doc_llm(
                    doc_spec.path,
                    content,
                    budget=doc_budget,
                    compression_context=f"for {recipe.name}"
                )
            elif self.use_smart_compression:
                pack.add_doc_smart(
                    doc_spec.path,
                    content,
                    budget=doc_budget,
                    compression_context=f"for {recipe.name}"
                )
            else:
                pack.add_doc(doc_spec.path, content, budget=doc_budget)

        # 5. Final budget check
        if pack.token_count > pack.budget:
            # Emergency trim using recipe strategy or default fallback
            strategy = recipe.trimming_strategy
            if not strategy:
                # Default fallback: truncate from end of input docs
                logger.warning(
                    f"[DocPack] No trimming strategy for {recipe.name}, using default truncate_end"
                )
                strategy = TrimStrategy(method="truncate_end", priority=["input_docs"])
            pack = self._apply_emergency_trim(pack, strategy, target=pack.budget)

        logger.info(
            f"[DocPack] Built async {recipe.name}: {pack.token_count}/{pack.budget} tokens "
            f"({len(pack.items)} items, {len(pack.trimming_log)} trimmed)"
        )

        return pack

    def _allocate_doc_budgets(
        self,
        doc_specs: List[DocSpec],
        total_budget: int
    ) -> Dict[DocSpec, int]:
        """
        Allocate budget across input docs.

        Priority:
        1. Docs with explicit max_tokens get their allocation
        2. Remaining budget split equally among others
        """
        budgets = {}
        allocated = 0

        # First pass: explicit budgets
        for spec in doc_specs:
            if spec.max_tokens:
                budgets[spec] = spec.max_tokens
                allocated += spec.max_tokens

        # Second pass: split remaining
        remaining_docs = [s for s in doc_specs if not s.max_tokens]
        if remaining_docs and total_budget > allocated:
            per_doc = (total_budget - allocated) // len(remaining_docs)
            for spec in remaining_docs:
                budgets[spec] = max(per_doc, 100)  # Minimum 100 tokens per doc

        return budgets

    def _apply_emergency_trim(self, pack: DocPack, strategy: TrimStrategy, target: int) -> DocPack:
        """
        Apply emergency trimming if pack exceeds budget.

        Strategies:
        - truncate_end: Remove from bottom of input docs
        - drop_oldest: Remove oldest items (not implemented yet)
        - summarize: LLM compression (not implemented yet)
        """
        if strategy.method == "truncate_end":
            # Find input docs and trim from end until under budget
            excess = pack.token_count - target
            logger.warning(f"[DocPack] Emergency trim: {excess} tokens over budget")

            for item in reversed(pack.items):
                if item.source == "input_doc" and excess > 0:
                    # Trim this doc
                    trim_amount = min(excess, item.tokens // 2)  # Max 50% trim per doc
                    new_tokens = item.tokens - trim_amount
                    item.content = pack._truncate_to_tokens(item.content, new_tokens)
                    item.tokens = count_tokens(item.content)
                    item.trimmed = True
                    pack.trimming_log.append(
                        f"Emergency trim {item.name}: {item.original_tokens or item.tokens + trim_amount} → {item.tokens}"
                    )
                    excess -= trim_amount

                    if pack.token_count <= target:
                        break

        return pack


class BudgetExceededError(Exception):
    """Raised when doc pack exceeds token budget"""
    pass


class MissingDocError(Exception):
    """Raised when required document not found"""
    pass
