"""
Document Compressor - Universal LLM-based document compression.

This service compresses any text that's too large for an LLM context window.
It can be called from anywhere in the system.

Key Features:
- Multiple compression strategies (truncate, extract_key, summarize, bullet_points)
- Both sync and async interfaces
- Sync fallback uses key sentence extraction (no LLM)
- Async can use LLM for smarter compression
- Token-based truncation (not character-based)

Quality Agent Review (2025-11-26):
- Uses dependency injection instead of singleton pattern
- Provides sync fallback for DocPackBuilder integration
- Uses tiktoken for accurate token counting
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from enum import Enum
import re
import logging

logger = logging.getLogger(__name__)

# Token counter
try:
    import tiktoken
    ENCODER = tiktoken.get_encoding("cl100k_base")  # GPT-4 encoding
except ImportError:
    logger.warning("[DocumentCompressor] tiktoken not available, using estimate")
    ENCODER = None


class CompressionStrategy(Enum):
    """Compression strategies ordered by quality/cost."""
    TRUNCATE = "truncate"           # Fast, dumb - just cut from end
    EXTRACT_KEY = "extract_key"     # Extract key sentences (no LLM)
    SUMMARIZE = "summarize"         # LLM summarization
    BULLET_POINTS = "bullet_points" # LLM → bullet points


@dataclass
class CompressionResult:
    """Result of document compression."""
    original_text: str
    compressed_text: str
    original_tokens: int
    compressed_tokens: int
    strategy_used: CompressionStrategy
    compression_ratio: float  # compressed/original
    quality_estimate: float   # 0.0-1.0 - how much info preserved
    metadata: Dict[str, Any] = field(default_factory=dict)
    llm_tokens_used: int = 0  # Track LLM call cost (prompt + output) for budget accounting


@dataclass
class CompressorConfig:
    """Configuration for document compression."""
    # LLM settings (for async compression)
    solver_url: str = "http://localhost:8000/v1/chat/completions"
    solver_model: str = "qwen3-coder"
    solver_api_key: str = "qwen-local"
    timeout: float = 15.0

    # Strategy selection thresholds
    llm_threshold_tokens: int = 500  # Use LLM if doc > 500 tokens AND needs compression
    max_llm_input_tokens: int = 2000  # Don't send more than this to compressor LLM

    # Output limits
    temperature: float = 0.3


COMPRESSION_PROMPT = '''You are a Document Compressor. Compress the following text while preserving all critical information.

## Strategy: {strategy}

{strategy_instructions}

## Document to Compress
```
{document}
```

## Target: {target_tokens} tokens maximum

## Output
{output_format}
'''

STRATEGY_INSTRUCTIONS = {
    CompressionStrategy.SUMMARIZE: """
Create a concise summary that preserves:
- ALL product/item entries (name, price, vendor, URL) - NEVER drop products
- Key facts, numbers, prices, dates
- Important names, entities, products
- Main conclusions or findings
- Critical caveats or warnings

IMPORTANT: If the document contains multiple products/claims, preserve ALL of them.
Each product should keep: name, price, vendor, and URL (full URL required).
""",
    CompressionStrategy.BULLET_POINTS: """
Extract key information as bullet points:
- One bullet per key fact
- Include numbers, prices, URLs
- Preserve product names exactly
- Max 10 bullets
""",
    CompressionStrategy.EXTRACT_KEY: """
