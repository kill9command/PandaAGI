"""
LLM Tool Generator - Uses LLM to generate tool specs, code, and tests.

Architecture Reference:
- architecture/concepts/SELF_BUILDING_SYSTEM.md
- architecture/concepts/TOOL_SYSTEM.md

Calls the LLM with the tool_generator prompt to produce:
- Tool specification (YAML frontmatter markdown)
- Python implementation
- pytest tests
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Load prompt template
PROMPT_PATH = Path(__file__).parent.parent.parent.parent / "apps" / "prompts" / "tools" / "tool_generator.md"


@dataclass
class GeneratedTool:
    """Result of LLM tool generation."""
    success: bool
    tool_name: str
    spec: Optional[str] = None
    code: Optional[str] = None
    tests: Optional[str] = None
    dependencies: Optional[List[str]] = None
    error: Optional[str] = None
    raw_response: Optional[str] = None


class LLMToolGenerator:
    """
    Generates tool specifications using LLM.

    Uses the tool_generator.md prompt to guide the LLM in producing
    valid tool specs, implementations, and tests.
    """

    def __init__(self, llm_client=None):
        """
        Initialize the generator.

        Args:
            llm_client: LLM client instance (optional, creates default)
        """
        self.llm_client = llm_client
        self._prompt_template: Optional[str] = None

    def _get_prompt_template(self) -> str:
        """Load the prompt template."""
        if self._prompt_template is None:
            if PROMPT_PATH.exists():
                self._prompt_template = PROMPT_PATH.read_text()
            else:
                # Fallback minimal prompt
                self._prompt_template = self._get_fallback_prompt()
        return self._prompt_template

    def _get_fallback_prompt(self) -> str:
        """Minimal fallback prompt if file not found."""
        return """Generate a tool with:
1. spec: YAML frontmatter markdown with name, entrypoint, inputs, outputs
2. code: Python async function implementation
3. tests: pytest tests

Return JSON: {"_type": "TOOL_GENERATED", "spec": "...", "code": "...", "tests": "...", "dependencies": []}
"""

    async def generate(
        self,
        tool_name: str,
        description: str,
        workflow_name: str = "",
        requirements: str = "",
        examples: Optional[List[Dict[str, str]]] = None,
    ) -> GeneratedTool:
        """
        Generate a tool using LLM.

        Args:
            tool_name: Desired tool name (e.g., "spreadsheet.read")
            description: What the tool should do
            workflow_name: Workflow this tool belongs to
            requirements: Additional requirements or constraints
            examples: Optional example inputs/outputs

        Returns:
            GeneratedTool with spec, code, tests
        """
        result = GeneratedTool(success=False, tool_name=tool_name)

        try:
            # Build the prompt
            prompt = self._build_prompt(
                tool_name, description, workflow_name, requirements, examples
            )

            # Call LLM
            llm_response = await self._call_llm(prompt)
            result.raw_response = llm_response

            # Parse response
            parsed = self._parse_response(llm_response)
            if parsed is None:
                result.error = "Failed to parse LLM response as JSON"
                return result

            if parsed.get("_type") != "TOOL_GENERATED":
                result.error = f"Unexpected response type: {parsed.get('_type')}"
                return result

            result.spec = parsed.get("spec", "")
            result.code = parsed.get("code", "")
            result.tests = parsed.get("tests", "")
            result.dependencies = parsed.get("dependencies", [])

            # Validate we got the required fields
            if not result.spec or not result.code:
                result.error = "LLM response missing spec or code"
                return result

            result.success = True
            logger.info(f"[LLMToolGenerator] Successfully generated tool: {tool_name}")
            return result

        except Exception as e:
            result.error = str(e)
            logger.error(f"[LLMToolGenerator] Generation failed: {e}")
            return result

    def _build_prompt(
        self,
        tool_name: str,
        description: str,
        workflow_name: str,
        requirements: str,
        examples: Optional[List[Dict[str, str]]],
    ) -> str:
        """Build the full prompt for LLM."""
        template = self._get_prompt_template()

        # Build the request section
        request = f"""
## Your Task

Generate a tool with the following specifications:

**Tool Name:** {tool_name}
**Description:** {description}
**Workflow:** {workflow_name or "standalone"}
"""

        if requirements:
            request += f"\n**Requirements:**\n{requirements}\n"

        if examples:
            request += "\n**Examples:**\n"
            for ex in examples:
                request += f"- Input: {ex.get('input', '')} -> Output: {ex.get('output', '')}\n"

        request += """
**Important:**
- Return ONLY valid JSON matching the output schema
- Do not include markdown code fences around the JSON
- Ensure the spec YAML is valid
- Ensure the Python code is syntactically correct
"""

        return template + "\n\n---\n\n" + request

    async def _call_llm(self, prompt: str) -> str:
        """Call the LLM with the prompt."""
        if self.llm_client is None:
            from libs.llm.llm_client import get_llm_client
            self.llm_client = get_llm_client()

        response = await self.llm_client.generate(
            prompt=prompt,
            role="mind",  # Use MIND role for reasoning tasks
            max_tokens=4000,  # Tools can be verbose
        )

        return response

    def _parse_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse LLM response as JSON."""
        if not response:
            return None

        # Try direct JSON parse first
        try:
            return json.loads(response.strip())
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code block
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try to find JSON object in response
        json_match = re.search(r'\{[^{}]*"_type"[^{}]*\}', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        # Try more aggressive extraction - find outermost braces
        start = response.find('{')
        end = response.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(response[start:end + 1])
            except json.JSONDecodeError:
                pass

        return None


# Module-level singleton
_generator: Optional[LLMToolGenerator] = None


def get_llm_tool_generator(llm_client=None) -> LLMToolGenerator:
    """Get or create the singleton generator."""
    global _generator
    if _generator is None or llm_client is not None:
        _generator = LLMToolGenerator(llm_client)
    return _generator


async def generate_tool(
    tool_name: str,
    description: str,
    workflow_name: str = "",
    requirements: str = "",
) -> GeneratedTool:
    """Convenience function to generate a tool."""
    generator = get_llm_tool_generator()
    return await generator.generate(tool_name, description, workflow_name, requirements)
