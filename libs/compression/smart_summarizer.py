"""Smart Summarizer for PandaAI v2.

Handles auto-compression of context.md sections using NERVES role (MIND @ temp=0.1).
Triggered when sections exceed their word budget.

Reference: architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md Section 3
Reference: architecture/LLM-ROLES/llm-roles-reference.md (NERVES Background Services)
"""

import logging
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

from libs.compression.section_budgets import (
    get_word_count,
    get_section_budget,
    is_over_budget,
    should_compress,
    get_compression_target,
    get_budget_status,
)
from libs.compression.content_types import (
    ContentType,
    get_compression_strategy,
    detect_content_type,
    build_preservation_prompt,
)

logger = logging.getLogger(__name__)


@dataclass
class CompressionResult:
    """Result of a compression operation.

    Attributes:
        success: Whether compression succeeded
        original_content: Original input content
        compressed_content: Compressed output (or original if failed)
        original_words: Word count before compression
        compressed_words: Word count after compression
        compression_ratio: Ratio of compressed to original (lower is better)
        verification_score: Score from fact verification (0.0-1.0)
        verification_passed: Whether verification passed (>= 0.80)
        key_facts_preserved: Number of key facts preserved
        key_facts_total: Total key facts extracted
        content_type: Type of content compressed
        section_num: Section number (if applicable)
        budget: Target budget
        attempts: Number of compression attempts made
        duration_ms: Time taken for compression
        error: Error message if failed
    """

    success: bool
    original_content: str
    compressed_content: str
    original_words: int
    compressed_words: int
    compression_ratio: float
    verification_score: float
    verification_passed: bool
    key_facts_preserved: int
    key_facts_total: int
    content_type: ContentType
    section_num: Optional[int] = None
    budget: Optional[int] = None
    attempts: int = 1
    duration_ms: int = 0
    error: Optional[str] = None


