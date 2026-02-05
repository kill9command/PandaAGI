"""
Document Writer Helpers for v4.0

Utilities to write structured data to markdown/JSON documents.

Author: v4.0 Migration
Date: 2025-11-16
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


def write_markdown_doc(
    path: Path,
    title: str,
    sections: Dict[str, str],
    metadata: Optional[Dict[str, str]] = None
) -> int:
    """
    Write a structured markdown document.

    Args:
        path: Path to write to
        title: Document title (H1)
        sections: Dict of {section_name: content}
        metadata: Optional metadata to include at top

    Returns:
        Number of characters written
    """
    content = f"# {title}\n\n"

    if metadata:
        for key, value in metadata.items():
            content += f"**{key}:** {value}  \n"
        content += "\n"

    for section_name, section_content in sections.items():
        content += f"## {section_name}\n{section_content}\n\n"

    path.write_text(content)
    return len(content)


def write_json_doc(path: Path, data: Dict[str, Any], pretty: bool = True) -> int:
    """
    Write a JSON document.

    Args:
        path: Path to write to
        data: Data to serialize
        pretty: Whether to use indentation

    Returns:
        Number of bytes written
    """
    with open(path, 'w') as f:
        if pretty:
            json.dump(data, f, indent=2)
        else:
            json.dump(data, f)

    return path.stat().st_size


# ==============================================================================
# Specific Document Writers
# ==============================================================================

def write_context_md(
    turn_dir: 'TurnDirectory',
    ctx: 'UnifiedContext'
) -> Path:
    """
    Write context.md from UnifiedContext object.

    Note: This is the canonical name as of 2025-11-27.
    Previously named write_unified_context_md.

    As of 2025-12-02, context.md is the SINGLE flowing document that:
    1. Gets created in Phase 1 with cached claims
    2. Gets updated in Phase 5 with fresh claims (if tools executed)
    3. Gets read by Synthesis in Phase 6

    Args:
        turn_dir: TurnDirectory instance
        ctx: UnifiedContext from unified_context.py

    Returns:
        Path to written file
    """
    sections = {}

    # Session State (current conversation context)
    session_content = ""
    if ctx.living_context:
        session_content = ctx.living_context.content
        sections["Session State"] = session_content

    # CONTEXT PRUNING: Extract focus entity from Previous turn for follow-up queries
    # If Previous turn mentions a specific product, we filter claims to only show that product
    focus_entity = None
    if session_content and "Previous turn:" in session_content:
        import re
        # Extract the product name from "Previous turn: Found... [Product Name] at $X"
        # Common patterns: "Found the cheapest laptop: Acer Nitro V Gaming Laptop at $725"
        prev_match = re.search(r'Previous turn:.*?(?:Found|Recommended|cheapest|best)[^:]*?[:\s]+([A-Z][^@$\n]+?)(?:\s+at\s+\$|\s+@\s+\$|\s+for\s+\$|\s*$)', session_content, re.IGNORECASE)
        if prev_match:
            focus_entity = prev_match.group(1).strip()
            # Clean up trailing punctuation
            focus_entity = re.sub(r'[,;.\s]+$', '', focus_entity)
            if len(focus_entity) > 10:  # Minimum length to be a valid product name
                logger.info(f"[DocWriter] CONTEXT PRUNING: Focus entity from Previous turn: '{focus_entity}'")

    # Current Claims - ALL existing knowledge merged into one section:
    # - Product claims (from Claim Registry)
    # - Long-term memories (cross-session)
    # - Discovered facts (session-based)
    claim_lines = []

    # Add long-term memories
    if ctx.long_term_memories:
        for mem in ctx.long_term_memories:
            claim_lines.append(f"- {mem.content} (memory, confidence: {mem.confidence:.2f})")

    # Add product claims - WITH PRUNING if focus_entity is set
    if ctx.recent_claims:
        # If we have a focus entity, filter claims to only those matching it
        claims_to_show = ctx.recent_claims
        if focus_entity:
            # Normalize focus entity for matching
            focus_lower = focus_entity.lower()
            focus_words = set(focus_lower.split())

            # Filter to claims that match the focus entity
            matching_claims = []
            for claim in ctx.recent_claims:
                metadata = claim.metadata if hasattr(claim, 'metadata') and claim.metadata else {}
                product_name = metadata.get('product_name', claim.content if hasattr(claim, 'content') else '')
                product_lower = product_name.lower()

                # Check if product name matches focus entity (word overlap or substring)
                product_words = set(product_lower.split())
                word_overlap = len(focus_words & product_words)

                # Match if: significant word overlap, or focus entity is substring of product name
                if word_overlap >= 2 or focus_lower in product_lower or product_lower in focus_lower:
                    matching_claims.append(claim)

            if matching_claims:
                claims_to_show = matching_claims
                logger.info(f"[DocWriter] CONTEXT PRUNING: Filtered {len(ctx.recent_claims)} claims down to {len(matching_claims)} matching '{focus_entity}'")
            else:
                # No matches - show the focus entity info from session state and skip claims
                logger.info(f"[DocWriter] CONTEXT PRUNING: No claims match focus entity '{focus_entity}', showing minimal claims")
                claims_to_show = []  # Don't confuse with unrelated products

        for claim in claims_to_show:
            metadata = claim.metadata if hasattr(claim, 'metadata') and claim.metadata else {}
            product_name = metadata.get('product_name', '')
            price = metadata.get('price', '')
            vendor = metadata.get('vendor', '')
            url = metadata.get('url', '')

            if product_name and price:
                line = f"- **{product_name}** @ {price}"
                if vendor:
                    line += f" ({vendor})"
                if url:
                    line += f" - [link]({url})"
                line += f" (confidence: {claim.confidence:.2f})"
            else:
                line = f"- {claim.content} (confidence: {claim.confidence:.2f})"
            claim_lines.append(line)

    # Add discovered facts
    if ctx.discovered_facts:
        for fact in ctx.discovered_facts:
            claim_lines.append(f"- {fact.content}")

    sections["Current Claims"] = "\n".join(claim_lines) if claim_lines else "(no current data)"

    # Fresh Claims - populated by Phase 5 if tools execute
    sections["Fresh Claims"] = "(pending - will be populated after tool execution)"

    metadata = {
        "Total Items": str(ctx.total_items),
        "Est. Tokens": str(ctx.total_estimated_tokens),
        "Gather Time": f"{ctx.gather_time_ms:.1f}ms"
    }

    path = turn_dir.doc_path("context.md")
    chars_written = write_markdown_doc(path, "Context", sections, metadata)

    logger.info(f"[DocWriter] Wrote context.md ({chars_written} chars, {ctx.total_estimated_tokens} tokens)")
    return path


def append_fresh_claims_to_context(
    turn_dir: 'TurnDirectory',
    fresh_claims: List[Dict[str, Any]],
    source: str = "tool_execution"
) -> Path:
    """
    Append fresh claims to context.md (Phase 5 claim extraction).

    This updates the "Fresh Claims" section of context.md with claims
    extracted from tool execution results.

    Args:
        turn_dir: TurnDirectory instance
        fresh_claims: List of claim dicts with:
            - product_name or statement: The claim text
            - price: Price if product claim
            - vendor: Vendor if product claim
            - url: URL if available
            - confidence: Confidence score (0-1)
        source: Source of claims (for logging)

    Returns:
        Path to updated file
    """
    path = turn_dir.doc_path("context.md")

    # Handle missing context.md - create minimal structure
    if not path.exists():
        logger.warning(f"[DocWriter] context.md not found, creating minimal structure")
        content = """# Context

