"""
Knowledge Extractor - Extract and categorize knowledge from research results.

Responsible for:
1. Extracting topics from queries and responses
2. Categorizing claims by type (retailer, price, tip, etc.)
3. Creating/updating topics in the Topic Index
4. Tagging claims with topic IDs

Called after research completes to accumulate session knowledge.

Created: 2025-12-02
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from orchestrator.shared_state.claims import ClaimRegistry, ClaimRow
from orchestrator.shared_state.topic_index import TopicIndex, Topic, get_topic_index
from orchestrator.shared_state.claim_types import ClaimType

logger = logging.getLogger(__name__)

# Prompt loading infrastructure
_PROMPT_DIR = Path(__file__).parent.parent / "apps" / "prompts" / "query"
_prompt_cache: Dict[str, str] = {}


def _load_prompt(prompt_name: str) -> str:
    """Load a prompt file from the query prompts directory."""
    if prompt_name in _prompt_cache:
        return _prompt_cache[prompt_name]
    prompt_path = _PROMPT_DIR / f"{prompt_name}.md"
    if prompt_path.exists():
        content = prompt_path.read_text()
        _prompt_cache[prompt_name] = content
        return content
    logger.warning(f"Prompt file not found: {prompt_path}")
    return ""


@dataclass
class TopicExtractionResult:
    """Result of topic extraction from a query/response."""
    topic_name: str
    topic_slug: str
    parent_slug: Optional[str]
    retailers: List[str]
    price_range: Dict[str, float]
    key_specs: List[str]
    is_new_domain: bool


@dataclass
class ClaimCategorization:
    """Categorization result for a claim."""
    claim_id: str
    claim_type: ClaimType
    confidence: float


class KnowledgeExtractor:
    """
    Extracts and categorizes knowledge from research results.

    Usage:
        extractor = KnowledgeExtractor(session_id)

        # After research completes:
        topic = await extractor.extract_and_store_topic(
            query="laptop with rtx 4070",
            research_result=result,
        )

        # Categorize and tag claims:
        await extractor.categorize_claims(topic.topic_id, claims)
    """

    def __init__(
        self,
        session_id: str,
        model_url: Optional[str] = None,
        model_id: Optional[str] = None,
    ):
        """
        Initialize KnowledgeExtractor.

        Args:
            session_id: Session to store knowledge in
            model_url: Optional LLM endpoint URL
            model_id: Optional LLM model ID
        """
        self.session_id = session_id
        self.model_url = model_url or os.getenv("LLM_BASE_URL", "http://127.0.0.1:8000/v1")
        self.model_id = model_id or os.getenv("LLM_MODEL_ID", "qwen3-coder")
        self.api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

        self._topic_index: Optional[TopicIndex] = None
        self._claim_registry: Optional[ClaimRegistry] = None

    @property
    def topic_index(self) -> TopicIndex:
        """Lazy-load topic index."""
        if self._topic_index is None:
            self._topic_index = get_topic_index()
        return self._topic_index

    @property
    def claim_registry(self) -> ClaimRegistry:
        """Lazy-load claim registry."""
        if self._claim_registry is None:
            from orchestrator.shared_state.claims import get_claim_registry
            self._claim_registry = get_claim_registry()
        return self._claim_registry

    def _normalize_vendor_domain(self, vendor: str) -> str:
        """Normalize a vendor string into a domain."""
        try:
            parsed = urlparse(vendor)
            domain = parsed.netloc or parsed.path.split("/")[0]
            domain = domain.lower().strip()
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return vendor.lower().strip()

    def _vendor_label_from_domain(self, domain: str) -> str:
        """Create a readable label from a vendor domain."""
        base = domain.split(".")[0] if domain else "unknown"
        return base.replace("-", " ").replace("_", " ").strip()

    async def extract_and_store_topic(
        self,
        query: str,
        research_result: Optional[Dict[str, Any]] = None,
        vendors_visited: Optional[List[str]] = None,
        products_found: Optional[List[Dict]] = None,
    ) -> Optional[Topic]:
        """
        Extract topic from query/results and store in Topic Index.

        Args:
            query: User's research query
            research_result: Optional research result dict
            vendors_visited: Optional list of vendors visited
            products_found: Optional list of products found

        Returns:
            Created or updated Topic, or None if extraction failed
        """
        try:
            # First try rule-based extraction (fast, no LLM)
            topic_result = self._extract_topic_rules(query, vendors_visited, products_found)

            # If rule-based gives good results, use it
            if topic_result and topic_result.topic_name:
                return await self._store_topic(topic_result, query)

            # Fall back to LLM extraction for complex queries
            topic_result = await self._extract_topic_llm(query, research_result)

            if topic_result and topic_result.topic_name:
                return await self._store_topic(topic_result, query)

            logger.warning(f"[KnowledgeExtractor] Could not extract topic from: {query[:50]}...")
            return None

        except Exception as e:
            logger.error(f"[KnowledgeExtractor] Topic extraction failed: {e}")
            return None

    def _extract_topic_rules(
        self,
        query: str,
        vendors: Optional[List[str]] = None,
        products: Optional[List[Dict]] = None,
    ) -> Optional[TopicExtractionResult]:
        """
        Rule-based topic extraction (fast, no LLM).

        Handles common patterns like:
        - "laptop with rtx 4060" → nvidia_rtx_4060_laptops
        - "cheap hamster cage" → hamster_cages
        """
        query_lower = query.lower()

        # Extract key components
        topic_words = []
        parent_words = []

        # GPU patterns
        gpu_match = re.search(r'(rtx|gtx|radeon|rx)\s*(\d{4})', query_lower)
        if gpu_match:
            gpu = f"{gpu_match.group(1)}_{gpu_match.group(2)}"
            topic_words.append(gpu)
            parent_words.append("nvidia" if "rtx" in gpu or "gtx" in gpu else "amd")

        # Product type patterns
        product_types = [
            "laptop", "laptops", "desktop", "computer", "pc",
            "phone", "tablet", "monitor", "tv", "television",
            "camera", "headphones", "speaker", "keyboard", "mouse",
            "cage", "food", "supplies", "accessories",
        ]
        for ptype in product_types:
            if ptype in query_lower:
                topic_words.append(ptype.rstrip('s'))  # Singularize
                break

        # Brand patterns
        brands = ["msi", "asus", "acer", "dell", "hp", "lenovo", "apple", "samsung", "sony"]
        for brand in brands:
            if brand in query_lower:
                topic_words.insert(0, brand)
                break

        # Modifiers
        modifiers = ["cheap", "budget", "gaming", "professional", "best"]
        for mod in modifiers:
            if mod in query_lower:
                topic_words.insert(0, mod)
                break

        if not topic_words:
            return None

        # Generate topic name and slug
        topic_slug = "_".join(topic_words)
        topic_name = " ".join(word.title() for word in topic_words)

        # Generate parent slug if we have parent words
        parent_slug = "_".join(parent_words + [topic_words[-1]]) if parent_words else None

        # Extract retailers from vendors visited
        retailers = []
        if vendors:
            try:
                from orchestrator.shared_state.vendor_registry import get_vendor_registry
                registry = get_vendor_registry()
            except Exception:
                registry = None

            seen = set()
            for vendor in vendors:
                domain = self._normalize_vendor_domain(vendor)
                if not domain:
                    continue
                label = None
                if registry:
                    record = registry.get(domain)
                    if record and record.name:
                        label = record.name
                if not label:
                    label = self._vendor_label_from_domain(domain)
                normalized = label.replace(" ", "").replace("&", "and")
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    retailers.append(normalized)

        # Extract price range from products
        price_range = {}
        if products:
            prices = []
            for product in products:
                price = product.get("price") or product.get("current_price")
                if price and isinstance(price, (int, float)) and price > 0:
                    prices.append(float(price))
            if prices:
                price_range = {"min": min(prices), "max": max(prices)}

        return TopicExtractionResult(
            topic_name=topic_name,
            topic_slug=topic_slug,
            parent_slug=parent_slug,
            retailers=retailers,
            price_range=price_range,
            key_specs=[],
            is_new_domain=False,
        )

    async def _extract_topic_llm(
        self,
        query: str,
        research_result: Optional[Dict[str, Any]] = None,
    ) -> Optional[TopicExtractionResult]:
        """
        LLM-based topic extraction for complex queries.
        """
        try:
            # Build context from research result
            context_parts = [f"Query: {query}"]

            if research_result:
                if "findings" in research_result:
                    findings = research_result["findings"][:5]  # Limit
                    context_parts.append(f"Findings: {json.dumps(findings, default=str)[:500]}")
                if "sources" in research_result:
                    sources = [s.get("domain", "") for s in research_result.get("sources", [])][:5]
                    context_parts.append(f"Sources: {sources}")

            context = "\n".join(context_parts)

            # Load prompt from file
            base_prompt = _load_prompt("topic_extractor")
            if not base_prompt:
                # Fallback inline prompt if file not found
                base_prompt = """Extract the main topic from this research query and context.