class SmartSummarizer:
    """
    Smart compression using NERVES role (MIND @ temp=0.1).

    Handles auto-compression when context.md sections exceed budgets.
    Uses a 3-stage verification process:
    1. Extract key facts from original (REFLEX)
    2. Compress content (NERVES)
    3. Verify facts preserved in compressed (REFLEX)

    Usage:
        summarizer = SmartSummarizer(llm_client)
        result = await summarizer.compress_if_needed(4, section_content)
        if result.success:
            use(result.compressed_content)
    """

    # NERVES uses MIND model with temp=0.1 for deterministic compression
    NERVES_TEMPERATURE = 0.1
    NERVES_MODEL_LAYER = "mind"  # Uses MIND model

    # REFLEX temperature for fact extraction/verification
    REFLEX_TEMPERATURE = 0.3

    def __init__(self, llm_client=None):
        """
        Initialize SmartSummarizer.

        Args:
            llm_client: Optional LLM client instance. If not provided,
                       will use get_llm_client() when needed.
        """
        self._llm_client = llm_client

    async def _get_client(self):
        """Get or create LLM client."""
        if self._llm_client is None:
            from libs.llm.client import get_llm_client
            self._llm_client = get_llm_client()
        return self._llm_client

    def check_section_size(self, section_num: int, content: str) -> dict:
        """
        Check if a section exceeds its word budget.

        Args:
            section_num: Section number (0-6)
            content: Section content to check

        Returns:
            Budget status dict with word_count, budget, utilization, etc.
        """
        return get_budget_status(section_num, content)

    async def compress_section(
        self,
        section_num: int,
        content: str,
        content_type: Optional[ContentType] = None,
    ) -> CompressionResult:
        """
        Compress a section using NERVES role.

        Uses the full 3-stage verification process:
        1. Extract key facts (REFLEX)
        2. Compress (NERVES)
        3. Verify facts preserved (REFLEX)

        Args:
            section_num: Section number (0-6) for budget
            content: Content to compress
            content_type: Optional content type override

        Returns:
            CompressionResult with compressed content and metrics
        """
        start_time = datetime.now()
        original_words = get_word_count(content)
        budget = get_section_budget(section_num)
        target_words = get_compression_target(section_num)

        # Detect or use provided content type
        if content_type is None:
            content_type = detect_content_type(content)

        strategy = get_compression_strategy(content_type)

        client = await self._get_client()

        # Track attempts for retry logic
        attempts = 0
        current_budget = target_words
        best_result = None

        while attempts < strategy.max_attempts:
            attempts += 1

            try:
                # Stage 1: Extract key facts using REFLEX
                key_facts = await self._extract_key_facts(client, content)

                if not key_facts:
                    logger.warning("Failed to extract key facts from content")
                    key_facts = []

                # Stage 2: Compress using NERVES
                compressed = await self._compress_content(
                    client, content, current_budget, strategy
                )

                compressed_words = get_word_count(compressed)
                compression_ratio = compressed_words / original_words if original_words > 0 else 0

                # Stage 3: Verify facts preserved using REFLEX
                from libs.compression.compression_verifier import CompressionVerifier
                verifier = CompressionVerifier(client)
                verification = await verifier.verify_compression(
                    original=content,
                    compressed=compressed,
                    key_facts=key_facts,
                )

                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                result = CompressionResult(
                    success=verification["passed"],
                    original_content=content,
                    compressed_content=compressed,
                    original_words=original_words,
                    compressed_words=compressed_words,
                    compression_ratio=compression_ratio,
                    verification_score=verification["score"],
                    verification_passed=verification["passed"],
                    key_facts_preserved=verification["facts_preserved"],
                    key_facts_total=verification["facts_total"],
                    content_type=content_type,
                    section_num=section_num,
                    budget=budget,
                    attempts=attempts,
                    duration_ms=duration_ms,
                )

                # Check verification score and decide action
                if verification["score"] >= 0.90:
                    # Accept compression
                    logger.info(
                        f"Compression accepted: {original_words} -> {compressed_words} words "
                        f"({compression_ratio:.2%}), verification: {verification['score']:.2%}"
                    )
                    return result

                elif verification["score"] >= 0.80:
                    # Accept with warning
                    logger.warning(
                        f"Compression accepted with warning: verification score "
                        f"{verification['score']:.2%} (threshold 0.80)"
                    )
                    return result

                elif verification["score"] >= 0.60:
                    # Retry with higher budget (20% more)
                    current_budget = int(current_budget * 1.2)
                    best_result = result
                    logger.info(
                        f"Retrying compression with higher budget: {current_budget} words"
                    )
                    continue

                else:
                    # Score too low, abort and use truncation
                    logger.error(
                        f"Compression verification failed: {verification['score']:.2%}. "
                        "Falling back to truncation."
                    )
                    result.success = False
                    result.error = f"Verification score too low: {verification['score']:.2%}"
                    return result

            except Exception as e:
                logger.exception(f"Compression attempt {attempts} failed: {e}")
                if attempts >= strategy.max_attempts:
                    duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                    return CompressionResult(
                        success=False,
                        original_content=content,
                        compressed_content=content,
                        original_words=original_words,
                        compressed_words=original_words,
                        compression_ratio=1.0,
                        verification_score=0.0,
                        verification_passed=False,
                        key_facts_preserved=0,
                        key_facts_total=0,
                        content_type=content_type,
                        section_num=section_num,
                        budget=budget,
                        attempts=attempts,
                        duration_ms=duration_ms,
                        error=str(e),
                    )

        # Return best result from attempts
        if best_result:
            return best_result

        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        return CompressionResult(
            success=False,
            original_content=content,
            compressed_content=content,
            original_words=original_words,
            compressed_words=original_words,
            compression_ratio=1.0,
            verification_score=0.0,
            verification_passed=False,
            key_facts_preserved=0,
            key_facts_total=0,
            content_type=content_type,
            section_num=section_num,
            budget=budget,
            attempts=attempts,
            duration_ms=duration_ms,
            error="Max attempts exceeded",
        )

    async def compress_if_needed(
        self,
        section_num: int,
        content: str,
        content_type: Optional[ContentType] = None,
    ) -> CompressionResult:
        """
        Check if section needs compression and compress if so.

        Only triggers compression when content exceeds budget by >20%
        to avoid expensive compression for marginal overages.

        Args:
            section_num: Section number (0-6)
            content: Content to potentially compress
            content_type: Optional content type override

        Returns:
            CompressionResult - if no compression needed, returns
            result with success=True and original content
        """
        original_words = get_word_count(content)
        budget = get_section_budget(section_num)

        # Check if compression is warranted
        if not should_compress(section_num, content):
            # Content is within acceptable range
            return CompressionResult(
                success=True,
                original_content=content,
                compressed_content=content,
                original_words=original_words,
                compressed_words=original_words,
                compression_ratio=1.0,
                verification_score=1.0,
                verification_passed=True,
                key_facts_preserved=0,
                key_facts_total=0,
                content_type=content_type or detect_content_type(content),
                section_num=section_num,
                budget=budget,
                attempts=0,
                duration_ms=0,
            )

        logger.info(
            f"Section {section_num} exceeds budget: {original_words}/{budget} words. "
            "Triggering NERVES compression."
        )

        return await self.compress_section(section_num, content, content_type)

    async def _extract_key_facts(
        self, client, content: str, max_facts: int = 10
    ) -> list[str]:
        """
        Extract key facts from content using REFLEX role.

        Args:
            client: LLM client
            content: Content to extract facts from
            max_facts: Maximum number of facts to extract (5-10)

        Returns:
            List of key fact strings
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a fact extractor. Your job is to identify the most important "
                    "facts from the given content. Focus on:\n"
                    "- Key decisions and their outcomes\n"
                    "- Numerical data (prices, scores, counts)\n"
                    "- Named entities (products, vendors, URLs)\n"
                    "- Conclusions and recommendations\n"
                    "- Action items and status\n\n"
                    f"Extract {max_facts} most important facts, one per line. "
                    "Each fact should be a complete, standalone statement."
                ),
            },
            {
                "role": "user",
                "content": f"Extract the key facts from this content:\n\n{content}",
            },
        ]

        response = await client.complete(
            model_layer=self.NERVES_MODEL_LAYER,  # Uses MIND
            messages=messages,
            temperature=self.REFLEX_TEMPERATURE,
            max_tokens=500,
        )

        # Parse facts from response (one per line)
        facts = []
        for line in response.content.strip().split("\n"):
            line = line.strip()
            # Remove bullet points, numbers, etc.
            if line.startswith(("-", "*", "•")):
                line = line[1:].strip()
            elif line and line[0].isdigit() and "." in line[:3]:
                line = line.split(".", 1)[1].strip()
            if line:
                facts.append(line)

        return facts[:max_facts]

    async def _compress_content(
        self,
        client,
        content: str,
        target_words: int,
        strategy,
    ) -> str:
        """
        Compress content using NERVES role (MIND @ temp=0.1).

        Args:
            client: LLM client
            content: Content to compress
            target_words: Target word count
            strategy: CompressionStrategy with preservation rules

        Returns:
            Compressed content string
        """
        preservation_prompt = build_preservation_prompt(strategy)

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a content compressor. Your job is to reduce the length of content "
                    "while preserving critical information.\n\n"
                    f"TARGET: Compress to approximately {target_words} words.\n\n"
                    f"{preservation_prompt}\n\n"
                    "RULES:\n"
                    "- Maintain the document structure and formatting\n"
                    "- Keep all section headers\n"
                    "- Preserve exact numbers, prices, and scores\n"
                    "- Keep source references and links\n"
                    "- Remove verbose explanations\n"
                    "- Condense repetitive information\n"
                    "- Output ONLY the compressed content, no explanations"
                ),
            },
            {
                "role": "user",
                "content": f"Compress this content:\n\n{content}",
            },
        ]

        response = await client.complete(
            model_layer=self.NERVES_MODEL_LAYER,  # Uses MIND
            messages=messages,
            temperature=self.NERVES_TEMPERATURE,  # 0.1 for deterministic
            max_tokens=target_words * 2,  # Allow some flexibility
        )

        return response.content.strip()


def get_summarizer(llm_client=None) -> SmartSummarizer:
    """
    Factory function to get a SmartSummarizer instance.

    Args:
        llm_client: Optional LLM client to use

    Returns:
        SmartSummarizer instance
    """
    return SmartSummarizer(llm_client)
