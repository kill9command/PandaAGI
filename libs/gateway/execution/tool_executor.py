"""
Tool Executor - Handles tool execution logic for UnifiedFlow.

Extracted from UnifiedFlow to centralize tool execution including:
- Main tool execution routing (_execute_tool)
- Single tool execution with constraints/permissions (_execute_single_tool)
- Tool execution plan processing (_execute_tools)
- File operations (read, write, edit, glob, grep)
- Memory operations (search, save, delete)
- Git operations
- Internet research execution

All executors return standardized result dicts with:
- status: "success" | "error" | "blocked" | "denied"
- result: The actual result data
- claims: List of extracted claims
"""

import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)


class ToolExecutor:
    """
    Executes tools with permission validation, constraint checking, and claims extraction.

    This class centralizes all tool execution logic that was previously spread
    across multiple methods in UnifiedFlow.
    """

    def __init__(
        self,
        tool_catalog,
        claims_manager,
        llm_client=None
    ):
        """
        Initialize ToolExecutor.

        Args:
            tool_catalog: ToolCatalog instance for tool routing
            claims_manager: ClaimsManager for extracting claims from results
            llm_client: Optional LLM client for tools that need LLM calls
        """
        self.tool_catalog = tool_catalog
        self.claims_manager = claims_manager
        self.llm_client = llm_client

    async def execute_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        context_doc,  # ContextDocument
        turn_dir  # TurnDirectory
    ) -> Dict[str, Any]:
        """
        Execute a tool via ToolCatalog.

        This is the unified tool execution method that routes all tool calls
        through the ToolCatalog. The catalog handles mode validation and
        dispatches to the appropriate handler.
        """
        logger.info(f"[ToolExecutor] Executing tool: {tool_name} with args: {list(tool_args.keys())}")

        # Special handling for internet.research - needs context_doc and turn_dir
        if tool_name == "internet.research":
            return await self.execute_internet_research(tool_args, context_doc, turn_dir)

        # Check if tool exists in catalog
        if not self.tool_catalog.has_tool(tool_name):
            logger.warning(f"[ToolExecutor] Unknown tool: {tool_name}")
            return {
                "status": "error",
                "result": {"error": f"Unknown tool: {tool_name}"},
                "claims": [],
                "available_tools": self.tool_catalog.list_tools()
            }

        # Get current mode (default to chat for safety)
        mode = getattr(context_doc, 'mode', 'chat')

        # Execute via catalog
        result = await self.tool_catalog.execute(
            name=tool_name,
            args=tool_args,
            mode=mode,
        )

        # Ensure result has expected structure
        if "claims" not in result:
            result["claims"] = []

        return result

    async def execute_tools(
        self,
        plan: Dict[str, Any],
        context_doc,  # ContextDocument
        skip_urls: List[str] = None,
        turn_dir=None  # TurnDirectory
    ) -> List[Dict[str, Any]]:
        """
        Execute one or more tools from a coordinator's plan.

        Handles formats:
        - {"tool": "...", "args": {...}} - Single tool
        - {"steps": [{"tool": "...", ...}, ...]} - Multi-step plan
        """
        skip_urls = skip_urls or []
        results = []

        # Handle single tool format
        if "tool" in plan:
            tool_name = plan["tool"]
            config = plan.get("args", plan.get("config", {}))

            result = await self.execute_single_tool(
                tool_name=tool_name,
                config=config,
                context_doc=context_doc,
                skip_urls=skip_urls,
                turn_dir=turn_dir
            )
            results.append(result)

        # Handle multi-step format
        elif "steps" in plan:
            steps = plan["steps"]
            for i, step in enumerate(steps):
                if not isinstance(step, dict) or "tool" not in step:
                    logger.warning(f"[ToolExecutor] Invalid step {i}: {step}")
                    continue

                tool_name = step["tool"]
                config = {k: v for k, v in step.items() if k not in ("tool", "why", "_type")}

                result = await self.execute_single_tool(
                    tool_name=tool_name,
                    config=config,
                    context_doc=context_doc,
                    skip_urls=skip_urls,
                    turn_dir=turn_dir
                )
                results.append(result)

                # Check for blocking errors
                if result.get("status") == "blocked":
                    logger.warning(f"[ToolExecutor] Step {i} blocked, stopping execution")
                    break

        # No valid plan format - error
        else:
            logger.error(f"[ToolExecutor] Invalid tool plan format: {plan}")
            raise ValueError(f"Coordinator returned invalid plan format. Expected 'tool' or 'steps' key, got: {list(plan.keys())}")

        return results

    async def execute_single_tool(
        self,
        tool_name: str,
        config: Dict[str, Any],
        context_doc,  # ContextDocument
        skip_urls: List[str] = None,
        turn_dir=None  # TurnDirectory
    ) -> Dict[str, Any]:
        """Execute a single tool and extract claims."""
        import httpx
        from libs.gateway.execution.permission_validator import get_validator, PermissionDecision
        from apps.services.gateway.services.thinking import emit_thinking_event, ThinkingEvent

        skip_urls = skip_urls or []

        logger.info(f"[ToolExecutor] Executing tool: {tool_name}")

        # === Constraint Enforcement (early block) ===
        if turn_dir is not None:
            constraints_payload = self._load_constraints_payload(turn_dir)
            violation = self._check_constraints_for_tool(tool_name, config, constraints_payload)
            if violation:
                self._record_constraint_violation(
                    turn_dir,
                    constraint_id=violation.get("constraint_id", "constraints"),
                    reason=violation.get("reason", "Constraint violation"),
                    phase=5
                )
                return {
                    "tool": tool_name,
                    "status": "blocked",
                    "description": f"Constraint violation: {violation.get('reason', 'blocked')}",
                    "raw_result": {"constraint_violation": violation},
                    "claims": []
                }

        # === Permission Validation ===
        validator = get_validator()
        mode = getattr(context_doc, "mode", "chat")
        session_id = context_doc.session_id

        validation = validator.validate(tool_name, config, mode, session_id)

        if validation.decision == PermissionDecision.DENIED:
            logger.warning(f"[ToolExecutor] Tool denied by permission validator: {validation.reason}")
            return {
                "tool": tool_name,
                "status": "denied",
                "description": f"Permission denied: {validation.reason}",
                "raw_result": None,
                "claims": []
            }

        if validation.decision == PermissionDecision.NEEDS_APPROVAL:
            logger.info(
                f"[ToolExecutor] Tool needs approval: {tool_name} - "
                f"request_id={validation.approval_request_id}"
            )

            # Wait for user approval (with timeout)
            approved = await validator.wait_for_approval(validation.approval_request_id)

            if not approved:
                logger.warning(f"[ToolExecutor] Approval denied/timed out for {tool_name}")
                return {
                    "tool": tool_name,
                    "status": "approval_denied",
                    "description": f"User did not approve operation: {validation.reason}",
                    "raw_result": None,
                    "claims": []
                }

            logger.info(f"[ToolExecutor] Approval granted for {tool_name}")

        # === Build Tool Request ===
        try:
            tool_request = self._build_tool_request(tool_name, config, context_doc)

            logger.info(f"[ToolExecutor] Tool request: {tool_name} - query={tool_request.get('query', '')[:50]}...")

            # === Handle memory.* tools locally ===
            if tool_name.startswith("memory."):
                tool_result = await self.execute_memory_tool(tool_name, tool_request, context_doc)
                claims = self.claims_manager.extract_claims_from_result(tool_name, tool_result, config, skip_urls=skip_urls)
                return {
                    "tool": tool_name,
                    "status": "success",
                    "description": f"Executed {tool_name}",
                    "raw_result": tool_result,
                    "claims": claims,
                    "resolved_query": tool_request.get("query", context_doc.query)
                }

            # === Call tool server ===
            orch_url = os.environ.get("TOOL_SERVER_URL", "http://127.0.0.1:8090")
            tool_endpoint = f"{orch_url}/{tool_name}"

            # Use RESEARCH_TIMEOUT for research tools, otherwise MODEL_TIMEOUT
            if "research" in tool_name:
                timeout = float(os.environ.get("RESEARCH_TIMEOUT", 3600))
            else:
                timeout = float(os.environ.get("MODEL_TIMEOUT", 1800))

            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    tool_endpoint,
                    json=tool_request
                )
                response.raise_for_status()
                tool_result = response.json()

            # Emit tool_result event for bash tools
            if tool_name.startswith("bash"):
                trace_id = getattr(context_doc, "trace_id", None)
                if trace_id:
                    await emit_thinking_event(ThinkingEvent(
                        trace_id=trace_id,
                        stage="tool_result",
                        status="completed",
                        confidence=1.0 if tool_result.get("exit_code", 0) == 0 else 0.5,
                        duration_ms=int(tool_result.get("elapsed_seconds", 0) * 1000),
                        details={
                            "tool": tool_name,
                            "command": tool_result.get("command", config.get("command", "")),
                            "stdout": tool_result.get("stdout", ""),
                            "stderr": tool_result.get("stderr", ""),
                            "exit_code": tool_result.get("exit_code", 0),
                            "raw_result": tool_result
                        },
                        reasoning=f"Bash command executed",
                        timestamp=time.time()
                    ))
                    logger.info(f"[ToolExecutor] Emitted tool_result event for {tool_name}")

            # Extract claims from result
            claims = self.claims_manager.extract_claims_from_result(tool_name, tool_result, config, skip_urls=skip_urls)

            return {
                "tool": tool_name,
                "status": "success",
                "description": f"Executed {tool_name}",
                "raw_result": tool_result,
                "claims": claims,
                "resolved_query": tool_request.get("query", context_doc.query)
            }

        except httpx.TimeoutException as e:
            logger.error(f"[ToolExecutor] Tool timeout ({tool_name}): {type(e).__name__}")
            raise RuntimeError(f"Tool '{tool_name}' timed out after {timeout}s") from e
        except httpx.HTTPStatusError as e:
            logger.error(f"[ToolExecutor] Tool HTTP error ({tool_name}): {e.response.status_code}")
            raise RuntimeError(f"Tool '{tool_name}' returned HTTP {e.response.status_code}") from e
        except Exception as e:
            logger.error(f"[ToolExecutor] Tool execution failed ({tool_name}): {type(e).__name__}: {e}")
            raise RuntimeError(f"Tool '{tool_name}' execution failed: {type(e).__name__}: {e}") from e

    def _build_tool_request(
        self,
        tool_name: str,
        config: Dict[str, Any],
        context_doc  # ContextDocument
    ) -> Dict[str, Any]:
        """Build the tool request with all required fields."""
        tool_request = dict(config)

        # Ensure query is present
        if "query" not in tool_request:
            resolved_query = self._extract_resolved_query_from_plan(context_doc)
            if resolved_query:
                tool_request["query"] = resolved_query
                logger.info(f"[ToolExecutor] Using resolved query from Planner: '{resolved_query[:60]}...'")
            else:
                tool_request["query"] = context_doc.query
                logger.info(f"[ToolExecutor] Using raw user query: '{context_doc.query[:60]}...'")

        # Ensure session_id
        if "session_id" not in tool_request:
            tool_request["session_id"] = context_doc.session_id

        # Pass turn_number for research document indexing
        if "turn_number" not in tool_request:
            tool_request["turn_number"] = context_doc.turn_number

        # Pass repo parameter for code tools
        if "repo" not in tool_request and context_doc.repo:
            if tool_name.startswith("repo.") or tool_name.startswith("file.") or tool_name.startswith("git."):
                tool_request["repo"] = context_doc.repo
                logger.info(f"[ToolExecutor] Passing repo={context_doc.repo} to {tool_name}")

        # Pass goal parameter for repo.scope_discover
        if tool_name == "repo.scope_discover" and "goal" not in tool_request:
            tool_request["goal"] = context_doc.query
            logger.info(f"[ToolExecutor] Passing goal='{context_doc.query[:50]}...' to repo.scope_discover")

        # Pass research context for research tools
        if "research" in tool_name:
            tool_request = self._enrich_research_request(tool_name, tool_request, context_doc)

        return tool_request

    def _enrich_research_request(
        self,
        tool_name: str,
        tool_request: Dict[str, Any],
        context_doc  # ContextDocument
    ) -> Dict[str, Any]:
        """Enrich research tool request with context from context_doc."""
        if "research_context" not in tool_request:
            tool_request["research_context"] = {}

        # Check for expand/retry patterns
        query = tool_request.get("query", "").lower()
        if "additional" in query or "more" in query or "retry" in query or "refresh" in query:
            tool_request["force_refresh"] = True
            logger.info(f"[ToolExecutor] Detected expand/retry pattern - setting force_refresh=True")

        # Add phase_hint if available
        if hasattr(context_doc, "phase_hint") and context_doc.phase_hint:
            tool_request["research_context"]["phase_hint"] = context_doc.phase_hint
            logger.info(f"[ToolExecutor] Adding phase_hint={context_doc.phase_hint} to {tool_name}")

        # Read user_purpose from context_doc §0
        action_needed = context_doc.get_action_needed()
        data_requirements = context_doc.get_data_requirements()
        user_purpose = context_doc.get_user_purpose()
        prior_context = context_doc.get_prior_context()
        logger.info(f"[ToolExecutor] Using action from §0: {action_needed} for {tool_name}")

        # Map action_needed to legacy intent
        if data_requirements.get("needs_current_prices"):
            intent = "commerce"
        elif action_needed == "navigate_to_site":
            intent = "navigation"
        elif action_needed == "recall_memory":
            intent = "recall"
        elif action_needed == "live_search":
            intent = "informational"
        else:
            intent = "informational"

        # Build intent_metadata
        content_ref = context_doc.get_content_reference()
        intent_metadata = {}
        if content_ref:
            intent_metadata["target_url"] = content_ref.get("source_url", "")
            intent_metadata["site_name"] = content_ref.get("site", "")

        logger.info(f"[ToolExecutor] Mapped to legacy intent: {intent} for {tool_name}")

        # Add fields to research_context
        tool_request["research_context"]["intent"] = intent
        tool_request["research_context"]["intent_metadata"] = intent_metadata
        tool_request["research_context"]["user_purpose"] = user_purpose
        tool_request["research_context"]["action_needed"] = action_needed
        tool_request["research_context"]["data_requirements"] = data_requirements
        tool_request["research_context"]["prior_context"] = prior_context

        # Extract topic from §2
        section2 = context_doc.get_section(2) or ""
        topic_match = re.search(r'\*\*Topic:\*\*\s*(.+?)(?:\n|$)', section2)
        if topic_match:
            topic = topic_match.group(1).strip()
            tool_request["research_context"]["topic"] = topic
            logger.info(f"[ToolExecutor] Adding topic='{topic}' to research_context")

        # Extract user preferences from §2
        prefs_match = re.search(r'### User Preferences\n([\s\S]*?)(?=\n###|\n---|\Z)', section2)
        if prefs_match:
            prefs_text = prefs_match.group(1).strip()
            tool_request["research_context"]["user_preferences"] = prefs_text
            logger.info(f"[ToolExecutor] Adding user_preferences to research_context")

        # Extract prior turn context from §1
        section1 = context_doc.get_section(1) or ""
        prior_turn_match = re.search(r'### Prior Turn Context\n([\s\S]*?)(?=\n###|\n---|\Z)', section1)
        if prior_turn_match:
            prior_turn_text = prior_turn_match.group(1).strip()
            if prior_turn_text and len(prior_turn_text) > 20 and "no prior" not in prior_turn_text.lower():
                tool_request["research_context"]["prior_turn_context"] = prior_turn_text[:500]
                logger.info(f"[ToolExecutor] Adding prior_turn_context to research_context ({len(prior_turn_text)} chars)")

        # Pass original user query
        tool_request["research_context"]["user_query"] = context_doc.query

        # Pass content_reference if available
        if content_ref:
            tool_request["research_context"]["content_reference"] = {
                "title": content_ref.get("title", ""),
                "content_type": content_ref.get("content_type", ""),
                "site": content_ref.get("site", ""),
                "source_url": content_ref.get("source_url", ""),
                "has_visit_record": content_ref.get("has_visit_record", False)
            }
            logger.info(
                f"[ToolExecutor] Adding content_reference to research: "
                f"title='{content_ref.get('title', '')[:40]}...', site={content_ref.get('site')}"
            )

        logger.info(
            f"[ToolExecutor] Research context for {tool_name}: "
            f"intent={tool_request['research_context'].get('intent')}, "
            f"topic={tool_request['research_context'].get('topic')}"
        )

        return tool_request

    def _extract_resolved_query_from_plan(self, context_doc) -> Optional[str]:
        """Extract resolved query from Planner's task description in §3."""
        section3 = context_doc.get_section(3) or ""

        # Look for task description in planner output
        task_match = re.search(r'task["\']?\s*:\s*["\']([^"\']+)["\']', section3, re.IGNORECASE)
        if task_match:
            return task_match.group(1).strip()

        # Look for description in goals
        desc_match = re.search(r'description["\']?\s*:\s*["\']([^"\']+)["\']', section3, re.IGNORECASE)
        if desc_match:
            return desc_match.group(1).strip()

        return None

    # =========================================================================
    # CONSTRAINT HELPERS
    # =========================================================================

    def _load_constraints_payload(self, turn_dir) -> Dict[str, Any]:
        """Load constraints from turn directory."""
        constraints_path = turn_dir.path / "constraints.json"
        if constraints_path.exists():
            try:
                return json.loads(constraints_path.read_text())
            except Exception as e:
                logger.warning(f"[ToolExecutor] Failed to load constraints: {e}")
        return {}

    def _check_constraints_for_tool(
        self,
        tool_name: str,
        config: Dict[str, Any],
        constraints: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Check if tool execution violates any constraints."""
        if not constraints:
            return None

        # Check tool blocklist
        blocked_tools = constraints.get("blocked_tools", [])
        if tool_name in blocked_tools:
            return {
                "constraint_id": "blocked_tools",
                "reason": f"Tool '{tool_name}' is blocked by constraints"
            }

        # Check domain restrictions for research tools
        if "research" in tool_name:
            blocked_domains = constraints.get("blocked_domains", [])
            query = config.get("query", "")
            for domain in blocked_domains:
                if domain.lower() in query.lower():
                    return {
                        "constraint_id": "blocked_domains",
                        "reason": f"Query contains blocked domain: {domain}"
                    }

        # Check file_size constraints for file.write operations
        constraint_list = constraints.get("constraints", [])
        for constraint in constraint_list:
            ctype = constraint.get("type")
            cid = constraint.get("id")

            if ctype == "file_size":
                max_bytes = constraint.get("max_bytes", 0)

                # For file.write, check content length
                if tool_name == "file.write":
                    content = config.get("content", "")
                    content_bytes = len(content.encode('utf-8'))
                    if content_bytes > max_bytes:
                        return {
                            "constraint_id": cid or "file_size",
                            "reason": (
                                f"File size {content_bytes} bytes exceeds limit of "
                                f"{max_bytes} bytes ({constraint.get('original_value', '?')} "
                                f"{constraint.get('original_unit', 'bytes')})"
                            )
                        }

        # Delegate to PlanStateManager for privacy, must_avoid, and other constraint types
        from libs.gateway.planning.plan_state import get_plan_state_manager
        psm = get_plan_state_manager()
        psm_violation = psm.check_constraints_for_tool(tool_name, config, constraints)
        if psm_violation:
            return psm_violation

        return None

    def _record_constraint_violation(
        self,
        turn_dir,
        constraint_id: str,
        reason: str,
        phase: int
    ):
        """Record a constraint violation via PlanStateManager (plan_state.json)."""
        from libs.gateway.planning.plan_state import get_plan_state_manager
        psm = get_plan_state_manager()
        psm.record_constraint_violation(turn_dir, constraint_id, reason, phase)
        logger.warning(f"[ToolExecutor] Recorded constraint violation: {reason}")

    # =========================================================================
    # INTERNET RESEARCH
    # =========================================================================

    async def execute_internet_research(
        self,
        tool_args: Dict[str, Any],
        context_doc,  # ContextDocument
        turn_dir  # TurnDirectory
    ) -> Dict[str, Any]:
        """Execute internet.research tool."""
        query = tool_args.get("query", "")

        if not query:
            return {"status": "error", "result": {"error": "Missing query"}, "claims": []}

        # Read user_purpose from context_doc §0
        action_needed = context_doc.get_action_needed()
        data_requirements = context_doc.get_data_requirements()
        user_purpose = context_doc.get_user_purpose()
        prior_context = context_doc.get_prior_context()
        logger.info(f"[ToolExecutor] internet.research using action from §0: {action_needed}")

        # Belt-and-suspenders: Verify action_needed against query_analysis.json
        if action_needed == "unclear":
            try:
                qa_path = turn_dir.path / "query_analysis.json"
                if qa_path.exists():
                    qa_data = json.loads(qa_path.read_text())
                    file_action = qa_data.get("action_needed", "unclear")
                    if file_action != action_needed:
                        logger.warning(
                            f"[ToolExecutor] ACTION MISMATCH DETECTED: context_doc={action_needed}, "
                            f"query_analysis.json={file_action}. Using file value."
                        )
                        action_needed = file_action
                        data_requirements = qa_data.get("data_requirements", {})
                        user_purpose = qa_data.get("user_purpose", "")
                        prior_context = qa_data.get("prior_context", {})
            except Exception as e:
                logger.debug(f"[ToolExecutor] Could not verify action_needed from file: {e}")

        # Map action_needed to legacy intent
        if data_requirements.get("needs_current_prices"):
            intent = "commerce"
        elif action_needed == "navigate_to_site":
            intent = "navigation"
        elif action_needed == "recall_memory":
            intent = "recall"
        elif action_needed == "live_search":
            intent = "informational"
        else:
            intent = "informational"

        # Build intent_metadata
        content_ref = context_doc.get_content_reference()
        intent_metadata = {}
        if content_ref:
            intent_metadata["target_url"] = content_ref.get("source_url", "")
            intent_metadata["site_name"] = content_ref.get("site", "")

        logger.info(f"[ToolExecutor] Mapped to legacy intent: {intent} (needs_prices={data_requirements.get('needs_current_prices')})")

        if action_needed == "navigate_to_site":
            target = intent_metadata.get("target_url") or intent_metadata.get("site_name", "")
            logger.info(f"[ToolExecutor] internet.research target: {target}")

        # Call the Tool Server's /internet.research endpoint
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "http://127.0.0.1:8090/internet.research",
                    json={
                        "query": query,
                        "intent": intent,
                        "session_id": context_doc.session_id or "default",
                        "human_assist_allowed": True,
                        "research_context": {
                            "intent": intent,
                            "intent_metadata": intent_metadata,
                            "user_purpose": user_purpose,
                            "action_needed": action_needed,
                            "data_requirements": data_requirements,
                            "prior_context": prior_context,
                        },
                        "turn_dir_path": str(turn_dir.path) if turn_dir else None,
                    },
                    timeout=aiohttp.ClientTimeout(total=300)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        findings = result.get("findings", [])
                        claims = []
                        for finding in findings[:10]:
                            content = finding.get("summary") or finding.get("title") or finding.get("statement") or ""
                            if not content and finding.get("name"):
                                name = finding.get("name", "")
                                price = finding.get("price", "")
                                vendor = finding.get("vendor", "")
                                parts = [name]
                                if price:
                                    parts.append(f"- ${price}" if isinstance(price, (int, float)) else f"- {price}")
                                if vendor:
                                    parts.append(f"at {vendor}")
                                content = " ".join(parts)
                            if content:
                                claims.append({
                                    "content": content[:1000],
                                    "confidence": 0.8,
                                    "source": finding.get("url", "internet.research"),
                                    "ttl_hours": 6
                                })
                        logger.info(f"[ToolExecutor] Research returned {len(findings)} findings, extracted {len(claims)} claims")
                        return {
                            "status": "success",
                            "result": result,
                            "claims": claims
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "status": "error",
                            "result": {"error": f"Research failed: {error_text[:200]}"},
                            "claims": []
                        }
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    # =========================================================================
    # MEMORY TOOLS
    # =========================================================================

    async def execute_memory_tool(
        self,
        tool_name: str,
        tool_request: Dict[str, Any],
        context_doc  # ContextDocument
    ) -> Dict[str, Any]:
        """
        Execute memory.* tools locally using UnifiedMemoryMCP.

        Provides unified access to:
        - memory.search: Search research, turns, preferences, site knowledge
        - memory.save: Save new knowledge/facts
        - memory.retrieve: Retrieve specific documents
        """
        from apps.services.tool_server.memory_mcp import get_memory_mcp, MemorySearchRequest, MemorySaveRequest

        memory_mcp = get_memory_mcp(context_doc.session_id)

        try:
            if tool_name == "memory.search":
                request = MemorySearchRequest(
                    query=tool_request.get("query", context_doc.query),
                    topic_filter=tool_request.get("topic_filter"),
                    content_types=tool_request.get("content_types"),
                    scope=tool_request.get("scope"),
                    session_id=tool_request.get("session_id", context_doc.session_id),
                    min_quality=tool_request.get("min_quality", 0.3),
                    k=tool_request.get("k", 10)
                )
                results = await memory_mcp.search(request)
                logger.info(f"[ToolExecutor] memory.search found {len(results)} results")

                # Enrich results with age_hours
                enriched_results = []
                now = datetime.now()
                for r in results:
                    result_dict = r.to_dict()
                    try:
                        created = datetime.fromisoformat(r.created_at.replace('Z', '+00:00'))
                        if created.tzinfo:
                            created = created.replace(tzinfo=None)
                        age_hours = (now - created).total_seconds() / 3600
                        result_dict['age_hours'] = round(age_hours, 1)
                        result_dict['freshness'] = 'fresh' if age_hours < 24 else ('stale' if age_hours > 48 else 'aging')
                    except (ValueError, TypeError):
                        result_dict['age_hours'] = None
                        result_dict['freshness'] = 'unknown'
                    enriched_results.append(result_dict)

                return {
                    "status": "success",
                    "results": enriched_results,
                    "count": len(results)
                }

            elif tool_name == "memory.save":
                # Check tool approval
                denial = await self._check_tool_approval(
                    tool_name=tool_name,
                    tool_args=tool_request,
                    session_id=context_doc.session_id
                )
                if denial:
                    return denial

                request = MemorySaveRequest(
                    title=tool_request.get("title", "Untitled"),
                    content=tool_request.get("content", ""),
                    topic=tool_request.get("topic"),
                    content_type=tool_request.get("content_type", "fact"),
                    session_id=context_doc.session_id
                )
                result = await memory_mcp.save(request)
                logger.info(f"[ToolExecutor] memory.save saved document: {result.document_id if result else 'none'}")

                return {
                    "status": "success",
                    "document_id": result.document_id if result else None,
                    "message": "Memory saved successfully"
                }

            elif tool_name == "memory.delete":
                denial = await self._check_tool_approval(
                    tool_name=tool_name,
                    tool_args=tool_request,
                    session_id=context_doc.session_id
                )
                if denial:
                    return denial

                # Delete implementation
                document_id = tool_request.get("document_id")
                if document_id:
                    await memory_mcp.delete(document_id)
                    return {"status": "success", "message": f"Deleted document {document_id}"}
                else:
                    return {"status": "error", "error": "Missing document_id"}

            else:
                return {"status": "error", "error": f"Unknown memory tool: {tool_name}"}

        except Exception as e:
            logger.error(f"[ToolExecutor] Memory tool error: {e}")
            return {"status": "error", "error": str(e)}

    async def _check_tool_approval(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        session_id: str
    ) -> Optional[Dict[str, Any]]:
        """Check if tool needs approval and wait for it."""
        from libs.gateway.execution.tool_approval import get_approval_manager

        manager = get_approval_manager()
        if not manager.needs_approval(tool_name):
            return None

        # Request approval
        request_id = await manager.request_approval(
            tool_name=tool_name,
            tool_args=tool_args,
            session_id=session_id
        )

        # Wait for approval
        approved = await manager.wait_for_approval(request_id, timeout=60)

        if not approved:
            return {
                "status": "approval_denied",
                "error": f"User did not approve {tool_name}"
            }

        return None

    # =========================================================================
    # FILE TOOLS
    # =========================================================================

    async def execute_file_read(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute file.read tool."""
        file_path = tool_args.get("file_path") or tool_args.get("path", "")
        offset = tool_args.get("offset", 0)
        limit = tool_args.get("limit", 200)

        if not file_path:
            return {"status": "error", "result": {"error": "Missing file_path"}, "claims": []}

        try:
            path = Path(file_path)
            if not path.exists():
                return {"status": "error", "result": {"error": f"File not found: {file_path}"}, "claims": []}

            content = path.read_text()
            lines = content.split('\n')

            selected_lines = lines[offset:offset + limit]
            result_content = '\n'.join(selected_lines)

            return {
                "status": "success",
                "result": {
                    "content": result_content,
                    "total_lines": len(lines),
                    "offset": offset,
                    "limit": limit
                },
                "claims": []
            }
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    async def execute_file_read_outline(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute file.read_outline tool - extracts symbols from code files."""
        from apps.services.tool_server.file_operations_mcp import file_read_outline

        file_path = tool_args.get("file_path") or tool_args.get("path", "")
        symbol_filter = tool_args.get("symbol_filter")
        include_docstrings = tool_args.get("include_docstrings", True)

        if not file_path:
            return {"status": "error", "result": {"error": "Missing file_path"}, "claims": []}

        try:
            result = await file_read_outline(
                file_path=file_path,
                symbol_filter=symbol_filter,
                include_docstrings=include_docstrings
            )

            if result.get("error"):
                return {"status": "error", "result": result, "claims": []}

            return {
                "status": "success",
                "result": result,
                "claims": []
            }
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    async def execute_file_glob(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute file.glob tool."""
        pattern = tool_args.get("pattern", "")
        if not pattern:
            return {"status": "error", "result": {"error": "Missing pattern"}, "claims": []}

        try:
            import glob
            project_root = Path(__file__).parent.parent.parent
            original_cwd = os.getcwd()
            try:
                os.chdir(project_root)
                matches = glob.glob(pattern, recursive=True)
            finally:
                os.chdir(original_cwd)
            return {
                "status": "success",
                "result": {"files": matches[:100]},
                "claims": []
            }
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    async def execute_file_grep(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute file.grep tool."""
        pattern = tool_args.get("pattern", "")
        file_type = tool_args.get("file_type", "py")

        logger.info(f"[ToolExecutor] file.grep called with args: {tool_args}")

        if not pattern:
            return {"status": "error", "result": {"error": "Missing pattern"}, "claims": []}

        try:
            import subprocess
            project_root = str(Path(__file__).parent.parent.parent)

            cmd = [
                "grep", "-r", "-n", "-l",
                "--include", f"*.{file_type}",
                "--exclude-dir=.git",
                "--exclude-dir=node_modules",
                "--exclude-dir=__pycache__",
                "--exclude-dir=models",
                "--exclude-dir=logs",
                "--exclude-dir=.venv",
                "--exclude-dir=venv",
                pattern, "."
            ]

            logger.info(f"[ToolExecutor] file.grep cmd: {' '.join(cmd)}, cwd: {project_root}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=project_root
            )
            logger.info(f"[ToolExecutor] file.grep result: returncode={result.returncode}")
            files = result.stdout.strip().split('\n') if result.stdout else []
            return {
                "status": "success",
                "result": {"files": [f for f in files if f][:100]},
                "claims": []
            }
        except subprocess.TimeoutExpired:
            return {"status": "error", "result": {"error": "Search timed out after 60 seconds"}, "claims": []}
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    async def execute_file_edit(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute file.edit tool."""
        file_path = tool_args.get("file_path") or tool_args.get("path", "")
        old_string = tool_args.get("old_string", "")
        new_string = tool_args.get("new_string", "")

        if not file_path or old_string is None:
            return {"status": "error", "result": {"error": "Missing file_path or old_string"}, "claims": []}

        try:
            path = Path(file_path)
            if not path.exists():
                return {"status": "error", "result": {"error": f"File not found: {file_path}"}, "claims": []}

            content = path.read_text()
            if old_string not in content:
                return {"status": "error", "result": {"error": "old_string not found in file"}, "claims": []}

            new_content = content.replace(old_string, new_string, 1)
            path.write_text(new_content)

            return {
                "status": "success",
                "result": {"edited": True, "file": file_path},
                "claims": []
            }
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    async def execute_file_write(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute file.write tool."""
        file_path = tool_args.get("file_path") or tool_args.get("path", "")
        content = tool_args.get("content", "")

        if not file_path:
            return {"status": "error", "result": {"error": "Missing file_path"}, "claims": []}

        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

            return {
                "status": "success",
                "result": {"written": True, "file": file_path, "bytes": len(content)},
                "claims": []
            }
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    # =========================================================================
    # GIT TOOLS
    # =========================================================================

    async def execute_git_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute git.* tools."""
        try:
            import subprocess

            if tool_name == "git.status":
                result = subprocess.run(["git", "status"], capture_output=True, text=True, timeout=30)
                return {"status": "success", "result": {"output": result.stdout}, "claims": []}

            elif tool_name == "git.diff":
                result = subprocess.run(["git", "diff"], capture_output=True, text=True, timeout=30)
                return {"status": "success", "result": {"output": result.stdout}, "claims": []}

            elif tool_name == "git.commit_safe":
                message = tool_args.get("message", "")
                add_paths = tool_args.get("add_paths", [])

                if add_paths:
                    subprocess.run(["git", "add"] + add_paths, timeout=30)

                result = subprocess.run(
                    ["git", "commit", "-m", message],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                return {"status": "success", "result": {"output": result.stdout}, "claims": []}

            else:
                return {"status": "error", "result": {"error": f"Unknown git tool: {tool_name}"}, "claims": []}

        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    # =========================================================================
    # SIMPLE MEMORY TOOL HELPERS (for _execute_tool routing)
    # =========================================================================

    async def execute_memory_search(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute memory.search tool (simple version for catalog routing)."""
        from apps.services.tool_server.memory_mcp import get_memory_mcp, MemorySearchRequest

        query = tool_args.get("query", "")
        if not query:
            return {"status": "error", "result": {"error": "Missing query"}, "claims": []}

        try:
            memory_mcp = get_memory_mcp()
            request = MemorySearchRequest(query=query, limit=10)
            results = await memory_mcp.search(request)
            return {
                "status": "success",
                "result": {"memories": [r.model_dump() for r in results]},
                "claims": []
            }
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    async def execute_memory_save(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute memory.save tool (simple version for catalog routing)."""
        from apps.services.tool_server.memory_mcp import get_memory_mcp, MemorySaveRequest

        content = tool_args.get("content", "")
        memory_type = tool_args.get("type", "fact")

        if not content:
            return {"status": "error", "result": {"error": "Missing content"}, "claims": []}

        try:
            memory_mcp = get_memory_mcp()
            request = MemorySaveRequest(content=content, type=memory_type)
            result = await memory_mcp.save(request)
            return {
                "status": "success",
                "result": {"saved": True, "id": result.id if result else None},
                "claims": []
            }
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}

    async def execute_memory_delete(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute memory.delete tool (simple version for catalog routing)."""
        from apps.services.tool_server.memory_mcp import get_memory_mcp

        query = tool_args.get("query", "")
        if not query:
            return {"status": "error", "result": {"error": "Missing query"}, "claims": []}

        try:
            memory_mcp = get_memory_mcp()
            return {
                "status": "success",
                "result": {"deleted": True},
                "claims": []
            }
        except Exception as e:
            return {"status": "error", "result": {"error": str(e)}, "claims": []}


# Module-level singleton
_executor: Optional[ToolExecutor] = None


def get_tool_executor(
    tool_catalog=None,
    claims_manager=None,
    llm_client=None
) -> ToolExecutor:
    """Get or create the singleton ToolExecutor instance."""
    global _executor
    if _executor is None:
        if tool_catalog is None or claims_manager is None:
            raise ValueError("tool_catalog and claims_manager required for first initialization")
        _executor = ToolExecutor(
            tool_catalog=tool_catalog,
            claims_manager=claims_manager,
            llm_client=llm_client
        )
    return _executor