## Session State
(no session state)

## Current Claims
(no current claims)

## Fresh Claims
(pending - will be populated after tool execution)
"""
        path.write_text(content)
    else:
        content = path.read_text()

    # Validate content is not empty
    if not content.strip():
        logger.warning(f"[DocWriter] context.md is empty, rebuilding structure")
        content = """# Context

## Session State
(no session state)

## Current Claims
(no current claims)

## Fresh Claims
(pending - will be populated after tool execution)
"""

    # Validate Fresh Claims section exists
    if "## Fresh Claims" not in content:
        logger.warning(f"[DocWriter] context.md missing Fresh Claims section, appending")
        content += "\n\n## Fresh Claims\n(pending - will be populated after tool execution)"

    # Build fresh claims section
    if fresh_claims:
        claim_lines = []
        for claim in fresh_claims:
            # Handle both product claims and general claims
            product_name = claim.get('product_name') or claim.get('name', '')
            statement = claim.get('statement', '')
            price = claim.get('price', '')
            vendor = claim.get('vendor', '')
            url = claim.get('url', '')
            confidence = claim.get('confidence', 0.7)

            if product_name and price:
                # Structured product claim
                line = f"- **{product_name}** @ {price}"
                if vendor:
                    line += f" ({vendor})"
                if url:
                    line += f" - [link]({url})"
                line += f" (confidence: {confidence:.2f})"
            elif statement:
                line = f"- {statement} (confidence: {confidence:.2f})"
            else:
                continue  # Skip malformed claims

            claim_lines.append(line)

        fresh_section = "\n".join(claim_lines) if claim_lines else "(no fresh claims extracted)"
    else:
        fresh_section = "(no fresh claims - tools returned no results)"

    # Replace the placeholder in Fresh Claims section
    old_fresh = "## Fresh Claims\n(pending - will be populated after tool execution)"
    new_fresh = f"## Fresh Claims\n{fresh_section}"

    if old_fresh in content:
        content = content.replace(old_fresh, new_fresh)
    else:
        # Fallback: try to find and replace just the section content
        import re
        # Match ## Fresh Claims until next ## or end of file
        pattern = r'(## Fresh Claims\n).*?(?=\n## |\n\Z|\Z)'
        replacement = f'\\1{fresh_section}'
        content = re.sub(pattern, replacement, content, flags=re.DOTALL)

    path.write_text(content)

    logger.info(f"[DocWriter] Updated context.md with {len(fresh_claims)} fresh claims (source: {source})")
    return path


# Backward compatibility alias
write_unified_context_md = write_context_md


def write_intent_json(turn_dir: 'TurnDirectory', intent: str, domain: str, confidence: float, is_retry: bool = False) -> Path:
    """Write intent.json with retry flag for observability"""
    data = {
        "intent": intent,
        "domain": domain,
        "confidence": confidence,
        "is_retry": is_retry,  # NEW: Track retry requests for observability
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    path = turn_dir.doc_path("intent.json")
    write_json_doc(path, data)

    retry_flag = " [RETRY]" if is_retry else ""
    logger.info(f"[DocWriter] Wrote intent.json (intent={intent}{retry_flag}, domain={domain}, conf={confidence:.2f})")
    return path


def write_meta_reflection_md(turn_dir: 'TurnDirectory', result: 'MetaReflectionResult') -> Path:
    """Write meta_reflection.md from MetaReflectionResult"""
    sections = {
        "Query Analysis": f"""- Clarity: {'HIGH' if result.confidence > 0.8 else 'MEDIUM' if result.confidence > 0.5 else 'LOW'}
- Context sufficiency: {'SUFFICIENT' if result.can_proceed else 'INSUFFICIENT'}
- Ambiguity: {'NONE' if result.confidence > 0.7 else 'SOME'}""",

        "Decision": f"""{result.action.value.upper()}
