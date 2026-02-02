"""
Improvement Principle Extractor

Extracts transferable principles when a REVISE leads to successful APPROVE.
Stores principles in Memory Bank for retrieval in future similar queries.

Based on Self-Improving Agent pattern: reflect on what made revisions succeed,
distill into reusable knowledge.

Usage:
    extractor = PrincipleExtractor(llm_client)
    principle = await extractor.extract_principle(
        original_response="The laptop costs $799...",
        revised_response="| Product | Price |...",
        revision_hints="Use table format for price comparisons",
        query="find cheapest gaming laptops"
    )
    # Returns: ImprovementPrinciple with category, trigger, description
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class ImprovementPrinciple:
    """A transferable lesson learned from a successful revision."""

    category: str
    """Category of improvement: formatting, completeness, accuracy, tone, structure"""

    trigger_pattern: str
    """Query pattern that should trigger this principle (e.g., 'price comparison', 'product search')"""

    title: str
    """Short title for the principle"""

    description: str
    """The principle itself - what to do differently"""

    rationale: str
    """Why this works better"""

    original_issue: str
    """What was wrong with the original"""

    successful_fix: str
    """What the revision did right"""

    source_turn: str = ""
    """Turn ID where this principle was learned"""

    confidence: float = 0.8
    """Confidence in this principle (0.0-1.0)"""

    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_markdown(self) -> str:
        """Format as markdown for Memory Bank storage."""
        return f"""---
category: {self.category}
trigger_pattern: {self.trigger_pattern}
source_turn: {self.source_turn}
confidence: {self.confidence}
created_at: {self.created_at}
tags: [improvement-principle, {self.category}]
---

# {self.title}

{self.description}

## Why This Works

{self.rationale}

## Pattern

**Original issue:** {self.original_issue}

**Successful fix:** {self.successful_fix}
"""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "category": self.category,
            "trigger_pattern": self.trigger_pattern,
            "title": self.title,
            "description": self.description,
            "rationale": self.rationale,
            "original_issue": self.original_issue,
            "successful_fix": self.successful_fix,
            "source_turn": self.source_turn,
            "confidence": self.confidence,
            "created_at": self.created_at,
        }


# Extraction prompt - uses REFLEX role (temp 0.3) for consistent structured output
EXTRACTION_PROMPT = """You are analyzing a successful response revision. A response was revised based on feedback, and the revision was approved.

Your task: Extract ONE transferable principle that explains why the revision was better.

## Original Response (not good enough)
{original_response}

## Revision Hints (feedback given)
{revision_hints}

## Revised Response (approved)
{revised_response}

## User Query Context
{query}

---

Output a JSON object with these fields:

```json
{{
  "category": "formatting|completeness|accuracy|tone|structure",
  "trigger_pattern": "short phrase describing when to apply this (e.g., 'price comparison queries')",
  "title": "Short Title (3-6 words)",
  "description": "The principle in 1-2 sentences. What should be done.",
  "rationale": "Why this approach works better. 1-2 sentences.",
  "original_issue": "What was wrong with the original. 1 sentence.",
  "successful_fix": "What the revision did right. 1 sentence."
}}
```

Focus on extractable, reusable knowledge. The principle should apply to future similar queries, not just this specific one.

