"""Phase 5: Synthesis - Generate user response.

Architecture Reference:
    architecture/main-system-patterns/phase5-synthesis.md

Role: VOICE (MIND model @ temp=0.7) - User Dialogue
Token Budget: ~10,000 total

Question: "How do I present this to the user?"

This is the ONLY model the user "hears" - it serves as the voice
of Pandora, converting structured data into natural, engaging dialogue.

Key Principle: CAPSULE-ONLY - Response must ONLY use data from
context.md (no hallucinations). Every factual claim must have
evidence in section 4 or section 2.
"""

from pathlib import Path
from typing import Optional

from libs.core.models import SynthesisResult
from libs.core.exceptions import PhaseError
from libs.document_io.context_manager import ContextManager

from apps.phases.base_phase import BasePhase


class Synthesis(BasePhase[SynthesisResult]):
    """
    Phase 5: Generate user-facing response.

    Uses VOICE role (MIND model with temp=0.7) for natural,
    engaging user dialogue.

    Two synthesis paths:
    1. With Tools: section 4 claims take precedence (fresh data)
    2. Without Tools: section 2 gathered context (cached/memory)
    """

    PHASE_NUMBER = 5
    PHASE_NAME = "synthesis"

    SYSTEM_PROMPT = """You are Pandora, a helpful AI assistant synthesizing a response for the user.

CRITICAL RULES:
1. Use ONLY information from the provided context and tool results
2. NEVER invent prices, URLs, product names, or specifications
3. If data is missing, acknowledge the gap rather than fabricate
4. Convert all URLs to clickable markdown links: [text](url)
5. Include source citations when referencing factual claims

RESPONSE FORMATTING BY INTENT:

commerce (shopping):
- Structured list with prices and links
- Use headers and bullet points
- Include product specs from research
- Example:
  ## Best Options
  **Product Name - $XXX** at Vendor
  - Key spec 1
  - [View on Vendor](url)

query (informational):
- Prose explanation with inline citations
- Logical flow of information
- Source references at end

recall (memory lookup):
- Direct answer from memory
- Single sentence if possible
- Confirm the stored information

preference (user stating preference):
- Acknowledge and confirm
- "Got it! I'll remember..."

greeting:
- Friendly response
- No elaboration needed

navigation (listing items):
- List exact titles/items from source
- Preserve original wording
- Don't summarize or categorize

code:
- Operation summary
- List files changed
- Show test results if applicable

OUTPUT: Write the response in markdown format.
Also include a validation checklist at the end (for Phase 6):
- [ ] Claims match evidence
- [ ] Intent satisfied
- [ ] No hallucinations
- [ ] Appropriate format"""

    async def execute(
        self,
        context: ContextManager,
        attempt: int = 1,
    ) -> SynthesisResult:
        """
        Generate response from gathered context and tool results.

        Args:
            context: Context manager with sections 0-4
            attempt: Synthesis attempt number (for REVISE loops)

        Returns:
            SynthesisResult with response text
        """
        # Read all context
        full_context = context.get_sections(0, 1, 2, 3, 4)

        # Read toolresults.md for detailed results
        toolresults_path = context.turn_dir / "toolresults.md"
        toolresults = ""
        if toolresults_path.exists():
            toolresults = toolresults_path.read_text()

        # Get original query for context discipline
        original_query = context.get_original_query()

        # Build user prompt
        user_prompt = f"""Original Query: {original_query}

Context Document:
{full_context}

Tool Results (detailed):
{toolresults if toolresults else "(No tool results)"}

Attempt: {attempt}

Generate a helpful, accurate response to the user's query.
Use ONLY information from the context above."""

        # Calculate available tokens for output
        # Model context is 4096, estimate input tokens (~4 chars per token)
        estimated_input_tokens = (len(self.SYSTEM_PROMPT) + len(user_prompt)) // 4
        model_context_limit = 4096
        available_tokens = model_context_limit - estimated_input_tokens - 100  # 100 token buffer

        # Desired max_tokens based on mode
        desired_max_tokens = 3000 if self.mode == "code" else 1500

        # Use the smaller of desired and available
        max_tokens = min(desired_max_tokens, max(300, available_tokens))  # At least 300 tokens

        # Call LLM (automatically uses VOICE role via phase number)
        response = await self.call_llm(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
        )

        # Parse response and extract checklist
        full_response, checklist = self._parse_response(response)

        # Build result
        result = SynthesisResult(
            response_preview=full_response[:500],
            full_response=full_response,
            citations=self._extract_citations(full_response),
            validation_checklist=checklist,
        )

        # Write to section 5
        context.write_section_5(result, attempt)

        # Write full response to response.md
        response_path = context.turn_dir / "response.md"
        response_path.write_text(full_response)

        return result

    def _parse_response(self, response: str) -> tuple[str, dict[str, bool]]:
        """
        Parse response and extract validation checklist.

        Returns:
            Tuple of (clean response, checklist dict)
        """
        # Default checklist
        checklist = {
            "claims_match_evidence": False,
            "intent_satisfied": False,
            "no_hallucinations": False,
            "appropriate_format": False,
        }

        # Try to find and parse checklist
        import re
        checklist_pattern = r"\[([xX ])\]\s*(.+?)(?=\n|\Z)"

        for match in re.finditer(checklist_pattern, response):
            checked = match.group(1).lower() == "x"
            label = match.group(2).strip().lower()

            if "claims" in label and "evidence" in label:
                checklist["claims_match_evidence"] = checked
            elif "intent" in label:
                checklist["intent_satisfied"] = checked
            elif "hallucination" in label:
                checklist["no_hallucinations"] = checked
            elif "format" in label:
                checklist["appropriate_format"] = checked

        # Remove checklist from response for cleaner output
        # Keep everything before the checklist section
        clean_response = response

        # Common checklist markers
        checklist_markers = [
            "**Validation Checklist:**",
            "## Validation Checklist",
            "### Validation Checklist",
            "---\n- [",
            "\n- [ ] Claims",
            "\n- [x] Claims",
        ]

        for marker in checklist_markers:
            if marker in clean_response:
                idx = clean_response.find(marker)
                clean_response = clean_response[:idx].strip()
                break

        return clean_response, checklist

    def _extract_citations(self, response: str) -> list[str]:
        """Extract citations/URLs from response."""
        import re

        citations = []

        # Find markdown links
        link_pattern = r"\[([^\]]+)\]\(([^)]+)\)"
        for match in re.finditer(link_pattern, response):
            text = match.group(1)
            url = match.group(2)
            citations.append(f"{text}: {url}")

        # Find raw URLs
        url_pattern = r"https?://[^\s\)\]>\"']+"
        for match in re.finditer(url_pattern, response):
            url = match.group(0)
            if url not in [c.split(": ")[-1] for c in citations]:
                citations.append(url)

        return citations[:20]  # Limit to 20 citations


# Factory function for convenience
def create_synthesis(mode: str = "chat") -> Synthesis:
    """Create a Synthesis instance."""
    return Synthesis(mode=mode)