- Confidence: {result.confidence:.2f}
- Reasoning: {result.reason}""",

        "Information Gaps": "NONE" if not result.needs_info else "\n".join(
            [f"- {req.type}: {req.query} ({req.reason})" for req in result.info_requests]
        )
    }

    if result.query_type:
        sections["Query Type"] = result.query_type

    metadata = {
        "Timestamp": datetime.now(timezone.utc).isoformat(),
        "Role": result.role,
        "Token Cost": f"~{result.token_cost} tokens"
    }

    path = turn_dir.doc_path("meta_reflection.md")
    write_markdown_doc(path, "Meta-Reflection Decision", sections, metadata)

    logger.info(f"[DocWriter] Wrote meta_reflection.md (action={result.action.value}, conf={result.confidence:.2f})")
    return path


def write_cache_decision_md(
    turn_dir: 'TurnDirectory',
    response_hit: bool,
    claims_hit: bool,
    tool_hits: Dict[str, bool],
    reasoning: str
) -> Path:
    """Write cache_decision.md"""
    sections = {
        "Layer 1: Response Cache": f"""- Status: {'HIT' if response_hit else 'MISS'}
- Reason: {reasoning if not response_hit else 'Semantically similar query found'}""",

        "Layer 2: Claims Cache": f"""- Status: {'HIT' if claims_hit else 'MISS'}
- Claims registry checked: Yes""",

        "Layer 3: Tool Cache": f"""- Status: DEFERRED (checked at tool execution time)