Output ONLY the JSON, no other text."""


class PrincipleExtractor:
    """
    Extracts improvement principles from successful revisions.

    When a Validator's REVISE leads to an APPROVE, this class extracts
    a transferable principle explaining what made the revision better.
    """

    def __init__(
        self,
        llm_client,
        memory_bank_path: Path = None,
    ):
        """
        Initialize the extractor.

        Args:
            llm_client: LLM client for extraction calls
            memory_bank_path: Path to Memory Bank (defaults to obsidian_memory)
        """
        self.llm_client = llm_client
        self.memory_bank_path = memory_bank_path or Path("panda_system_docs/obsidian_memory")
        self.principles_dir = self.memory_bank_path / "Improvements" / "Principles"

    async def extract_principle(
        self,
        original_response: str,
        revised_response: str,
        revision_hints: str,
        query: str,
        turn_id: str = "",
        revision_focus: str = "",
    ) -> Optional[ImprovementPrinciple]:
        """
        Extract a principle from a successful revision.

        Args:
            original_response: The response that got REVISE
            revised_response: The response that got APPROVE
            revision_hints: The hints that guided the revision
            query: The original user query
            turn_id: Turn identifier for traceability
            revision_focus: Category from Validator (formatting, completeness, etc.)

        Returns:
            ImprovementPrinciple if extraction succeeds, None otherwise
        """
        # Truncate responses to avoid token bloat (keep first/last for comparison)
        original_truncated = self._truncate_for_comparison(original_response, 800)
        revised_truncated = self._truncate_for_comparison(revised_response, 800)

        prompt = EXTRACTION_PROMPT.format(
            original_response=original_truncated,
            revision_hints=revision_hints,
            revised_response=revised_truncated,
            query=query,
        )

        try:
            # Use REFLEX role (temp 0.3) for consistent extraction
            # Role "guide" uses the main LLM endpoint
            response = await self.llm_client.call(
                prompt=prompt,
                role="guide",
                temperature=0.3,
                max_tokens=500,
            )

            principle_data = self._parse_json_response(response)
            if not principle_data:
                logger.warning("[PrincipleExtractor] Failed to parse extraction response")
                return None

            # Use Validator's revision_focus as category hint if available
            if revision_focus and not principle_data.get("category"):
                principle_data["category"] = revision_focus

            principle = ImprovementPrinciple(
                category=principle_data.get("category", "general"),
                trigger_pattern=principle_data.get("trigger_pattern", ""),
                title=principle_data.get("title", "Untitled Principle"),
                description=principle_data.get("description", ""),
                rationale=principle_data.get("rationale", ""),
                original_issue=principle_data.get("original_issue", ""),
                successful_fix=principle_data.get("successful_fix", ""),
                source_turn=turn_id,
                confidence=0.8,  # Default confidence for extracted principles
            )

            logger.info(
                f"[PrincipleExtractor] Extracted principle: {principle.title} "
                f"(category={principle.category}, trigger={principle.trigger_pattern})"
            )

            return principle

        except Exception as e:
            logger.error(f"[PrincipleExtractor] Extraction failed: {e}")
            return None

    async def store_principle(self, principle: ImprovementPrinciple) -> Optional[Path]:
        """
        Store a principle in Memory Bank.

        Args:
            principle: The principle to store

        Returns:
            Path to stored file, or None if storage failed
        """
        try:
            # Ensure directory exists
            self.principles_dir.mkdir(parents=True, exist_ok=True)

            # Generate filename from title
            safe_title = self._sanitize_filename(principle.title)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{safe_title}_{timestamp}.md"
            filepath = self.principles_dir / filename

            # Write markdown
            filepath.write_text(principle.to_markdown())

            logger.info(f"[PrincipleExtractor] Stored principle at: {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"[PrincipleExtractor] Failed to store principle: {e}")
            return None

    async def extract_and_store(
        self,
        original_response: str,
        revised_response: str,
        revision_hints: str,
        query: str,
        turn_id: str = "",
        revision_focus: str = "",
    ) -> Optional[ImprovementPrinciple]:
        """
        Extract a principle and store it in Memory Bank.

        Convenience method that combines extract_principle and store_principle.

        Returns:
            The extracted principle if successful, None otherwise
        """
        principle = await self.extract_principle(
            original_response=original_response,
            revised_response=revised_response,
            revision_hints=revision_hints,
            query=query,
            turn_id=turn_id,
            revision_focus=revision_focus,
        )

        if principle:
            await self.store_principle(principle)

        return principle

    def _truncate_for_comparison(self, text: str, max_chars: int) -> str:
        """Truncate text while keeping beginning and end for comparison."""
        if len(text) <= max_chars:
            return text

        # Keep 60% from start, 40% from end
        start_chars = int(max_chars * 0.6)
        end_chars = max_chars - start_chars - 20  # Room for ellipsis

        return f"{text[:start_chars]}\n\n[...truncated...]\n\n{text[-end_chars:]}"

    def _parse_json_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse JSON from LLM response, handling markdown code blocks."""
        import json

        # Try to extract JSON from markdown code block
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try direct parse
        try:
            # Find first { and last }
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except json.JSONDecodeError:
            pass

        return None

    def _sanitize_filename(self, title: str) -> str:
        """Convert title to safe filename."""
        # Replace spaces with underscores, remove special chars
        safe = re.sub(r"[^\w\s-]", "", title.lower())
        safe = re.sub(r"[-\s]+", "_", safe)
        return safe[:50]  # Limit length


# Module-level instance
_extractor: Optional[PrincipleExtractor] = None


def get_principle_extractor(llm_client=None) -> PrincipleExtractor:
    """Get or create the global PrincipleExtractor instance."""
    global _extractor
    if _extractor is None:
        if llm_client is None:
            raise ValueError("llm_client required for first initialization")
        _extractor = PrincipleExtractor(llm_client)
    return _extractor
