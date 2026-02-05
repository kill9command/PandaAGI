"""
Claims Manager - Claim extraction and summarization from tool results.

Extracted from UnifiedFlow to provide:
- Claim extraction from various tool results
- Claim summarization (LLM-based and fallback)
- Tool result summarization for context

Claims are structured facts extracted from tool executions that:
- Feed into the claims table in §4
- Can be invalidated on validation failure
- Have TTL for freshness tracking
"""

import logging
import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from libs.gateway.llm.llm_client import LLMClient

logger = logging.getLogger(__name__)


class ClaimsManager:
    """
    Manages claim extraction and summarization.

    Responsibilities:
    - Extract claims from tool results (research, memory, etc.)
    - Summarize claims to fit context budgets
    - Format tool results for synthesis
    """

    def __init__(self, llm_client: Optional["LLMClient"] = None):
        """
        Initialize the claims manager.

        Args:
            llm_client: Optional LLM client for summarization
        """
        self.llm_client = llm_client

    def extract_claims_from_result(
        self,
        tool_name: str,
        result: Dict[str, Any],
        config: Dict[str, Any] = None,
        skip_urls: List[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Extract claims from tool result, filtering out failed URLs.

        Args:
            tool_name: Name of the tool that produced the result
            result: Raw tool result dictionary
            config: Optional configuration
            skip_urls: URLs to skip (from retry context)

        Returns:
            List of claim dictionaries with content, confidence, source, ttl_hours
        """
        claims = []
        skip_urls = skip_urls or []
        config = config or {}

        if tool_name == "internet.research":
            claims.extend(self._extract_research_claims(result, skip_urls))

        elif tool_name == "memory.search":
            claims.extend(self._extract_memory_search_claims(result))

        elif tool_name == "memory.retrieve":
            claims.extend(self._extract_memory_retrieve_claims(result))

        elif tool_name == "memory.save":
            claims.extend(self._extract_memory_save_claims(result))

        elif tool_name == "memory.recall":
            claims.extend(self._extract_memory_recall_claims(result))

        if tool_name == "internet.research":
            logger.info(f"[ClaimsManager] Extracted {len(claims)} claims from {tool_name}")

        return claims

    def _extract_research_claims(
        self,
        result: Dict[str, Any],
        skip_urls: List[str]
    ) -> List[Dict[str, Any]]:
        """Extract claims from internet.research results."""
        claims = []
        findings = result.get("findings", [])

        logger.info(
            f"[ClaimsManager] Research claim extraction: {len(findings)} findings, "
            f"keys={list(findings[0].keys()) if findings else 'none'}"
        )

        skipped_count = 0
        for finding in findings[:10]:  # Limit to 10
            # Skip findings with URLs that failed in previous retry attempts
            finding_url = finding.get("url", "")
            if finding_url and any(
                skip_url in finding_url or finding_url in skip_url
                for skip_url in skip_urls
            ):
                logger.info(f"[ClaimsManager] Skipping finding with failed URL: {finding_url[:80]}...")
                skipped_count += 1
                continue

            # Build claim content from available fields
            content = (
                finding.get("summary") or
                finding.get("title") or
                finding.get("statement") or
                ""
            )

            if not content and finding.get("name"):
                # Product finding - build descriptive content
                name = finding.get("name", "")
                price = finding.get("price", "")
                vendor = finding.get("vendor", "")
                parts = [name]
                if price:
                    if isinstance(price, (int, float)):
                        parts.append(f"- ${price}")
                    elif str(price).replace('.', '').replace(',', '').isdigit():
                        parts.append(f"- ${price}")
                    else:
                        parts.append(f"- {price}")
                if vendor:
                    parts.append(f"at {vendor}")
                content = " ".join(parts)

            claims.append({
                "content": content[:1000] if content else "",
                "confidence": 0.8,
                "source": finding.get("url", "internet.research"),
                "ttl_hours": 6
            })

        # Extract from answer if present
        answer = result.get("answer", "")
        if answer:
            claims.append({
                "content": answer[:300],
                "confidence": 0.85,
                "source": "internet.research/synthesis",
                "ttl_hours": 6
            })

        return claims

    def _extract_memory_search_claims(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract claims from memory.search results."""
        claims = []
        results_list = result.get("results", [])

        for item in results_list:
            content = item.get("snippet") or item.get("title", "")
            if content:
                claims.append({
                    "content": content[:1000],
                    "confidence": min(0.95, item.get("score", 0.7) + 0.2),
                    "source": f"memory/{item.get('source', 'unknown')}",
                    "ttl_hours": 24
                })

        return claims

    def _extract_memory_retrieve_claims(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract claims from memory.retrieve results."""
        claims = []
        doc_content = result.get("content", "")

        if doc_content:
            claims.append({
                "content": doc_content[:2000],
                "confidence": 0.95,
                "source": f"memory/{result.get('doc_path', 'document')}",
                "ttl_hours": 24
            })

        return claims

    def _extract_memory_save_claims(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract claims from memory.save results."""
        claims = []

        if result.get("status") == "saved":
            claims.append({
                "content": f"Saved: {result.get('doc_id', 'document')}",
                "confidence": 1.0,
                "source": "memory/save",
                "ttl_hours": 168  # 1 week
            })

        return claims

    def _extract_memory_recall_claims(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract claims from legacy memory.recall results."""
        claims = []
        items = result.get("items", [])

        for item in items:
            claims.append({
                "content": item.get("content", str(item))[:1000],
                "confidence": 0.95,
                "source": "memory",
                "ttl_hours": 24
            })

        return claims

    def summarize_tool_results(self, tool_results: List[Dict[str, Any]]) -> str:
        """
        Summarize tool results with detailed findings.

        For internet.research, includes:
        - Phase 1: Intelligence gathered (forums, recommendations, key criteria)
        - Phase 2: Products found (names, prices, vendors)

        For failed tools, includes error classification.

        Args:
            tool_results: List of tool result dictionaries

        Returns:
            Formatted summary string
        """
        from libs.gateway.util.error_compactor import get_error_compactor

        summaries = []
        error_compactor = get_error_compactor()

        for result in tool_results:
            status = result.get("status", "unknown")
            tool = result.get("tool", "unknown")
            claims_count = len(result.get("claims", []))
            summaries.append(f"- {tool}: {status} ({claims_count} claims)")

            # Handle failed tools with error compaction
            if status in ("error", "failed", "timeout"):
                compacted = error_compactor.compact_from_result(result, tool)
                if compacted:
                    summaries.append(compacted.to_context_format())
                continue

            # For internet.research, add detailed breakdown
            if tool == "internet.research" and status == "success":
                summaries.extend(self._format_research_result(result))

        return "\n".join(summaries) if summaries else "No tool results"

    def _format_research_result(self, result: Dict[str, Any]) -> List[str]:
        """Format internet.research result details."""
        summaries = []
        raw_result = result.get("raw_result", {})

        # Phase 1 Intelligence
        intelligence = raw_result.get("intelligence", {})
        if intelligence:
            key_criteria = intelligence.get("key_criteria", [])
            credible_sources = intelligence.get("credible_sources", [])
            recommendations = intelligence.get("key_recommendations", [])

            if key_criteria or credible_sources or recommendations:
                summaries.append("  **Phase 1 Intelligence:**")
                if key_criteria:
                    summaries.append(f"  - Key criteria: {', '.join(key_criteria[:5])}")
                if credible_sources:
                    sources_display = [
                        s.get('name', s.get('url', 'unknown'))[:30]
                        for s in credible_sources[:3]
                    ]
                    summaries.append(f"  - Sources: {', '.join(sources_display)}")
                if recommendations:
                    summaries.append(f"  - Recommendations: {', '.join(recommendations[:3])}")

        # Phase 2 Products
        findings = raw_result.get("findings", [])
        product_findings = [
            f for f in findings
            if f.get("type") == "product" or f.get("price")
        ]

        if product_findings:
            summaries.append(f"  **Phase 2 Products ({len(product_findings)} found):**")
            for pf in product_findings[:5]:
                name = pf.get("name", pf.get("title", "Unknown"))[:40]
                price = pf.get("price", "N/A")
                vendor = pf.get("vendor", pf.get("source", ""))[:20]
                url = pf.get("url", "")
                if url and vendor:
                    summaries.append(f"  - {name} | {price} | {vendor} | {url}")
                elif vendor:
                    summaries.append(f"  - {name} | {price} | {vendor}")
                else:
                    summaries.append(f"  - {name} | {price}")

            if len(product_findings) > 5:
                summaries.append(f"  - ... and {len(product_findings) - 5} more products")

        # General findings (non-product)
        general_findings = [
            f for f in findings
            if f.get("type") in ("source_summary", "user_insight", None)
            and not f.get("price")
        ]

        if general_findings and not product_findings:
            summaries.append(f"  **Research Findings ({len(general_findings)} items):**")
            for gf in general_findings[:5]:
                statement = gf.get("statement", gf.get("content", ""))
                source = gf.get("source", "")[:50]
                if statement:
                    preview = statement[:800] + "..." if len(statement) > 800 else statement
                    preview_lines = preview.split("\n")
                    if len(preview_lines) > 1:
                        summaries.append(f"  - Source: {source}")
                        for line in preview_lines[:20]:
                            if line.strip():
                                summaries.append(f"    {line.strip()}")
                        if len(preview_lines) > 20:
                            summaries.append(f"    ... and {len(preview_lines) - 20} more lines")
                    else:
                        summaries.append(f"  - {preview}")

            if len(general_findings) > 5:
                summaries.append(f"  - ... and {len(general_findings) - 5} more findings")
            summaries.append("  **Status: Content extracted - task may be DONE**")

        # Strategy
        strategy = raw_result.get("strategy", "")
        if strategy:
            summaries.append(f"  Strategy: {strategy}")

        return summaries

    async def summarize_claims_batch(
        self,
        claims: List[Dict[str, Any]],
        max_chars_per_claim: int = 100
    ) -> List[str]:
        """
        Summarize all claims using LLM in a single batch call.

        MUST PRESERVE: price, vendor name, product name, key specs.
        Uses pattern extraction ONLY as fallback if LLM fails.

        Args:
            claims: List of claim dictionaries
            max_chars_per_claim: Target length for summaries

        Returns:
            List of summarized claim strings
        """
        if not claims:
            return []

        if not self.llm_client:
            logger.warning("[ClaimsManager] No LLM client, using fallback extraction")
            return [
                self.extract_claim_key_facts(c.get('content', ''), max_chars_per_claim)
                for c in claims
            ]

        # Build batch prompt
        claims_text = "\n".join([
            f"{i+1}. {c.get('content', '')[:300]}"
            for i, c in enumerate(claims)
        ])

        # Try to load prompt from recipe system
        try:
            from libs.gateway.llm.recipe_loader import load_recipe
            recipe = load_recipe("memory/claim_summarizer")
            prompt_template = recipe.get_prompt()
            prompt = prompt_template.format(
                max_chars=max_chars_per_claim,
                claims_text=claims_text
            )
        except Exception as e:
            logger.warning(f"[ClaimsManager] Failed to load claim_summarizer recipe: {e}")
            prompt = f"""Summarize each claim to ~{max_chars_per_claim} characters.

CRITICAL - Preserve KEY FACTS from each claim:
- If there's a price, keep it EXACT (e.g., $794.99)
- If there's a vendor/source, include it
- If there's a measurement/spec (height, size, material), keep it
- If it's factual info (how-to, specifications), preserve the key details
- Do NOT add information that isn't in the original claim

Format: One summary per line, numbered 1-N. No extra text.

CLAIMS TO SUMMARIZE:
{claims_text}

SUMMARIES:"""

        try:
            # NERVES role (temp=0.3) for factual claim extraction
            response = await self.llm_client.call(
                prompt=prompt,
                role="claims_extractor",
                max_tokens=len(claims) * 50,
                temperature=0.3
            )

            # Parse numbered summaries
            summaries = []
            for line in response.strip().split('\n'):
                line = line.strip()
                if line and (line[0].isdigit() or line.startswith('-')):
                    summary = re.sub(r'^[\d]+\.\s*', '', line)
                    summary = re.sub(r'^-\s*', '', summary).strip()
                    if summary:
                        summaries.append(summary)

            if len(summaries) >= len(claims):
                logger.info(f"[ClaimsManager] LLM summarized {len(claims)} claims successfully")
                return summaries[:len(claims)]

            logger.warning(
                f"[ClaimsManager] LLM returned {len(summaries)} summaries "
                f"for {len(claims)} claims, using fallback"
            )

        except Exception as e:
            logger.error(f"[ClaimsManager] Claim summarization LLM call failed: {e}")

        # Fallback: pattern extraction
        logger.info(f"[ClaimsManager] Using pattern extraction fallback for {len(claims)} claims")
        return [
            self.extract_claim_key_facts(c.get('content', ''), max_chars_per_claim)
            for c in claims
        ]

    def extract_claim_key_facts(self, content: str, max_chars: int = 100) -> str:
        """
        FALLBACK ONLY: Extract key facts using regex if LLM fails.

        Args:
            content: Claim content to summarize
            max_chars: Maximum output length

        Returns:
            Extracted key facts string
        """
        if len(content) <= max_chars:
            return content

        # Extract price
        price_match = re.search(r'\$[\d,]+(?:\.\d{2})?', content)
        price = price_match.group() if price_match else ""

        # Extract vendor
        vendor_match = re.search(
            r'(?:at|from)\s+([a-zA-Z0-9.-]+\.(?:com|org|net))',
            content,
            re.I
        )
        vendor = f"at {vendor_match.group(1)}" if vendor_match else ""

        # Get product name
        if " - $" in content:
            product = content.split(" - $")[0][:60]
        else:
            product = content[:60]

        parts = [p for p in [product.strip(), price, vendor] if p]
        result = " - ".join(parts) if parts else content[:max_chars]
        return result[:max_chars]

    def extract_claims_from_workflow_result(
        self,
        workflow_result: Any,
        workflow_name: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Extract claims from workflow outputs.

        Handles:
        - findings array (common in research workflows)
        - products array (commerce workflows)

        Args:
            workflow_result: WorkflowResult object with .outputs dict
            workflow_name: Name of the workflow for source attribution

        Returns:
            List of claim dictionaries with claim_text, source, confidence, tool, fields
        """
        claims = []

        # Handle both WorkflowResult objects and raw dicts
        if hasattr(workflow_result, 'outputs'):
            outputs = workflow_result.outputs
            wf_name = getattr(workflow_result, 'workflow_name', workflow_name)
        else:
            outputs = workflow_result if isinstance(workflow_result, dict) else {}
            wf_name = workflow_name

        # Extract from findings array (common in research workflows)
        findings = outputs.get("findings", [])
        for finding in findings:
            if isinstance(finding, dict):
                claims.append({
                    "claim_text": finding.get("name", finding.get("statement", "")),
                    "source": finding.get("url", finding.get("source", f"workflow:{wf_name}")),
                    "confidence": finding.get("confidence", 0.7),
                    "tool": f"workflow:{wf_name}",
                    "fields": finding
                })

        # Extract from products array (commerce workflows)
        products = outputs.get("products", [])
        for product in products:
            if isinstance(product, dict):
                claims.append({
                    "claim_text": product.get("name", ""),
                    "source": product.get("url", product.get("vendor", f"workflow:{wf_name}")),
                    "confidence": product.get("confidence", 0.8),
                    "tool": f"workflow:{wf_name}",
                    "fields": {
                        "price": product.get("price"),
                        "vendor": product.get("vendor"),
                        "in_stock": product.get("in_stock"),
                        **product
                    }
                })

        return claims


# Module-level singleton
_manager: Optional[ClaimsManager] = None


def get_claims_manager(llm_client: Optional["LLMClient"] = None) -> ClaimsManager:
    """Get or create the singleton ClaimsManager instance."""
    global _manager
    if _manager is None:
        _manager = ClaimsManager(llm_client)
    return _manager