- Tools to check: {', '.join(tool_hits.keys()) if tool_hits else 'TBD'}"""
    }

    path = turn_dir.doc_path("cache_decision.md")
    write_markdown_doc(path, "Cache Evaluation Results", sections)

    logger.info(f"[DocWriter] Wrote cache_decision.md (response={response_hit}, claims={claims_hit})")
    return path


def write_ticket_json(turn_dir: 'TurnDirectory', ticket: Dict[str, Any]) -> Path:
    """
    Write ticket.json - preserves full ticket structure.

    This is the machine-readable version that preserves:
    - parse.entities: Extracted entities from user message
    - resolution: Entity resolution status and resolved values
    - research_type: Type of research needed (commerce, technical_specs, etc.)
    - constraints: Budget and preference constraints

    Args:
        turn_dir: TurnDirectory instance
        ticket: Full ticket dict from Planner

    Returns:
        Path to written file
    """
    path = turn_dir.doc_path("ticket.json")
    write_json_doc(path, ticket)

    # Handle both new and old schema for logging
    parse_data = ticket.get("parse", {})
    entities = parse_data.get("entities") or ticket.get("entities", [])
    resolution = ticket.get("resolution", {})
    resolved_entity = resolution.get("resolved_entity")
    research_type = ticket.get("research_type", "general")
    route_to = ticket.get("route_to", "unknown")

    logger.info(
        f"[DocWriter] Wrote ticket.json "
        f"(route_to={route_to}, entities={len(entities)}, "
        f"resolved={resolved_entity or 'none'}, research_type={research_type})"
    )
    return path


def write_ticket_md(turn_dir: 'TurnDirectory', ticket: Dict[str, Any]) -> Path:
    """Write ticket.md from TICKET JSON

    Handles three schema versions:
    - v3.0 (new): route_to, parse, resolution, research_type
    - v2.0 (old): goal, subtasks
    - v1.0 (fallback): user_need, recommended_tools
    """

    # Detect schema version and normalize
    if "route_to" in ticket and "parse" in ticket:
        # v3.0 simplified schema
        user_need = ticket.get("reason", "Process user request")
        parse_data = ticket.get("parse", {})
        resolution = ticket.get("resolution", {})

        # Build context from parse data
        context_items = []
        context_items.append(f"intent: {parse_data.get('intent', 'unknown')}")
        if parse_data.get("entities"):
            context_items.append(f"entities: {', '.join(parse_data['entities'])}")
        if parse_data.get("specs"):
            context_items.append(f"specs: {', '.join(parse_data['specs'])}")
        if parse_data.get("question"):
            context_items.append(f"question: {parse_data['question']}")
        if resolution.get("resolved_entity"):
            context_items.append(f"resolved_entity: {resolution['resolved_entity']}")
        context_str = "\n".join([f"- {item}" for item in context_items])

        # Determine tools from route_to
        route_to = ticket.get("route_to", "coordinator")
        research_type = ticket.get("research_type", "general")
        if route_to == "coordinator":
            recommended_tools = f"- internet.research ({research_type})"
        elif route_to == "synthesis":
            recommended_tools = "- (no tools needed - direct synthesis)"
        else:
            recommended_tools = "- (clarification needed)"

        # Format constraints
        constraints_dict = ticket.get("constraints", {})
        if constraints_dict:
            constraints_list = [f"- {k}: {v}" for k, v in constraints_dict.items()]
        else:
            constraints_list = ["- (no constraints)"]
        constraints_str = "\n".join(constraints_list)

        success_str = "- Route correctly and provide accurate response"

    elif "goal" in ticket:
        # Old schema from strategic.md prompt
        user_need = ticket.get("goal", "")
        context_items = []

        # Add analysis if present
        if "analysis" in ticket:
            context_items.append(f"analysis: {ticket['analysis']}")

        # Add detected_intent if present
        if "detected_intent" in ticket:
            context_items.append(f"intent: {ticket['detected_intent']}")

        # Add micro_plan if present
        if "micro_plan" in ticket:
            for step in ticket.get("micro_plan", []):
                context_items.append(f"plan: {step}")

        context_str = "\n".join([f"- {item}" for item in context_items]) if context_items else ""

        # Extract tools from subtasks
        tools = []
        for subtask in ticket.get("subtasks", []):
            kind = subtask.get("kind", "search")
            if kind == "search":
                tools.append("internet.research")
            elif kind == "code":
                tools.append("file.read")
            elif kind == "fetch":
                tools.append("playwright.visit")

        # Remove duplicates
        tools = list(dict.fromkeys(tools))
        recommended_tools = "\n".join([f"- {tool}" for tool in tools]) if tools else "- (no tools needed)"

        # Format constraints
        constraints_dict = ticket.get("constraints", {})
        if isinstance(constraints_dict, dict):
            constraints_list = [f"- {k}: {v}" for k, v in constraints_dict.items()]
        else:
            constraints_list = ["- (no constraints)"]
        constraints_str = "\n".join(constraints_list)

        # Success criteria from reflection
        success_criteria = []
        if "reflection" in ticket and "success_criteria" in ticket["reflection"]:
            success_criteria.append(f"- {ticket['reflection']['success_criteria']}")
        if not success_criteria:
            success_criteria = ["- Provide accurate answer to user query"]
        success_str = "\n".join(success_criteria)

    else:
        # New schema from fallback
        user_need = ticket.get("user_need", "")
        context_str = "\n".join([f"- {k}: {v}" for k, v in ticket.get("context", {}).items()])
        recommended_tools = "\n".join([f"- {tool}" for tool in ticket.get("recommended_tools", [])])

        constraints = ticket.get("constraints", [])
        if isinstance(constraints, list):
            constraints_str = "\n".join([f"- {c}" for c in constraints])
        else:
            constraints_str = "\n".join([f"- {k}: {v}" for k, v in constraints.items()])

        success_str = "\n".join([f"- {c}" for c in ticket.get("success_criteria", [])])

    # Build sections
    sections = {
        "User Need": user_need,
        "Context": context_str,
        "Recommended Tools": recommended_tools,
        "Constraints": constraints_str,
        "Success Criteria": success_str
    }

    if "estimated_complexity" in ticket:
        sections["Estimated Complexity"] = ticket["estimated_complexity"]

    path = turn_dir.doc_path("ticket.md")
    write_markdown_doc(path, "Task Ticket", sections)

    # Count tools for logging
    tool_count = len(ticket.get("recommended_tools", [])) if "recommended_tools" in ticket else len(ticket.get("subtasks", []))
    logger.info(f"[DocWriter] Wrote ticket.md ({tool_count} tools)")
    return path


def write_plan_md(turn_dir: 'TurnDirectory', plan: Dict[str, Any]) -> Path:
    """Write plan.md from PLAN JSON"""
    sections = {
        "Tools Selected": "\n".join([f"{i+1}. {tool}" for i, tool in enumerate(plan.get("tools_selected", []))]),
        "Tool Configuration": f"```json\n{json.dumps(plan.get('tool_config', {}), indent=2)}\n```",
        "Execution Sequence": "\n".join([f"{i+1}. {step}" for i, step in enumerate(plan.get("execution_sequence", []))]),
        "Quality Gates": "\n".join([f"- {gate}" for gate in plan.get("quality_gates", [])])
    }

    path = turn_dir.doc_path("plan.md")
    write_markdown_doc(path, "Execution Plan", sections)

    logger.info(f"[DocWriter] Wrote plan.md ({len(plan.get('tools_selected', []))} tools)")
    return path


def write_bundle_json(turn_dir: 'TurnDirectory', bundle: Dict[str, Any]) -> Path:
    """Write bundle.json with tool execution results"""
    path = turn_dir.doc_path("bundle.json")
    write_json_doc(path, bundle)

    tool_count = len(bundle.get("tool_executions", []))
    logger.info(f"[DocWriter] Wrote bundle.json ({tool_count} tool executions)")
    return path


def write_phase1_intelligence_md(
    turn_dir: 'TurnDirectory',
    intelligence_summary: str,
    sources_count: int,
    key_findings: List[str]
) -> Path:
    """
    Write phase1_intelligence.md with research intelligence summary.

    This enables document-driven architecture where Phase 1 research outputs
    are summarized in markdown instead of loaded directly into prompts.

    Args:
        turn_dir: TurnDirectory instance
        intelligence_summary: High-level summary of intelligence gathered
        sources_count: Number of sources consulted
        key_findings: List of key findings from research

    Returns:
        Path to written file
    """
    sections = {
        "Intelligence Summary": intelligence_summary,
        "Key Findings": "\n".join([f"{i+1}. {finding}" for i, finding in enumerate(key_findings)]),
        "Sources Consulted": f"{sources_count} sources"
    }

    metadata = {
        "Timestamp": datetime.now(timezone.utc).isoformat(),
        "Phase": "Phase 1 Intelligence Gathering"
    }

    path = turn_dir.doc_path("phase1_intelligence.md")
    write_markdown_doc(path, "Phase 1 Intelligence Summary", sections, metadata)

    logger.info(f"[DocWriter] Wrote phase1_intelligence.md ({sources_count} sources, {len(key_findings)} findings)")
    return path


def write_bundlechunks_json(
    turn_dir: 'TurnDirectory',
    bundle: Dict[str, Any],
    max_chunk_tokens: int = 2000
) -> List[Path]:
    """
    Write bundle as multiple chunked JSON files (bundle_part_001.json, bundle_part_002.json, etc.)

    This enables streaming CM intake where Context Manager processes chunks incrementally
    instead of loading entire bundle into memory.

    Args:
        turn_dir: TurnDirectory instance
        bundle: Bundle dict with tool_executions list
        max_chunk_tokens: Maximum tokens per chunk (default: 2000)

    Returns:
        List of paths to written chunk files
    """
    tool_executions = bundle.get("tool_executions", [])

    if not tool_executions:
        # No executions - write empty bundle as single file
        path = turn_dir.doc_path("bundle_part_001.json")
        write_json_doc(path, bundle)
        logger.info(f"[DocWriter] Wrote bundle_part_001.json (empty)")
        return [path]

    # Chunk tool executions by token count
    chunks = []
    current_chunk = []
    current_tokens = 0

    for execution in tool_executions:
        # Estimate tokens in execution (rough: JSON string length / 4)
        execution_json = json.dumps(execution)
        execution_tokens = len(execution_json) // 4

        if current_tokens + execution_tokens > max_chunk_tokens and current_chunk:
            # Save current chunk and start new one
            chunks.append(current_chunk)
            current_chunk = [execution]
            current_tokens = execution_tokens
        else:
            current_chunk.append(execution)
            current_tokens += execution_tokens

    # Add final chunk
    if current_chunk:
        chunks.append(current_chunk)

    # Write chunks to files
    paths = []
    for i, chunk_executions in enumerate(chunks, 1):
        chunk_data = {
            **bundle,  # Include bundle metadata
            "tool_executions": chunk_executions,
            "chunk_info": {
                "chunk_number": i,
                "total_chunks": len(chunks),
                "executions_in_chunk": len(chunk_executions)
            }
        }

        path = turn_dir.doc_path(f"bundle_part_{i:03d}.json")
        write_json_doc(path, chunk_data)
        paths.append(path)

    logger.info(
        f"[DocWriter] Wrote {len(chunks)} bundle chunks "
        f"({sum(len(c) for c in chunks)} total executions, ~{max_chunk_tokens} tokens/chunk)"
    )
    return paths


def write_capsule_md(turn_dir: 'TurnDirectory', capsule: 'DistilledCapsule') -> Path:
    """Write capsule.md from DistilledCapsule"""
    sections = {
        f"Capsule ID": capsule.capsule_id if hasattr(capsule, 'capsule_id') else "N/A"
    }

    # Claims
    if hasattr(capsule, 'claims') and capsule.claims:
        claim_lines = []
        for i, claim in enumerate(capsule.claims, 1):
            claim_lines.append(f"""### Claim {i}: {getattr(claim, 'type', 'General')}