Extract the most important sentences verbatim:
- Sentences with numbers, prices, conclusions
- Opening and closing statements
- Any sentences with critical keywords
"""
}


def count_tokens(text: str) -> int:
    """
    Count tokens in text using tiktoken.

    Falls back to character estimate if tiktoken unavailable.
    """
    if ENCODER:
        return len(ENCODER.encode(text))
    return len(text) // 4  # Fallback estimate


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """
    Truncate text to fit within token budget.

    Uses tiktoken for accurate truncation, tries to end at sentence boundary.
    """
    current_tokens = count_tokens(text)
    if current_tokens <= max_tokens:
        return text

    if ENCODER:
        tokens = ENCODER.encode(text)
        truncated_tokens = tokens[:max_tokens]
        truncated = ENCODER.decode(truncated_tokens)
    else:
        # Character-based fallback
        char_ratio = len(text) / max(current_tokens, 1)
        target_chars = int(max_tokens * char_ratio)
        truncated = text[:target_chars]

    # Try to end at sentence boundary
    last_period = truncated.rfind('.')
    last_question = truncated.rfind('?')
    last_exclaim = truncated.rfind('!')
    last_sentence = max(last_period, last_question, last_exclaim)

    if last_sentence > len(truncated) * 0.7:
        return truncated[:last_sentence + 1]

    # Try word boundary
    last_space = truncated.rfind(' ')
    if last_space > len(truncated) * 0.8:
        return truncated[:last_space] + "..."

    return truncated.rstrip() + "..."


class DocumentCompressor:
    """
    Universal document compression service.

    Provides both sync and async interfaces:
    - compress_sync(): Uses key sentence extraction (no LLM, fast)
    - compress(): Uses LLM when beneficial (slower, smarter)

    Usage:
        compressor = DocumentCompressor(config)

        # Sync (for DocPackBuilder)
        result = compressor.compress_sync(text, target_tokens=500)

        # Async (when LLM compression is worth it)
        result = await compressor.compress(text, target_tokens=500, context="product research")
    """

    def __init__(self, config: Optional[CompressorConfig] = None):
        self.config = config or CompressorConfig()

    def compress_sync(
        self,
        text: str,
        target_tokens: int,
        strategy: Optional[CompressionStrategy] = None,
    ) -> CompressionResult:
        """
        Synchronous compression (no LLM calls).

        Use this when you need compression without async context,
        such as in DocPackBuilder.

        Args:
            text: Document to compress
            target_tokens: Target output size in tokens
            strategy: Compression strategy (auto-selected if None, but no LLM strategies)

        Returns:
            CompressionResult with compressed text
        """
        original_tokens = count_tokens(text)

        # No compression needed
        if original_tokens <= target_tokens:
            return CompressionResult(
                original_text=text,
                compressed_text=text,
                original_tokens=original_tokens,
                compressed_tokens=original_tokens,
                strategy_used=CompressionStrategy.TRUNCATE,
                compression_ratio=1.0,
                quality_estimate=1.0,
                metadata={"action": "no_compression_needed"}
            )

        # Select sync-compatible strategy
        if strategy in (CompressionStrategy.SUMMARIZE, CompressionStrategy.BULLET_POINTS):
            # Can't use LLM strategies in sync mode, downgrade
            strategy = CompressionStrategy.EXTRACT_KEY
            logger.debug("[DocumentCompressor] Downgraded to EXTRACT_KEY for sync mode")

        if strategy is None:
            compression_ratio = target_tokens / original_tokens
            # For moderate compression, use key extraction
            if compression_ratio > 0.3:
                strategy = CompressionStrategy.EXTRACT_KEY
            else:
                # For extreme compression, truncation is safer
                strategy = CompressionStrategy.TRUNCATE

        # Apply compression
        if strategy == CompressionStrategy.TRUNCATE:
            return self._truncate(text, target_tokens, original_tokens)
        else:
            return self._extract_key_sentences(text, target_tokens, original_tokens)

    async def compress(
        self,
        text: str,
        target_tokens: int,
        context: str = "",
        strategy: Optional[CompressionStrategy] = None,
        force_llm: bool = False,
    ) -> CompressionResult:
        """
        Asynchronous compression with optional LLM.

        Args:
            text: Document to compress
            target_tokens: Target output size in tokens
            context: Why this doc is being compressed (helps LLM prioritize)
            strategy: Compression strategy (auto-selected if None)
            force_llm: Force LLM compression even for small docs

        Returns:
            CompressionResult with compressed text and metadata
        """
        original_tokens = count_tokens(text)

        # No compression needed
        if original_tokens <= target_tokens:
            return CompressionResult(
                original_text=text,
                compressed_text=text,
                original_tokens=original_tokens,
                compressed_tokens=original_tokens,
                strategy_used=CompressionStrategy.TRUNCATE,
                compression_ratio=1.0,
                quality_estimate=1.0,
                metadata={"action": "no_compression_needed"}
            )

        # Select strategy
        if strategy is None:
            strategy = self._select_strategy(original_tokens, target_tokens, force_llm)

        # Apply compression
        if strategy == CompressionStrategy.TRUNCATE:
            return self._truncate(text, target_tokens, original_tokens)
        elif strategy == CompressionStrategy.EXTRACT_KEY:
            return self._extract_key_sentences(text, target_tokens, original_tokens)
        else:
            # LLM-based compression
            return await self._llm_compress(text, target_tokens, original_tokens, strategy, context)

    def _select_strategy(
        self,
        original_tokens: int,
        target_tokens: int,
        force_llm: bool
    ) -> CompressionStrategy:
        """Auto-select best compression strategy."""
        compression_ratio = target_tokens / original_tokens

        # For small docs or minimal compression, use simple methods
        if not force_llm and original_tokens < self.config.llm_threshold_tokens:
            if compression_ratio > 0.5:
                return CompressionStrategy.TRUNCATE
            return CompressionStrategy.EXTRACT_KEY

        # For moderate compression (>50% retained), extract key sentences
        if compression_ratio > 0.5:
            return CompressionStrategy.EXTRACT_KEY

        # For heavy compression (<50% retained), use LLM summarization
        if compression_ratio > 0.2:
            return CompressionStrategy.SUMMARIZE

        # For extreme compression (<20% retained), use bullet points
        return CompressionStrategy.BULLET_POINTS

    def _truncate(
        self,
        text: str,
        target_tokens: int,
        original_tokens: int
    ) -> CompressionResult:
        """Simple truncation (fast, no LLM)."""
        compressed = truncate_to_tokens(text, target_tokens)
        compressed_tokens = count_tokens(compressed)

        return CompressionResult(
            original_text=text,
            compressed_text=compressed,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            strategy_used=CompressionStrategy.TRUNCATE,
            compression_ratio=compressed_tokens / max(original_tokens, 1),
            quality_estimate=0.4,  # Low - loses end content
            metadata={"method": "token_truncate"}
        )

    def _extract_key_sentences(
        self,
        text: str,
        target_tokens: int,
        original_tokens: int
    ) -> CompressionResult:
        """Extract key sentences/lines without LLM."""
        # For markdown/structured content, split on newlines first, then sentences
        # This handles capsule.md format: "- **Product:** Name\n- **Price:** $X"
        if '\n' in text and ('**' in text or '###' in text or '- ' in text):
            # Markdown content - split on newlines to preserve structure
            sentences = [line.strip() for line in text.split('\n') if line.strip()]
        else:
            # Regular prose - split on sentence boundaries
            sentences = re.split(r'(?<=[.!?])\s+', text)

        if not sentences:
            return self._truncate(text, target_tokens, original_tokens)

        # Score sentences by importance
        keywords = [
            'price', 'cost', '$', 'found', 'result', 'error', 'success',
            'recommend', 'best', 'important', 'note', 'warning', 'total',
            'available', 'in stock', 'sold out', 'conclusion', 'summary',
            'key', 'critical', 'must', 'should', 'however', 'but', 'therefore'
        ]

        # High-priority markers for product/claim content
        product_markers = ['**product', '**price', '**vendor', '**url', '🔗', 'claim', 'http']

        scored = []
        for i, sent in enumerate(sentences):
            if not sent.strip():
                continue

            score = 0
            sent_lower = sent.lower()

            # Position score (first and last sentences important)
            if i == 0:
                score += 5
            elif i == len(sentences) - 1:
                score += 3
            elif i < 3:
                score += 2  # Early sentences often important

            # Keyword score
            for kw in keywords:
                if kw in sent_lower:
                    score += 2

            # HIGH PRIORITY: Product/claim markers (never drop these)
            for marker in product_markers:
                if marker in sent_lower:
                    score += 5  # High score to ensure product lines are kept

            # Number score (sentences with numbers often important)
            if re.search(r'\d+', sent):
                score += 2

            # Currency score
            if re.search(r'\$[\d,]+', sent):
                score += 3

            # URL score
            if 'http' in sent or '.com' in sent:
                score += 2

            # Length penalty (very short sentences less useful)
            word_count = len(sent.split())
            if word_count < 5:
                score -= 1
            elif word_count > 20:
                score += 1  # More detailed sentences often important

            scored.append((score, i, sent))

        # Sort by score (highest first), then by position for ties
        scored.sort(key=lambda x: (-x[0], x[1]))

        # Take top sentences until budget
        selected_indices = set()
        current_tokens = 0

        for score, idx, sent in scored:
            sent_tokens = count_tokens(sent)
            if current_tokens + sent_tokens <= target_tokens:
                selected_indices.add(idx)
                current_tokens += sent_tokens

        # Reconstruct in original order
        result_sentences = []
        for i, sent in enumerate(sentences):
            if i in selected_indices:
                result_sentences.append(sent)

        compressed = ' '.join(result_sentences)

        # If still empty, fall back to truncation
        if not compressed.strip():
            return self._truncate(text, target_tokens, original_tokens)

        compressed_tokens = count_tokens(compressed)

        return CompressionResult(
            original_text=text,
            compressed_text=compressed,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            strategy_used=CompressionStrategy.EXTRACT_KEY,
            compression_ratio=compressed_tokens / max(original_tokens, 1),
            quality_estimate=0.7,  # Medium - keeps key sentences
            metadata={
                "sentences_kept": len(selected_indices),
                "sentences_total": len(sentences)
            }
        )

    async def _llm_compress(
        self,
        text: str,
        target_tokens: int,
        original_tokens: int,
        strategy: CompressionStrategy,
        context: str,
    ) -> CompressionResult:
        """LLM-based compression."""
        import httpx

        # Truncate input if too long for compressor
        input_text = text
        if original_tokens > self.config.max_llm_input_tokens:
            input_text = truncate_to_tokens(text, self.config.max_llm_input_tokens)
            logger.debug(
                f"[DocumentCompressor] Truncated input from {original_tokens} to "
                f"{self.config.max_llm_input_tokens} tokens before LLM compression"
            )

        # Build prompt
        strategy_instructions = STRATEGY_INSTRUCTIONS.get(
            strategy,
            "Summarize concisely while preserving key facts."
        )

        if strategy == CompressionStrategy.BULLET_POINTS:
            output_format = "Output bullet points only, one per line starting with -"
        else:
            output_format = "Output compressed text only, no explanation or preamble."

        prompt = COMPRESSION_PROMPT.format(
            strategy=strategy.value,
            strategy_instructions=strategy_instructions,
            document=input_text,
            target_tokens=target_tokens,
            output_format=output_format,
        )

        if context:
            prompt += f"\n\n## Context\nThis document is being compressed for: {context}"

        # Validate total input size
        prompt_tokens = count_tokens(prompt)
        if prompt_tokens > 8000:
            logger.warning(
                f"[DocumentCompressor] Prompt too large ({prompt_tokens} tokens), "
                "falling back to key extraction"
            )
            return self._extract_key_sentences(text, target_tokens, original_tokens)

        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.post(
                    self.config.solver_url,
                    headers={
                        "Authorization": f"Bearer {self.config.solver_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.config.solver_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": target_tokens + 100,  # Buffer for formatting
                        "temperature": self.config.temperature,
                    }
                )
                response.raise_for_status()

                data = response.json()
                compressed = data["choices"][0]["message"]["content"].strip()

                # Extract token usage from response (vLLM format)
                usage = data.get("usage", {})
                llm_prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                llm_completion_tokens = usage.get("completion_tokens", 0)
                llm_total_tokens = llm_prompt_tokens + llm_completion_tokens

                # Clean up common LLM artifacts
                compressed = self._clean_llm_output(compressed)

                compressed_tokens = count_tokens(compressed)

                # If still over budget, truncate
                if compressed_tokens > target_tokens:
                    compressed = truncate_to_tokens(compressed, target_tokens)
                    compressed_tokens = count_tokens(compressed)

                logger.info(
                    f"[DocumentCompressor] LLM compression used {llm_total_tokens} tokens "
                    f"(prompt={llm_prompt_tokens}, completion={llm_completion_tokens})"
                )

                return CompressionResult(
                    original_text=text,
                    compressed_text=compressed,
                    original_tokens=original_tokens,
                    compressed_tokens=compressed_tokens,
                    strategy_used=strategy,
                    compression_ratio=compressed_tokens / max(original_tokens, 1),
                    quality_estimate=0.85,  # High - LLM preserves semantics
                    metadata={
                        "llm_model": self.config.solver_model,
                        "context": context[:100] if context else None,
                        "prompt_tokens": llm_prompt_tokens,
                        "completion_tokens": llm_completion_tokens,
                    },
                    llm_tokens_used=llm_total_tokens
                )

        except Exception as e:
            logger.error(f"[DocumentCompressor] LLM compression failed: {e}")
            # Fallback to key sentence extraction
            return self._extract_key_sentences(text, target_tokens, original_tokens)

    def _clean_llm_output(self, text: str) -> str:
        """Clean common LLM output artifacts."""
        # Remove markdown code blocks if present
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)

        # Remove common preambles
        preambles = [
            "Here is the compressed text:",
            "Here's the summary:",
            "Summary:",
            "Compressed version:",
        ]
        for preamble in preambles:
            if text.lower().startswith(preamble.lower()):
                text = text[len(preamble):].strip()

        return text.strip()


# Convenience functions for easy import

def compress_document_sync(
    text: str,
    target_tokens: int,
    config: Optional[CompressorConfig] = None,
) -> CompressionResult:
    """
    Synchronous document compression (no LLM).

    Usage:
        result = compress_document_sync(long_text, target_tokens=500)
        print(result.compressed_text)
    """
    compressor = DocumentCompressor(config)
    return compressor.compress_sync(text, target_tokens)


async def compress_document(
    text: str,
    target_tokens: int,
    context: str = "",
    strategy: Optional[CompressionStrategy] = None,
    config: Optional[CompressorConfig] = None,
) -> CompressionResult:
    """
    Asynchronous document compression with optional LLM.

    Usage:
        result = await compress_document(
            text=long_document,
            target_tokens=500,
            context="for product research capsule"
        )
        print(result.compressed_text)
    """
    compressor = DocumentCompressor(config)
    return await compressor.compress(text, target_tokens, context, strategy)
