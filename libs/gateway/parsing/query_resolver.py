"""
Query Resolver - Reference resolution for follow-up queries.

Extracted from UnifiedFlow to handle:
- N-1 turn reference resolution
- Pronoun and vague reference resolution
- Clarification extraction

Architecture Reference:
- architecture/main-system-patterns/phase1-query-analyzer.md
"""

import logging
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from libs.gateway.context.context_document import ContextDocument

logger = logging.getLogger(__name__)


class QueryResolver:
    """
    Resolves vague references in follow-up queries.

    Responsibilities:
    - Extract clarification questions from context
    - Resolve pronouns using N-1 turn context
    - Use LLM for complex reference resolution
    """

    def __init__(self, llm_client: Any, turns_dir: Path):
        """Initialize the query resolver."""
        self.llm_client = llm_client
        self.turns_dir = turns_dir

    def extract_clarification(self, context_doc: "ContextDocument") -> str:
        """Extract clarification question from context."""
        section1 = context_doc.get_section(1)
        if section1 and "clarification" in section1.lower():
            # Try to extract the question
            lines = section1.split("\n")
            for line in lines:
                if "?" in line:
                    return line.strip()

        return "Could you please provide more details about your request?"

    async def resolve_query_from_context(self, query: str, context_doc: "ContextDocument") -> str:
        """
        DEPRECATED: Use resolve_query_with_n1() instead.

        This function used the full gathered context which could include irrelevant
        older turns, causing the LLM to resolve pronouns incorrectly.

        Keeping this for backward compatibility but should not be called.
        """
        from libs.gateway.recipes.recipe_loader import load_recipe

        gathered = context_doc.get_section(2) or ""

        # Quick check: if query is explicit and long enough, skip resolution
        query_lower = query.lower()
        word_count = len(query.split())
        has_explicit_subject = any(kw in query_lower for kw in [
            'hamster', 'laptop', 'phone', 'computer', 'reef', 'aquarium',
            'fish', 'coral', 'pet', 'amazon', 'ebay', 'google', '.com', '.org'
        ])

        if word_count >= 10 and has_explicit_subject:
            logger.info(f"[QueryResolver] Query explicit, skipping resolution: '{query[:50]}'")
            return query

        if not gathered.strip():
            logger.info(f"[QueryResolver] No context, skipping resolution: '{query[:50]}'")
            return query

        # Use LLM to resolve vague references
        try:
            recipe = load_recipe("pipeline/reference_resolver")
            prompt_template = recipe.get_prompt()
            prompt = prompt_template.format(query=query, context=gathered[:2000])
        except Exception as e:
            logger.warning(f"[QueryResolver] Failed to load reference_resolver recipe: {e}, using fallback")
            prompt = f"""Resolve any vague references in this query using the conversation context.

QUERY: {query}

CONTEXT:
{gathered[:2000]}

TASK:
- If the query contains vague words like "some", "them", "it", "those", "these", "that", "one", replace them with the specific subject from context
- If the query is a follow-up question about something mentioned in context (like "the topics", "the results", "tell me more"), prepend the subject
- If the query is already specific and complete, return it unchanged

OUTPUT:
Return ONLY the resolved query (or the original if no resolution needed). No explanation."""

        try:
            # NERVES role (temp=0.3) for reference resolution
            resolved = await self.llm_client.call(
                prompt=prompt,
                role="resolver",
                max_tokens=200,
                temperature=0.3
            )
            resolved = resolved.strip()

            if resolved and len(resolved) > 3 and len(resolved) < len(query) * 5:
                if resolved != query:
                    logger.info(f"[QueryResolver] LLM resolved query: '{query}' → '{resolved}'")
                return resolved
            else:
                logger.warning(f"[QueryResolver] LLM returned invalid resolution: '{resolved[:100]}', using original")
                return query

        except Exception as e:
            logger.error(f"[QueryResolver] Query resolution LLM call failed: {e}")
            return query

    async def resolve_query_with_n1(self, query: str, turn_number: int, session_id: str) -> str:
        """
        Resolve references using the immediately preceding turn (N-1).

        This runs BEFORE context gathering to ensure the query is explicit
        before we search for relevant context.

        ARCHITECTURAL FIX (2026-01-04): Always provides N-1 context to the LLM.
        The LLM decides if resolution is needed - no hardcoded pattern matching.

        This handles:
        - Pronouns: "it", "that", "those", "some"
        - Definite references: "the thread", "the laptop", "the product"
        - Implicit references: "tell me more", "how many pages"
        """
        from libs.gateway.recipes.recipe_loader import load_recipe

        # Load N-1 turn content
        n1_turn_number = turn_number - 1
        if n1_turn_number < 1:
            logger.debug("[QueryResolver] No N-1 turn available, skipping resolution")
            return query

        n1_dir = self.turns_dir / f"turn_{n1_turn_number:06d}"
        if not n1_dir.exists():
            logger.debug(f"[QueryResolver] N-1 turn dir not found: {n1_dir}")
            return query

        # Read N-1 context
        n1_context_path = n1_dir / "context.md"
        n1_response_path = n1_dir / "response.md"

        n1_query = ""
        n1_response = ""

        # Extract query from N-1
        if n1_context_path.exists():
            try:
                content = n1_context_path.read_text()
                if "## 0. User Query" in content:
                    query_section = content.split("## 0. User Query")[1]
                    if "---" in query_section:
                        query_section = query_section.split("---")[0]
                    n1_query = query_section.strip()[:200]
            except Exception as e:
                logger.warning(f"[QueryResolver] Failed to read N-1 query: {e}")

        # Extract response from N-1
        if n1_response_path.exists():
            try:
                content = n1_response_path.read_text()
                if "**Draft Response:**" in content:
                    response_section = content.split("**Draft Response:**")[1]
                    if "---" in response_section:
                        response_section = response_section.split("---")[0]
                    n1_response = response_section.strip()[:500]
                else:
                    n1_response = content.strip()[:500]
            except Exception as e:
                logger.warning(f"[QueryResolver] Failed to read N-1 response: {e}")

        if not n1_query and not n1_response:
            logger.debug("[QueryResolver] N-1 has no extractable content, skipping resolution")
            return query

        # Build N-1 summary
        n1_summary = ""
        if n1_query:
            n1_summary += f"User asked: {n1_query}\n"
        if n1_response:
            n1_summary += f"Response: {n1_response}"

        logger.info(f"[QueryResolver] N-1 Resolution: query='{query[:50]}', N-1 topic='{n1_query[:50]}...'")

        # LLM prompt
        try:
            recipe = load_recipe("pipeline/reference_resolver")
            prompt_template = recipe.get_prompt()
            prompt = prompt_template.format(query=query, context=n1_summary[:800])
        except Exception as e:
            logger.warning(f"[QueryResolver] Failed to load reference_resolver recipe: {e}, using fallback")
            prompt = f"""Resolve any vague references in the current query using the previous message.

CURRENT QUERY: {query}

PREVIOUS MESSAGE (what was just discussed):
{n1_summary[:800]}

TASK:
- If the query contains pronouns like "some", "it", "that", "those", "them", "these" that refer to something from the previous message, replace them with the specific subject.
- If the query is already complete and explicit (has a clear subject), return it UNCHANGED.
- If the previous message is unrelated (like "thanks" or "ok"), return the query UNCHANGED.

EXAMPLES:
- "find some for sale" + prev="Syrian hamster is favorite" → "find Syrian hamsters for sale"
- "find some laptops for sale" + prev="Syrian hamster" → "find some laptops for sale" (unchanged - already has subject)
- "how much is it" + prev="RTX 4060 costs $800" → "how much is the RTX 4060"
- "tell me more" + prev="Discussed reef tanks" → "tell me more about reef tanks"
- "thanks" + prev="anything" → "thanks" (unchanged)

OUTPUT: Return ONLY the resolved query (or original if no resolution needed). No explanation."""

        try:
            # NERVES role (temp=0.3) for reference resolution
            resolved = await self.llm_client.call(
                prompt=prompt,
                role="resolver",
                max_tokens=200,
                temperature=0.3
            )
            resolved = resolved.strip()

            # Remove any quotes the LLM might have added
            if resolved.startswith('"') and resolved.endswith('"'):
                resolved = resolved[1:-1]
            if resolved.startswith("'") and resolved.endswith("'"):
                resolved = resolved[1:-1]

            # Sanity checks
            if not resolved or len(resolved) < 3:
                logger.warning(f"[QueryResolver] N-1 resolution returned empty/short, using original")
                return query

            if len(resolved) > len(query) * 5:
                logger.warning(f"[QueryResolver] N-1 resolution too long, using original")
                return query

            if resolved != query:
                logger.info(f"[QueryResolver] N-1 RESOLVED: '{query}' → '{resolved}'")
            else:
                logger.debug(f"[QueryResolver] N-1 resolution: query unchanged (already explicit)")

            return resolved

        except Exception as e:
            logger.error(f"[QueryResolver] N-1 resolution LLM call failed: {e}")
            return query


# Factory function
def get_query_resolver(llm_client: Any, turns_dir: Path) -> QueryResolver:
    """Create a QueryResolver instance."""
    return QueryResolver(llm_client=llm_client, turns_dir=turns_dir)