- **Statement:** {claim.statement}
- **Confidence:** {claim.confidence:.2f}
- **Evidence:** {', '.join(claim.evidence[:3]) if claim.evidence else 'None'}
- **TTL:** {getattr(claim, 'ttl_hours', 'N/A')} hours
""")
        sections["Claims"] = "\n".join(claim_lines)

    # Quality assessment
    if hasattr(capsule, 'quality_score'):
        sections["Quality Assessment"] = f"""- Overall quality score: {capsule.quality_score:.2f}
- Intent alignment: {getattr(capsule, 'intent_alignment', 'N/A')}
- Evidence strength: {getattr(capsule, 'evidence_strength', 'N/A')}"""

    path = turn_dir.doc_path("capsule.md")
    write_markdown_doc(path, "Evidence-Based Claims (Distilled Capsule)", sections)

    claim_count = len(capsule.claims) if hasattr(capsule, 'claims') else 0
    logger.info(f"[DocWriter] Wrote capsule.md ({claim_count} claims)")
    return path


def write_turn_summary_md(
    turn_dir: 'TurnDirectory',
    summary_data: Dict[str, Any]
) -> Path:
    """Write turn_summary.md for rolling context"""
    sections = {
        "Turn Metadata": f"""- Turn ID: {summary_data.get('turn_id', 'N/A')}
