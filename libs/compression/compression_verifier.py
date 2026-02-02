"""Compression verification for PandaAI v2.

Verifies that compression preserves critical information.
Uses REFLEX role to check that key facts are still derivable from compressed content.

Reference: architecture/LLM-ROLES/llm-roles-reference.md (Compression Verification Plan)
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Result of compression verification.

    Attributes:
        passed: Whether verification passed (score >= 0.80)
        score: Verification score (0.0-1.0)
        facts_preserved: Number of facts still derivable
        facts_total: Total facts checked
        facts_missing: List of facts not found in compressed
        semantic_similarity: Optional embedding similarity score
        action: Recommended action based on score
    """

    passed: bool
    score: float
    facts_preserved: int
    facts_total: int
    facts_missing: list[str]
    semantic_similarity: Optional[float] = None
    action: str = "accepted"


class CompressionVerifier:
    """
    Verifies compression quality by checking fact preservation.

    Uses a two-stage verification:
    1. Fact verification: Check if key facts are derivable from compressed
    2. Semantic similarity: Compare embeddings (optional)

    Verification thresholds (from architecture spec):
    - >= 0.90: Accept compression
    - 0.80-0.89: Accept with warning logged
    - 0.60-0.79: Retry with 20% higher budget
    - < 0.60: Abort compression, use truncation instead
    """

    # REFLEX temperature for verification
    REFLEX_TEMPERATURE = 0.3
    MODEL_LAYER = "mind"  # Uses MIND model

    # Verification thresholds
    THRESHOLD_ACCEPT = 0.90
    THRESHOLD_WARNING = 0.80
    THRESHOLD_RETRY = 0.60

    def __init__(self, llm_client=None):
        """
        Initialize CompressionVerifier.

        Args:
            llm_client: Optional LLM client instance
        """
        self._llm_client = llm_client

    async def _get_client(self):
        """Get or create LLM client."""
        if self._llm_client is None:
            from libs.llm.client import get_llm_client
            self._llm_client = get_llm_client()
        return self._llm_client

    async def verify_compression(
        self,
        original: str,
        compressed: str,
        key_facts: Optional[list[str]] = None,
    ) -> dict:
        """
        Verify that compression preserved critical information.

        Args:
            original: Original content before compression
            compressed: Compressed content
            key_facts: Optional pre-extracted key facts to verify

        Returns:
            Dict with verification results:
            - passed: bool
            - score: float (0.0-1.0)
            - facts_preserved: int
            - facts_total: int
            - facts_missing: list[str]
            - action: str (accepted, accepted_with_warning, retry, abort)
        """
        client = await self._get_client()

        # If no key facts provided, extract them from original
        if not key_facts:
            key_facts = await self._extract_key_facts(client, original)

        if not key_facts:
            # No facts to verify - pass by default
            logger.warning("No key facts to verify - assuming compression passed")
            return {
                "passed": True,
                "score": 1.0,
                "facts_preserved": 0,
                "facts_total": 0,
                "facts_missing": [],
                "action": "accepted",
            }

        # Verify each fact against compressed content
        verification_results = await self._verify_facts(client, compressed, key_facts)

        # Calculate score
        facts_preserved = sum(1 for v in verification_results if v["preserved"])
        facts_total = len(key_facts)
        score = facts_preserved / facts_total if facts_total > 0 else 1.0

        facts_missing = [
            f["fact"] for f in verification_results if not f["preserved"]
        ]

        # Determine action based on score
        if score >= self.THRESHOLD_ACCEPT:
            action = "accepted"
            passed = True
        elif score >= self.THRESHOLD_WARNING:
            action = "accepted_with_warning"
            passed = True
            logger.warning(
                f"Compression verification score {score:.2%} below optimal "
                f"(>= {self.THRESHOLD_ACCEPT:.0%})"
            )
        elif score >= self.THRESHOLD_RETRY:
            action = "retry"
            passed = False
            logger.info(
                f"Compression verification score {score:.2%} - retry recommended"
            )
        else:
            action = "abort"
            passed = False
            logger.error(
                f"Compression verification score {score:.2%} too low - aborting"
            )

        return {
            "passed": passed,
            "score": score,
            "facts_preserved": facts_preserved,
            "facts_total": facts_total,
            "facts_missing": facts_missing,
            "action": action,
        }

    async def _extract_key_facts(
        self, client, content: str, max_facts: int = 10
    ) -> list[str]:
        """
        Extract key facts from content.

        Args:
            client: LLM client
            content: Content to extract facts from
            max_facts: Maximum facts to extract

        Returns:
            List of key fact strings
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a fact extractor. Identify the most important facts from "
                    "the content. Focus on:\n"
                    "- Decisions and outcomes\n"
                    "- Numbers (prices, scores, counts)\n"
                    "- Named entities (products, vendors)\n"
                    "- Conclusions and recommendations\n\n"
                    f"Extract up to {max_facts} key facts, one per line."
                ),
            },
            {
                "role": "user",
                "content": f"Extract key facts:\n\n{content}",
            },
        ]

        response = await client.complete(
            model_layer=self.MODEL_LAYER,
            messages=messages,
            temperature=self.REFLEX_TEMPERATURE,
            max_tokens=500,
        )

        # Parse facts
        facts = []
        for line in response.content.strip().split("\n"):
            line = line.strip()
            if line.startswith(("-", "*", "•")):
                line = line[1:].strip()
            elif line and line[0].isdigit() and "." in line[:3]:
                line = line.split(".", 1)[1].strip()
            if line:
                facts.append(line)

        return facts[:max_facts]

    async def _verify_facts(
        self, client, compressed: str, facts: list[str]
    ) -> list[dict]:
        """
        Verify each fact against compressed content.

        Args:
            client: LLM client
            compressed: Compressed content to check against
            facts: List of facts to verify

        Returns:
            List of dicts with {fact, preserved, reason}
        """
        if not facts:
            return []

        # Build verification prompt with all facts
        facts_text = "\n".join(f"{i+1}. {fact}" for i, fact in enumerate(facts))

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a fact verifier. Check if each fact can be derived from "
                    "the compressed content. A fact is PRESERVED if:\n"
                    "- The exact information is present, OR\n"
                    "- The information can be clearly inferred\n\n"
                    "A fact is MISSING if:\n"
                    "- The information is not present and cannot be inferred\n"
                    "- Key details (numbers, names) are lost\n\n"
                    "For each fact, respond with: <number>. [Y/N] <brief reason>\n"
                    "Y = preserved, N = missing"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"COMPRESSED CONTENT:\n{compressed}\n\n"
                    f"FACTS TO VERIFY:\n{facts_text}\n\n"
                    "Check each fact (Y=preserved, N=missing):"
                ),
            },
        ]

        response = await client.complete(
            model_layer=self.MODEL_LAYER,
            messages=messages,
            temperature=self.REFLEX_TEMPERATURE,
            max_tokens=500,
        )

        # Parse verification results
        results = []
        lines = response.content.strip().split("\n")

        for i, fact in enumerate(facts):
            preserved = True  # Default to preserved if parsing fails
            reason = "Unable to parse verification"

            # Look for matching line in response
            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # Try to match pattern: "1. [Y/N] reason" or "1. Y/N reason"
                if line.startswith(f"{i+1}.") or line.startswith(f"{i+1})"):
                    # Extract Y/N
                    rest = line.split(".", 1)[-1].strip() if "." in line else line
                    rest = rest.split(")", 1)[-1].strip() if ")" in rest else rest

                    if rest.upper().startswith("[Y]") or rest.upper().startswith("Y"):
                        preserved = True
                        reason = rest[1:].strip() if rest[0] in "[Y" else rest[1:].strip()
                        reason = reason.lstrip("]").strip()
                    elif rest.upper().startswith("[N]") or rest.upper().startswith("N"):
                        preserved = False
                        reason = rest[1:].strip() if rest[0] in "[N" else rest[1:].strip()
                        reason = reason.lstrip("]").strip()
                    break

            results.append({
                "fact": fact,
                "preserved": preserved,
                "reason": reason,
            })

        return results

    async def compute_semantic_similarity(
        self, original: str, compressed: str
    ) -> float:
        """
        Compute semantic similarity between original and compressed using embeddings.

        This is an optional additional check beyond fact verification.

        Args:
            original: Original content
            compressed: Compressed content

        Returns:
            Cosine similarity score (0.0-1.0)
        """
        try:
            # Use sentence-transformers for embedding
            from sentence_transformers import SentenceTransformer
            import numpy as np

            # Use the configured embedding model
            model = SentenceTransformer("all-MiniLM-L6-v2")

            # Get embeddings
            embeddings = model.encode([original, compressed])

            # Compute cosine similarity
            similarity = np.dot(embeddings[0], embeddings[1]) / (
                np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1])
            )

            return float(similarity)

        except ImportError:
            logger.warning(
                "sentence-transformers not available for semantic similarity"
            )
            return 0.0
        except Exception as e:
            logger.exception(f"Error computing semantic similarity: {e}")
            return 0.0


def get_verifier(llm_client=None) -> CompressionVerifier:
    """
    Factory function to get a CompressionVerifier instance.

    Args:
        llm_client: Optional LLM client to use

    Returns:
        CompressionVerifier instance
    """
    return CompressionVerifier(llm_client)
