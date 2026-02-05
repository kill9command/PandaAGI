"""Phase 4: Coordinator - Executes tools.

Architecture Reference:
    architecture/main-system-patterns/phase5-coordinator.md

Role: MIND (MIND model @ temp=0.6) - but mostly just executes
This is a THIN execution layer, not a strategic component.

Question: "Which tools are available and how do I execute them?"

Key Principle: Each MCP tool has its own knowledge loop and LLM roles
internally. The Coordinator doesn't manage that complexity - it just
calls tools and receives results.

Responsibilities:
    - Read ticket.md from Planner
    - Call MCP tools via Orchestrator
    - Append results to section 4
    - Return to Orchestrator for loop decision
"""

import json
import re
from pathlib import Path
from typing import Optional, Any

import httpx

from libs.core.config import get_settings
from libs.core.models import (
    ToolExecutionResult,
    ToolResult,
    Claim,
)
from libs.core.exceptions import PhaseError, ToolError
from libs.document_io.context_manager import ContextManager

from apps.phases.base_phase import BasePhase


class Coordinator(BasePhase[ToolExecutionResult]):
    """
    Phase 4: Execute tools.

    This is a THIN execution layer. It:
    1. Reads ticket.md from Planner
    2. Calls MCP tools via Orchestrator
    3. Appends results to section 4
    4. Returns to Orchestrator for loop decision

    Intelligence lives in:
    - Orchestrator (manages overall flow)
    - Individual MCP tools (have their own internal loops)
    """

    PHASE_NUMBER = 4
    PHASE_NAME = "coordinator"

    # Tool -> Orchestrator endpoint mapping
    TOOL_ENDPOINTS = {
        "internet.research": "/research",
        "memory.search": "/memory/query",
        "memory.save": "/memory/create",
        "memory.delete": "/memory/delete",
        "memory.retrieve": "/memory/retrieve",
        "file.read": "/file/read",
        "file.glob": "/file/glob",
        "file.grep": "/file/grep",
        "file.write": "/file/write",
        "file.edit": "/file/edit",
        "file.create": "/file/create",
        "file.delete": "/file/delete",
        "git.add": "/git/add",
        "git.commit": "/git/commit",
        "git.push": "/git/push",
        "git.pull": "/git/pull",
        "git.status": "/git/status",
        "bash.execute": "/bash/execute",
        "test.run": "/test/run",
    }

    # Tools allowed in chat mode (read-only + research + memory)
    CHAT_MODE_TOOLS = {
        "internet.research",
        "memory.search",
        "memory.save",
        "memory.delete",
        "memory.retrieve",
        "file.read",
        "file.glob",
        "file.grep",
    }

    def __init__(self, mode: str = "chat"):
        super().__init__(mode)
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get HTTP client (lazy initialization)."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.tool_server.base_url,
                timeout=120.0,  # Long timeout for research operations
            )
        return self._client

    async def execute(
        self,
        context: ContextManager,
        iteration: int,
    ) -> ToolExecutionResult:
        """
        Execute tools from ticket.md.

        Args:
            context: Context manager
            iteration: Current loop iteration (1-based)

        Returns:
            ToolExecutionResult with results and claims
        """
        # Read ticket
        ticket_path = context.turn_dir / "ticket.md"
        if not ticket_path.exists():
            return ToolExecutionResult(
                iteration=iteration,
                action="DONE",
                reasoning="No ticket found - nothing to execute",
            )

        ticket = ticket_path.read_text()
        tool_requests = self._parse_ticket(ticket)

        if not tool_requests:
            return ToolExecutionResult(
                iteration=iteration,
                action="DONE",
                reasoning="No tool requests in ticket",
            )

        # Execute each tool
        results: list[ToolResult] = []
        claims: list[Claim] = []

        for request in tool_requests:
            tool = request["tool"]
            args = request.get("args", {})
            goal_id = request.get("goal_id")

            # Validate tool is allowed in current mode
            if not self._is_tool_allowed(tool):
                results.append(
                    ToolResult(
                        tool=tool,
                        goal_id=goal_id,
                        success=False,
                        result=None,
                        error=f"Tool '{tool}' not allowed in {self.mode} mode",
                    )
                )
                continue

            # Execute tool
            result = await self._call_tool(tool, args, goal_id)
            results.append(result)

            # Extract claims from successful results
            if result.success and result.result:
                extracted = self._extract_claims(tool, result.result)
                claims.extend(extracted)

        # Determine action based on results
        any_success = any(r.success for r in results)
        action = "TOOL_CALL" if any_success else "BLOCKED"

        # Build execution result
        execution = ToolExecutionResult(
            iteration=iteration,
            action=action,
            reasoning=f"Executed {len(results)} tools, {sum(1 for r in results if r.success)} succeeded",
            tool_results=results,
            claims_extracted=claims,
            progress_summary=self._build_progress_summary(results),
        )

        # Append to section 4
        context.append_section_4(execution)

        # Write detailed results to toolresults.md
        self._write_toolresults(context.turn_dir, execution)

        return execution

    def _is_tool_allowed(self, tool: str) -> bool:
        """Check if tool is allowed in current mode."""
        if self.mode == "code":
            # All tools allowed in code mode
            return tool in self.TOOL_ENDPOINTS
        else:
            # Only read-only + research + memory in chat mode
            return tool in self.CHAT_MODE_TOOLS

    async def _call_tool(
        self,
        tool: str,
        args: dict[str, Any],
        goal_id: Optional[str] = None,
    ) -> ToolResult:
        """Call a tool via Orchestrator."""
        endpoint = self.TOOL_ENDPOINTS.get(tool)
        if not endpoint:
            return ToolResult(
                tool=tool,
                goal_id=goal_id,
                success=False,
                result=None,
                error=f"Unknown tool: {tool}",
            )

        try:
            response = await self.client.post(
                endpoint,
                json=args,
                headers={
                    "X-Panda-Mode": self.mode,
                    "Content-Type": "application/json",
                },
            )

            if response.status_code == 200:
                result_data = response.json()
                return ToolResult(
                    tool=tool,
                    goal_id=goal_id,
                    success=True,
                    result=result_data,
                    confidence=result_data.get("confidence", 1.0),
                )
            else:
                return ToolResult(
                    tool=tool,
                    goal_id=goal_id,
                    success=False,
                    result=None,
                    error=f"HTTP {response.status_code}: {response.text[:200]}",
                )

        except httpx.TimeoutException:
            return ToolResult(
                tool=tool,
                goal_id=goal_id,
                success=False,
                result=None,
                error="Request timeout",
            )
        except Exception as e:
            return ToolResult(
                tool=tool,
                goal_id=goal_id,
                success=False,
                result=None,
                error=str(e),
            )

    def _parse_ticket(self, ticket: str) -> list[dict[str, Any]]:
        """Parse ticket.md into tool requests."""
        requests = []

        # Look for tool request sections
        # Format: ### tool.name followed by **Args:** {...}
        tool_pattern = r"###\s+(\S+)\s*\n+\*\*Args:\*\*\s*(.+?)(?=\n###|\n##|\Z)"

        for match in re.finditer(tool_pattern, ticket, re.DOTALL):
            tool = match.group(1).strip()
            args_str = match.group(2).strip()

            # Handle multi-line args
            args_str = args_str.split("\n")[0].strip()

            try:
                args = json.loads(args_str)
            except json.JSONDecodeError:
                # Try to extract just the JSON part
                json_match = re.search(r"\{.*\}", args_str)
                if json_match:
                    try:
                        args = json.loads(json_match.group(0))
                    except json.JSONDecodeError:
                        args = {}
                else:
                    args = {}

            # Look for goal_id
            goal_match = re.search(r"\*\*Goal:\*\*\s*(\S+)", ticket[match.end():match.end()+100])
            goal_id = goal_match.group(1) if goal_match else None

            requests.append({
                "tool": tool,
                "args": args,
                "goal_id": goal_id,
            })

        return requests

    def _extract_claims(self, tool: str, result: Any) -> list[Claim]:
        """Extract claims from tool result."""
        claims = []

        if not isinstance(result, dict):
            return claims

        # Handle internet.research results
        if tool == "internet.research":
            findings = result.get("findings", [])
            for finding in findings[:10]:  # Limit to top 10
                if isinstance(finding, dict):
                    claim_text = self._format_finding_claim(finding)
                    if claim_text:
                        claims.append(
                            Claim(
                                claim=claim_text,
                                confidence=finding.get("confidence", 0.8),
                                source=finding.get("source", "internet.research"),
                                ttl_hours=6,  # Default 6-hour TTL for commerce
                            )
                        )

        # Handle memory.search results
        elif tool == "memory.search":
            memories = result.get("memories", [])
            for memory in memories:
                if isinstance(memory, dict):
                    claims.append(
                        Claim(
                            claim=memory.get("content", ""),
                            confidence=memory.get("confidence", 0.9),
                            source="memory",
                            ttl_hours=None,  # Memory doesn't expire
                        )
                    )

        return claims

    def _format_finding_claim(self, finding: dict) -> str:
        """Format a research finding as a claim string."""
        parts = []

        if finding.get("name") or finding.get("title"):
            parts.append(finding.get("name") or finding.get("title"))

        if finding.get("price"):
            parts.append(f"@ {finding['price']}")

        if finding.get("vendor") or finding.get("source"):
            vendor = finding.get("vendor") or finding.get("source")
            parts.append(f"({vendor})")

        if finding.get("url"):
            parts.append(f"- {finding['url']}")

        return " ".join(parts) if parts else ""

    def _build_progress_summary(self, results: list[ToolResult]) -> str:
        """Build a progress summary from tool results."""
        success_count = sum(1 for r in results if r.success)
        total = len(results)

        if success_count == total:
            return f"All {total} tools executed successfully"
        elif success_count == 0:
            return f"All {total} tools failed"
        else:
            return f"{success_count}/{total} tools succeeded"

    def _write_toolresults(self, turn_dir: Path, execution: ToolExecutionResult) -> None:
        """Write detailed results to toolresults.md."""
        results_path = turn_dir / "toolresults.md"

        # Build content for this iteration
        content = f"""
## Iteration {execution.iteration}

**Action:** {execution.action}
**Reasoning:** {execution.reasoning}

"""
        # Tool results
        for result in execution.tool_results:
            content += f"### {result.tool}\n\n"
            content += f"**Success:** {result.success}\n"

            if result.goal_id:
                content += f"**Goal:** {result.goal_id}\n"

            if result.success:
                # Format result nicely
                if isinstance(result.result, dict):
                    content += f"**Result:**\n```json\n{json.dumps(result.result, indent=2, default=str)[:2000]}\n```\n"
                else:
                    content += f"**Result:** {str(result.result)[:500]}\n"
            else:
                content += f"**Error:** {result.error}\n"

            content += "\n"

        # Claims extracted
        if execution.claims_extracted:
            content += "### Claims Extracted\n\n"
            content += "| Claim | Confidence | Source | TTL |\n"
            content += "|-------|------------|--------|-----|\n"
            for claim in execution.claims_extracted:
                ttl = f"{claim.ttl_hours}h" if claim.ttl_hours else "N/A"
                # Truncate long claims
                claim_text = claim.claim[:100] + "..." if len(claim.claim) > 100 else claim.claim
                content += f"| {claim_text} | {claim.confidence:.2f} | {claim.source} | {ttl} |\n"
            content += "\n"

        # Append to existing file or create new
        if results_path.exists():
            existing = results_path.read_text()
            results_path.write_text(existing + content)
        else:
            header = f"# Tool Results\n\n**Turn:** {turn_dir.name}\n"
            results_path.write_text(header + content)

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# Factory function for convenience
def create_coordinator(mode: str = "chat") -> Coordinator:
    """Create a Coordinator instance."""
    return Coordinator(mode=mode)