- Session ID: {summary_data.get('session_id', 'N/A')}
- Query: {summary_data.get('query', 'N/A')}
- Intent: {summary_data.get('intent', 'N/A')}
- Outcome: {summary_data.get('outcome', 'N/A')}""",

        "Key Actions Taken": "\n".join([f"- {action}" for action in summary_data.get('actions', [])]),
        "Discovered Facts": "\n".join([f"- {fact}" for fact in summary_data.get('facts', [])]),
        "Session State Updates": summary_data.get('state_updates', ''),
        "Conversation Continuity": summary_data.get('continuity', '')
    }

    path = turn_dir.doc_path("turn_summary.md")
    write_markdown_doc(path, "Turn Summary (for Rolling Context)", sections)

    logger.info(f"[DocWriter] Wrote turn_summary.md")
    return path


def write_memory_update_json(turn_dir: 'TurnDirectory', memory_update: Dict[str, Any]) -> Path:
    """Write memory_update.json"""
    path = turn_dir.doc_path("memory_update.json")
    write_json_doc(path, memory_update)

    updates_count = len(memory_update.get("preference_analysis", {}).get("updates", []))
    logger.info(f"[DocWriter] Wrote memory_update.json ({updates_count} preference updates)")
    return path


def write_answer_md(turn_dir: 'TurnDirectory', answer: str, metadata: Optional[Dict] = None) -> Path:
    """Write answer.md with final response"""
    sections = {"Final Response": answer}

    if metadata:
        meta_lines = []
        for key, value in metadata.items():
            meta_lines.append(f"*{key}: {value}*")
        sections["Metadata"] = "\n".join(meta_lines)

    path = turn_dir.doc_path("answer.md")
    write_markdown_doc(path, "Final Response", sections)

    logger.info(f"[DocWriter] Wrote answer.md ({len(answer)} chars)")
    return path


# ==============================================================================
# Phase 1 Research Documents (NEW - Document-Based IO Architecture)
# ==============================================================================

def write_phase1_raw_findings_md(
    turn_dir: 'TurnDirectory',
    sources: List[Dict[str, Any]],
    query: str
) -> Path:
    """
    Write phase1_raw_findings.md with full content from each source visited.

    This is the PRIMARY input document for the Intelligence Synthesizer LLM.
    Contains the actual text/content extracted from each forum, guide, or review.

    Args:
        turn_dir: TurnDirectory instance
        sources: List of source dicts from research_orchestrator.gather_intelligence().
            Expected format (from _web_vision_visit_and_read):
                - url: Source URL
                - text_content: Summarized content
                - text_content_full: Full content (if available)
                - extracted_info: Dict with page analysis
                - summary: Brief summary
                - page_type: Type detected by LLM
                - metadata: Additional info

            Also accepts legacy format:
                - url, title, content, content_type, key_points, timestamp, status
        query: Original user query

    Returns:
        Path to written file
    """
    content = f"# Phase 1 Raw Findings\n\n"
    content += f"**Query:** {query}\n"
    content += f"**Timestamp:** {datetime.now(timezone.utc).isoformat()}\n"
    content += f"**Sources Visited:** {len(sources)}\n\n"
    content += "---\n\n"

    successful_sources = 0
    for i, source in enumerate(sources, 1):
        # Handle both new format (from gather_intelligence) and legacy format
        url = source.get("url", "Unknown URL")

        # Try to extract title from various sources
        title = source.get("title")
        if not title:
            extracted_info = source.get("extracted_info", {})
            title = extracted_info.get("title") or extracted_info.get("page_title") or "Untitled"

        # Get content - prefer full content, fall back to summarized
        source_content = (
            source.get("text_content_full") or
            source.get("text_content") or
            source.get("content") or
            "No content extracted"
        )

        # Get content type from page_type or content_type
        content_type = (
            source.get("page_type") or
            source.get("content_type") or
            "unknown"
        )

        # Get key points from extracted_info or direct field
        key_points = source.get("key_points", [])
        if not key_points:
            extracted_info = source.get("extracted_info", {})
            key_points = extracted_info.get("key_points", [])
            if not key_points:
                # Try to use summary as a key point
                summary = source.get("summary", "")
                if summary and len(summary) > 20:
                    key_points = [summary]

        # Get timestamp from metadata or direct field
        timestamp = source.get("timestamp", "Unknown")
        if timestamp == "Unknown":
            metadata = source.get("metadata", {})
            timestamp = metadata.get("timestamp", "Unknown")

        # Determine status - if we have content, it was successful
        status = source.get("status")
        if not status:
            status = "success" if source_content and source_content != "No content extracted" else "failed"

        content += f"## Source {i}: {title}\n\n"
        content += f"**URL:** {url}\n"
        content += f"**Type:** {content_type}\n"
        content += f"**Visited:** {timestamp}\n"
        content += f"**Status:** {status}\n\n"

        if status == "success":
            successful_sources += 1

            # Truncate very long content but keep it substantial
            max_content_len = 3000
            if len(source_content) > max_content_len:
                source_content = source_content[:max_content_len] + "\n\n[... content truncated ...]"

            content += f"### Extracted Content\n\n{source_content}\n\n"

            if key_points:
                content += "### Key Points\n\n"
                for point in key_points:
                    content += f"- {point}\n"
                content += "\n"
        else:
            content += f"### Error\n\nFailed to extract content: {status}\n\n"

        content += "---\n\n"

    path = turn_dir.doc_path("phase1_raw_findings.md")
    path.write_text(content)

    logger.info(f"[DocWriter] Wrote phase1_raw_findings.md ({successful_sources}/{len(sources)} sources, {len(content)} chars)")
    return path


def write_phase1_sources_md(
    turn_dir: 'TurnDirectory',
    sources: List[Dict[str, Any]],
    query: str
) -> Path:
    """
    Write phase1_sources.md with a summary table of sources consulted.

    This provides a quick reference for what sources were visited without
    the full content (which is in phase1_raw_findings.md).

    Args:
        turn_dir: TurnDirectory instance
        sources: List of source dicts from research_orchestrator.gather_intelligence().
            Handles both new format (from _web_vision_visit_and_read) and legacy format.
        query: Original user query

    Returns:
        Path to written file
    """
    content = f"# Phase 1 Sources Consulted\n\n"
    content += f"**Query:** {query}\n"
    content += f"**Timestamp:** {datetime.now(timezone.utc).isoformat()}\n\n"

    # Summary table
    content += "## Source Summary\n\n"
    content += "| # | Source | Type | Status |\n"
    content += "|---|--------|------|--------|\n"

    successful = 0
    failed = 0
    for i, source in enumerate(sources, 1):
        # Handle both new format and legacy format for title
        title = source.get("title")
        if not title:
            extracted_info = source.get("extracted_info", {})
            title = extracted_info.get("title") or extracted_info.get("page_title") or "Untitled"
        title = title[:50]

        # Handle content_type - check page_type first (new format)
        content_type = (
            source.get("page_type") or
            source.get("content_type") or
            "unknown"
        )

        # Determine status - if we have content, it was successful
        status = source.get("status")
        if not status:
            has_content = (
                source.get("text_content_full") or
                source.get("text_content") or
                source.get("content")
            )
            status = "success" if has_content else "failed"

        if status == "success":
            status_display = "✓ Success"
            successful += 1
        else:
            status_display = f"✗ {str(status)[:20]}"
            failed += 1

        content += f"| {i} | {title} | {content_type} | {status_display} |\n"

    content += f"\n**Total:** {len(sources)} sources ({successful} successful, {failed} failed)\n\n"

    # List URLs for reference
    content += "## URLs\n\n"
    for i, source in enumerate(sources, 1):
        url = source.get("url", "Unknown")
        # Determine status for icon
        status = source.get("status")
        if not status:
            has_content = (
                source.get("text_content_full") or
                source.get("text_content") or
                source.get("content")
            )
            status = "success" if has_content else "failed"
        status_icon = "✓" if status == "success" else "✗"
        content += f"{i}. {status_icon} {url}\n"

    path = turn_dir.doc_path("phase1_sources.md")
    path.write_text(content)

    logger.info(f"[DocWriter] Wrote phase1_sources.md ({successful}/{len(sources)} sources)")
    return path


def write_phase2_search_plan_md(
    turn_dir: 'TurnDirectory',
    search_strategies: List[Dict[str, Any]],
    verification_criteria: List[str],
    intelligence_summary: str,
    query: str
) -> Path:
    """
    Write phase2_search_plan.md with the planned search strategy.

    This is created by the Research Role LLM after reading phase1_intelligence.md.
    The Phase 2 Executor reads this to know what searches to perform.

    Args:
        turn_dir: TurnDirectory instance
        search_strategies: List of search strategy dicts:
            - strategy_type: "google_generic", "vendor_direct", "model_specific"
            - query: Search query to execute
            - target_vendor: Optional vendor domain for vendor_direct
            - rationale: Why this search was chosen
            - priority: Execution order
        verification_criteria: List of criteria for product verification
        intelligence_summary: Brief summary of Phase 1 intelligence used
        query: Original user query

    Returns:
        Path to written file
    """
    content = f"# Phase 2 Search Plan\n\n"
    content += f"**Query:** {query}\n"
    content += f"**Created:** {datetime.now(timezone.utc).isoformat()}\n\n"

    content += "## Intelligence Summary\n\n"
    content += f"{intelligence_summary}\n\n"

    content += "## Search Strategy\n\n"

    for i, strategy in enumerate(search_strategies, 1):
        strategy_type = strategy.get("strategy_type", "unknown")
        search_query = strategy.get("query", "")
        target_vendor = strategy.get("target_vendor", "")
        rationale = strategy.get("rationale", "")

        # Format based on strategy type
        if strategy_type == "google_generic":
            content += f"### {i}. Generic Google Search\n\n"
            content += f"**Query:** `{search_query}`\n"
        elif strategy_type == "vendor_direct":
            content += f"### {i}. Vendor Direct: {target_vendor}\n\n"
            content += f"**Target:** {target_vendor}\n"
            content += f"**Site Search:** `{search_query}`\n"
        elif strategy_type == "google_site":
            content += f"### {i}. Google Site Search: {target_vendor}\n\n"
            content += f"**Query:** `{search_query} site:{target_vendor}`\n"
        elif strategy_type == "model_specific":
            content += f"### {i}. Specific Model Search\n\n"
            content += f"**Query:** `{search_query}`\n"
        else:
            content += f"### {i}. Search\n\n"
            content += f"**Query:** `{search_query}`\n"

        content += f"**Rationale:** {rationale}\n\n"

    content += "## Verification Criteria\n\n"
    content += "For each product found, verify via click-to-PDP:\n\n"
    for criterion in verification_criteria:
        content += f"- [ ] {criterion}\n"

    content += "\n## Execution Notes\n\n"
    content += "- Execute searches in order of priority\n"
    content += "- Use click-to-verify for ALL products\n"
    content += "- Stop when enough verified products found (default: 5)\n"

    path = turn_dir.doc_path("phase2_search_plan.md")
    path.write_text(content)

    logger.info(f"[DocWriter] Wrote phase2_search_plan.md ({len(search_strategies)} searches planned)")
    return path


def write_phase2_findings_md(
    turn_dir: 'TurnDirectory',
    verified_products: List[Dict[str, Any]],
    search_stats: Dict[str, Any],
    warnings: List[str],
    query: str
) -> Path:
    """
    Write phase2_findings.md with verified products from Phase 2 search.

    This is the final output of Phase 2, containing click-verified products
    with accurate prices, URLs, and specs.

    Args:
        turn_dir: TurnDirectory instance
        verified_products: List of verified product dicts:
            - title: Product name
            - price: Verified price
            - url: Verified PDP URL
            - vendor: Vendor name
            - in_stock: Boolean
            - specs: Dict of specifications
            - viability_score: 0-1 score
        search_stats: Stats about the search process
        warnings: Community warnings/tips from Phase 1 to surface to user
        query: Original user query

    Returns:
        Path to written file
    """
    content = f"# Phase 2 Findings\n\n"
    content += f"**Query:** {query}\n"
    content += f"**Timestamp:** {datetime.now(timezone.utc).isoformat()}\n"
    content += f"**Products Found:** {len(verified_products)}\n\n"

    content += "## Verified Products\n\n"

    if not verified_products:
        content += "*No products found matching criteria.*\n\n"
    else:
        for i, product in enumerate(verified_products, 1):
            title = product.get("title", "Unknown")
            price = product.get("price", "N/A")
            url = product.get("url", "")
            vendor = product.get("vendor", "Unknown")
            in_stock = product.get("in_stock", False)
            specs = product.get("specs", {})
            score = product.get("viability_score", 0)

            stock_status = "✓ In Stock" if in_stock else "✗ Out of Stock"

            content += f"### {i}. {title}\n\n"
            content += f"**Price:** {price}\n"
            content += f"**Vendor:** {vendor}\n"
            content += f"**Stock:** {stock_status}\n"
            content += f"**Viability Score:** {score:.2f}\n"
            content += f"**URL:** {url}\n\n"

            if specs:
                content += "**Specs:**\n"
                for key, value in specs.items():
                    content += f"- {key}: {value}\n"
                content += "\n"

    # Search stats
    content += "## Search Statistics\n\n"
    for key, value in search_stats.items():
        content += f"- **{key}:** {value}\n"

    # Warnings from community
    if warnings:
        content += "\n## Community Tips & Warnings\n\n"
        content += "*From Phase 1 research - consider before purchase:*\n\n"
        for warning in warnings:
            content += f"- ⚠️ {warning}\n"

    path = turn_dir.doc_path("phase2_findings.md")
    path.write_text(content)

    logger.info(f"[DocWriter] Wrote phase2_findings.md ({len(verified_products)} products)")
    return path


# ==============================================================================
# Unified Knowledge Retrieval Documents (Phase 1 Context Gathering)
# ==============================================================================

def write_cached_knowledge_md(
    turn_dir: 'TurnDirectory',
    knowledge: 'RetrievedKnowledge',
    query: str,
    user_constraints: Optional[Dict] = None
) -> Path:
    """
    Write cached_knowledge.md with unified cached data (products + claims).

    This document is created during Phase 1 Context Gathering and informs
    the Planner about ALL existing cached knowledge. The Planner can then
    decide whether to skip research or do targeted research for gaps.

    Args:
        turn_dir: TurnDirectory instance
        knowledge: RetrievedKnowledge from KnowledgeRetriever
        query: Current user query
        user_constraints: User preferences (budget, etc.)

    Returns:
        Path to written file
    """
    from apps.services.tool_server.intelligence_retriever import RetrievedKnowledge

    user_constraints = user_constraints or {}

    content = f"# Cached Knowledge\n\n"
    content += f"**Query:** {query}\n"
    content += f"**Timestamp:** {datetime.now(timezone.utc).isoformat()}\n"
    content += f"**Sources Searched:** {knowledge.sources_searched}\n"
    content += f"**Data Freshness:** {knowledge.freshest_data_hours:.1f}h - {knowledge.oldest_data_hours:.1f}h old\n"
    content += f"**Coverage Score:** {knowledge.query_coverage:.2f}\n\n"

    # Summary counts
    product_count = len(knowledge.products)
    claim_count = len(knowledge.claims)
    content += f"**Found:** {product_count} products, {claim_count} verified claims\n\n"

    # Assessment summary
    content += "## Data Sufficiency Assessment\n\n"

    has_fresh = knowledge.has_fresh_prices(max_age_hours=6.0)
    has_sufficient = knowledge.has_sufficient_products(min_count=5)
    has_claims = knowledge.has_relevant_claims(min_count=2)

    if has_sufficient and has_fresh:
        content += "**Status:** ✓ SUFFICIENT - Can likely answer from cached data\n"
        content += "- Enough products found\n"
        content += "- Price data is fresh (< 6h old)\n"
        if has_claims:
            content += "- Verified claims available\n"
        recommendation = "use_cached"
    elif (has_sufficient or has_claims) and not has_fresh:
        content += "**Status:** ⚠️ PARTIAL - Data found but may be stale\n"
        if has_sufficient:
            content += "- Enough products found\n"
        if has_claims:
            content += f"- {claim_count} verified claims available\n"
        content += "- Price data may need refresh (> 6h old)\n"
        recommendation = "partial_research"
    elif product_count > 0 or claim_count > 0:
        content += "**Status:** ⚠️ PARTIAL - Some data found but not comprehensive\n"
        if product_count > 0:
            content += f"- Only {product_count} products found (need 5+)\n"
        if claim_count > 0:
            content += f"- {claim_count} verified claims available\n"
        recommendation = "partial_research"
    else:
        content += "**Status:** ✗ INSUFFICIENT - Need full research\n"
        content += "- No cached products or claims match this query\n"
        recommendation = "full_research"

    content += f"\n**Recommendation:** `{recommendation}`\n\n"

    # Verified Claims section (show first - higher quality)
    if knowledge.claims:
        content += "## Verified Claims\n\n"
        content += "*Previously verified facts with evidence:*\n\n"

        for i, claim in enumerate(knowledge.claims[:10], 1):
            confidence_icon = "🟢" if claim.confidence == "high" else "🟡" if claim.confidence == "medium" else "🔴"
            content += f"### {i}. {confidence_icon} {claim.statement}\n"
            content += f"- **Confidence:** {claim.confidence}\n"
            content += f"- **Age:** {claim.age_hours:.1f}h (expires in {claim.expires_in_hours:.1f}h)\n"
            if claim.evidence:
                content += f"- **Evidence:** {', '.join(claim.evidence[:2])}\n"
            content += "\n"

        if len(knowledge.claims) > 10:
            content += f"*... and {len(knowledge.claims) - 10} more claims*\n\n"
    else:
        content += "## Verified Claims\n\n"
        content += "*No verified claims found for this query.*\n\n"

    # Products section
    content += "## Cached Products\n\n"

    if not knowledge.products:
        content += "*No products found in cache for this query.*\n\n"
    else:
        # Filter by budget if specified
        budget = user_constraints.get("budget") or user_constraints.get("max_price")
        if budget:
            matching = knowledge.get_matching_products(float(budget))
            content += f"*Showing products within budget ${budget} ({len(matching)}/{product_count} match)*\n\n"
            products_to_show = matching
        else:
            products_to_show = knowledge.products

        # Show top products (limit to 10)
        for i, prod in enumerate(products_to_show[:10], 1):
            price_str = f"${prod.price:.2f}" if prod.price else prod.price_str or "Price unknown"
            age_str = f"{prod.age_hours:.1f}h ago" if prod.age_hours else "unknown age"

            content += f"### {i}. {prod.name}\n"
            content += f"- **Price:** {price_str}\n"
            content += f"- **Retailer:** {prod.retailer}\n"
            content += f"- **Data Age:** {age_str}\n"
            if prod.url:
                content += f"- **URL:** {prod.url}\n"
            if prod.specs:
                specs_str = ", ".join([f"{k}: {v}" for k, v in list(prod.specs.items())[:3]])
                content += f"- **Specs:** {specs_str}\n"
            content += "\n"

        if len(products_to_show) > 10:
            content += f"*... and {len(products_to_show) - 10} more products*\n\n"

    # Retailers section
    if knowledge.retailers:
        content += "## Known Retailers\n\n"
        content += ", ".join(knowledge.retailers) + "\n\n"

    # Price range section
    if knowledge.price_range:
        content += "## Price Range (from cache)\n\n"
        if "min" in knowledge.price_range:
            content += f"- Min: ${knowledge.price_range['min']:.2f}\n"
        if "max" in knowledge.price_range:
            content += f"- Max: ${knowledge.price_range['max']:.2f}\n"
        content += "\n"

    # Guidance for planner
    content += "## Guidance for Planner\n\n"

    if recommendation == "use_cached":
        content += """Based on cached knowledge, you may be able to answer this query WITHOUT calling `internet.research`.

Consider:
1. Review the verified claims and products above
2. If they match the user's needs, synthesize an answer directly
3. Only call research if the cached data doesn't fully address the query
"""
    elif recommendation == "partial_research":
        content += """Cached data is available but incomplete. Consider TARGETED research:

1. If prices need refresh: Focus on vendor sites directly
2. If more options needed: Do a focused search for specific gaps
3. Use existing claims as foundation - they're already verified
4. Avoid full broad research - use cached knowledge as a starting point
"""
    else:
        content += """No relevant cached data found. Full research recommended.

Proceed with `internet.research` tool call.
"""

    path = turn_dir.doc_path("cached_knowledge.md")
    path.write_text(content)

    logger.info(
        f"[DocWriter] Wrote cached_knowledge.md "
        f"({product_count} products, {claim_count} claims, coverage={knowledge.query_coverage:.2f}, rec={recommendation})"
    )
    return path


# Backward compatibility alias
def write_cached_intelligence_md(turn_dir, retrieved_intel, query, user_constraints=None):
    """Backward compatibility alias for write_cached_knowledge_md."""
    return write_cached_knowledge_md(turn_dir, retrieved_intel, query, user_constraints)