Return ONLY a JSON object with these fields:
- topic_name: Human readable name (e.g., "NVIDIA RTX 4070 Laptops")
- topic_slug: URL-safe identifier (e.g., "nvidia_rtx_4070_laptops")
- parent_slug: Parent topic slug if applicable (e.g., "gaming_laptops"), or null
- retailers: List of retailer names mentioned or relevant
- is_new_domain: true if this is a completely new topic domain"""

            prompt = f"""{base_prompt}

## Current Task

{context}

JSON response:"""

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.model_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model_id,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 500,
                        "temperature": 0.1,
                    }
                )
                response.raise_for_status()
                result = response.json()

            content = result["choices"][0]["message"]["content"].strip()

            # Parse JSON from response
            json_match = re.search(r'\{[^{}]+\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return TopicExtractionResult(
                    topic_name=data.get("topic_name", ""),
                    topic_slug=data.get("topic_slug", ""),
                    parent_slug=data.get("parent_slug"),
                    retailers=data.get("retailers", []),
                    price_range={},
                    key_specs=[],
                    is_new_domain=data.get("is_new_domain", False),
                )

        except Exception as e:
            logger.warning(f"[KnowledgeExtractor] LLM topic extraction failed: {e}")

        return None

    async def _store_topic(
        self,
        topic_result: TopicExtractionResult,
        source_query: str,
    ) -> Topic:
        """Store or update topic in Topic Index."""

        # Check if topic already exists
        existing = self.topic_index.get_topic_by_slug(
            self.session_id,
            topic_result.topic_slug
        )

        if existing:
            # Update existing topic
            updated = self.topic_index.update_topic(
                topic_id=existing.topic_id,
                retailers=topic_result.retailers,
                price_range=topic_result.price_range,
                key_specs=topic_result.key_specs,
                source_query=source_query,
            )
            logger.info(f"[KnowledgeExtractor] Updated topic: {existing.topic_name}")
            return updated or existing

        # Resolve parent topic
        parent_id = None
        if topic_result.parent_slug:
            parent = self.topic_index.get_topic_by_slug(
                self.session_id,
                topic_result.parent_slug
            )
            if parent:
                parent_id = parent.topic_id

        # Create new topic
        topic = self.topic_index.create_topic(
            session_id=self.session_id,
            topic_name=topic_result.topic_name,
            topic_slug=topic_result.topic_slug,
            parent_id=parent_id,
            source_query=source_query,
            retailers=topic_result.retailers,
            price_range=topic_result.price_range,
            key_specs=topic_result.key_specs,
        )

        logger.info(f"[KnowledgeExtractor] Created topic: {topic.topic_name}")
        return topic

    def categorize_claims(
        self,
        claims: List[ClaimRow],
    ) -> List[ClaimCategorization]:
        """
        Categorize claims by type using rule-based analysis.

        Args:
            claims: List of claims to categorize

        Returns:
            List of categorization results
        """
        results = []

        for claim in claims:
            claim_type = ClaimType.from_statement(claim.statement)
            confidence = 0.8 if claim_type != ClaimType.GENERAL else 0.5

            results.append(ClaimCategorization(
                claim_id=claim.claim_id,
                claim_type=claim_type,
                confidence=confidence,
            ))

        return results

    async def tag_claims_with_topic(
        self,
        topic_id: str,
        claim_ids: List[str],
        auto_categorize: bool = True,
    ) -> int:
        """
        Tag claims with topic ID and optionally categorize them.

        Args:
            topic_id: Topic to associate claims with
            claim_ids: List of claim IDs to tag
            auto_categorize: Whether to auto-categorize claims by type

        Returns:
            Number of claims updated
        """
        if not claim_ids:
            return 0

        updates = []

        for claim_id in claim_ids:
            update = {"claim_id": claim_id, "topic_id": topic_id}

            if auto_categorize:
                # Get claim statement for categorization
                claims = list(self.claim_registry.list_active_claims())
                claim = next((c for c in claims if c.claim_id == claim_id), None)
                if claim:
                    claim_type = ClaimType.from_statement(claim.statement)
                    update["claim_type"] = claim_type.value

            updates.append(update)

        count = self.claim_registry.bulk_update_claim_topics(updates)
        logger.info(f"[KnowledgeExtractor] Tagged {count} claims with topic {topic_id}")

        return count

    async def process_research_completion(
        self,
        query: str,
        research_result: Dict[str, Any],
        capsule_claims: Optional[List[ClaimRow]] = None,
    ) -> Optional[Topic]:
        """
        Process completed research: extract topic, categorize and tag claims.

        This is the main entry point called after research completes.

        Args:
            query: Original user query
            research_result: Research result dict
            capsule_claims: Optional list of claims from the capsule

        Returns:
            Created/updated Topic, or None if extraction failed
        """
        # Extract vendors and products from research result
        vendors = []
        products = []

        if "sources" in research_result:
            vendors = [s.get("domain", "") for s in research_result.get("sources", [])]

        if "findings" in research_result:
            for finding in research_result.get("findings", []):
                if isinstance(finding, dict) and "price" in finding:
                    products.append(finding)

        # Extract and store topic
        topic = await self.extract_and_store_topic(
            query=query,
            research_result=research_result,
            vendors_visited=vendors,
            products_found=products,
        )

        if not topic:
            return None

        # Tag claims with topic if provided
        if capsule_claims:
            claim_ids = [c.claim_id for c in capsule_claims]
            await self.tag_claims_with_topic(
                topic_id=topic.topic_id,
                claim_ids=claim_ids,
                auto_categorize=True,
            )

        return topic


# Module-level factory
_extractor_cache: Dict[str, KnowledgeExtractor] = {}


def get_knowledge_extractor(session_id: str) -> KnowledgeExtractor:
    """Get or create KnowledgeExtractor for session."""
    if session_id not in _extractor_cache:
        _extractor_cache[session_id] = KnowledgeExtractor(session_id)
    return _extractor_cache[session_id]
