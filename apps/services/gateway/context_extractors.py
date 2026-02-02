"""
Context Extraction Utilities

Helper functions to extract structured information from turn data
for updating the living session context.
"""

import re
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


def extract_preferences(user_msg: str, guide_payload: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """
    Extract user preference statements from query or Guide response.

    Enhanced patterns covering location, time, quality, budget, attributes, brands, etc.

    Examples:
    - "my favorite hamster is Syrian" → {"favorite_hamster": "Syrian"}
    - "I prefer organic food" → {"food_preference": "organic"}
    - "my budget is under $50" → {"budget": "under $50"}
    - "I'm in California" → {"location": "California"}
    - "I need it by Friday" → {"timeframe": "by Friday"}
    - "I want high quality" → {"quality_preference": "high quality"}

    Args:
        user_msg: User's query
        guide_payload: Optional Guide response to check for extracted preferences

    Returns:
        Dictionary of preferences found
    """
    preferences = {}
    msg_lower = user_msg.lower()

    # Pattern: "my favorite X is Y"
    favorite_match = re.search(r'my favorite (\w+) is ([\w\s]+?)(?:\s+(?:and|or|but|for|with)|[.,!?]|$)', user_msg, re.IGNORECASE)
    if favorite_match:
        category = favorite_match.group(1)
        value = favorite_match.group(2).strip()
        preferences[f"favorite_{category}"] = value
        logger.info(f"[ContextExtract] Found preference: favorite_{category} = {value}")

    # Pattern: "I prefer X" or "I'd prefer X"
    prefer_match = re.search(r"I(?:'d)? prefer ([\w\s]+?)(?:\s+(?:over|to|than|and|or|but|for)|[.,!?]|$)", user_msg, re.IGNORECASE)
    if prefer_match:
        value = prefer_match.group(1).strip()
        preferences["general_preference"] = value
        logger.info(f"[ContextExtract] Found preference: general_preference = {value}")

    # Pattern: "my budget is X" or "budget of X" or "under $X"
    budget_patterns = [
        r'my budget is ([\w\s$€£¥,.-]+?)(?:\s+(?:and|or|but|for)|[.,!?]|$)',
        r'budget of ([\w\s$€£¥,.-]+?)(?:\s+(?:and|or|but|for)|[.,!?]|$)',
        r'under ([\$€£¥]\d+(?:,\d{3})*(?:\.\d{2})?)',
        r'less than ([\$€£¥]\d+(?:,\d{3})*(?:\.\d{2})?)',
        r'max(?:imum)? ([\$€£¥]\d+(?:,\d{3})*(?:\.\d{2})?)',
    ]
    for pattern in budget_patterns:
        budget_match = re.search(pattern, user_msg, re.IGNORECASE)
        if budget_match:
            value = budget_match.group(1).strip()
            preferences["budget"] = value
            logger.info(f"[ContextExtract] Found preference: budget = {value}")
            break

    # Pattern: Location - "I'm in X", "I'm located in X", "I live in X", "near X"
    location_patterns = [
        r"I(?:'m| am) (?:in|located in|living in|from) ([\w\s]+?)(?:\s+(?:and|or|but|for)|[.,!?]|$)",
        r"I live in ([\w\s]+?)(?:\s+(?:and|or|but|for)|[.,!?]|$)",
        r"near ([\w\s]+?)(?:\s+(?:and|or|but|for)|[.,!?]|$)",
        r"(?:zip code|zipcode|postal code) (\d{5}(?:-\d{4})?)",
    ]
    for pattern in location_patterns:
        location_match = re.search(pattern, user_msg, re.IGNORECASE)
        if location_match:
            value = location_match.group(1).strip()
            preferences["location"] = value
            logger.info(f"[ContextExtract] Found preference: location = {value}")
            break

    # Pattern: Timeframe - "by X", "within X", "in X days/weeks"
    time_patterns = [
        r"(?:by|before) ([\w\s]+?)(?:\s+(?:and|or|but)|[.,!?]|$)",
        r"within ([\w\s]+?)(?:\s+(?:and|or|but)|[.,!?]|$)",
        r"in (\d+\s+(?:day|week|month|hour)s?)",
        r"(?:need|want|require) it (?:by|before|within) ([\w\s]+?)(?:\s+(?:and|or)|[.,!?]|$)",
    ]
    for pattern in time_patterns:
        time_match = re.search(pattern, user_msg, re.IGNORECASE)
        if time_match:
            value = time_match.group(1).strip()
            # Skip if value is too generic
            if value.lower() not in ['then', 'now', 'the way', 'the end']:
                preferences["timeframe"] = value
                logger.info(f"[ContextExtract] Found preference: timeframe = {value}")
                break

    # Pattern: Quality preferences
    if any(phrase in msg_lower for phrase in ['high quality', 'top quality', 'best quality', 'premium']):
        preferences["quality_preference"] = "high quality"
        logger.info(f"[ContextExtract] Found preference: quality_preference = high quality")
    elif any(phrase in msg_lower for phrase in ['budget', 'cheap', 'affordable', 'inexpensive']):
        if "quality_preference" not in preferences:  # Don't override if already set
            preferences["quality_preference"] = "budget friendly"
            logger.info(f"[ContextExtract] Found preference: quality_preference = budget friendly")

    # Pattern: Size/Quantity
    size_patterns = [
        r"(?:size|sized) ([\w\s]+?)(?:\s+(?:and|or|but|for)|[.,!?]|$)",
        r"(small|medium|large|extra large|xl|xxl|tiny|huge|massive) (?:sized?|one)",
    ]
    for pattern in size_patterns:
        size_match = re.search(pattern, user_msg, re.IGNORECASE)
        if size_match:
            value = size_match.group(1).strip()
            preferences["size"] = value
            logger.info(f"[ContextExtract] Found preference: size = {value}")
            break

    # Pattern: Color
    colors = ['red', 'blue', 'green', 'yellow', 'orange', 'purple', 'pink', 'black', 'white', 'gray', 'brown', 'beige', 'golden', 'silver']
    color_pattern = r'\b(' + '|'.join(colors) + r')\s+(?:color|colored|one|hamster|item)'
    color_match = re.search(color_pattern, user_msg, re.IGNORECASE)
    if color_match:
        value = color_match.group(1)
        preferences["color"] = value
        logger.info(f"[ContextExtract] Found preference: color = {value}")

    # Pattern: Brand preference
    brand_match = re.search(r"(?:I like|I prefer|I want|I use) ([\w\s]+?) brand", user_msg, re.IGNORECASE)
    if brand_match:
        value = brand_match.group(1).strip()
        preferences["brand"] = value
        logger.info(f"[ContextExtract] Found preference: brand = {value}")

    # Pattern: Dietary/Organic/Natural preferences
    if any(word in msg_lower for word in ['organic', 'natural', 'non-gmo', 'sustainable', 'eco-friendly']):
        for word in ['organic', 'natural', 'non-gmo', 'sustainable', 'eco-friendly']:
            if word in msg_lower:
                preferences["dietary_preference"] = word
                logger.info(f"[ContextExtract] Found preference: dietary_preference = {word}")
                break

    return preferences


def extract_topic(user_msg: str, guide_payload: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Extract the current conversation topic from query or Guide analysis.

    Enhanced classification with better keyword coverage and entity extraction:
    - Shopping: "for sale", "buy", "purchase", "cost", "available", "order"
    - Care: "care", "how to", "feed", "diet", "health", "maintenance"
    - Information: "what is", "tell me about", "learn", "understand"
    - Finding: "find", "where", "locate", "breeder", "nearby"
    - Breeding: "breed", "breeding", "genetics", "litter"
    - Comparison: "compare", "difference", "vs", "better", "best"

    Args:
        user_msg: User's query
        guide_payload: Optional Guide response with goal/analysis

    Returns:
        Topic string or None
    """
    msg_lower = user_msg.lower()

    # If Guide has a goal, use that as topic
    if guide_payload and "goal" in guide_payload:
        goal = guide_payload["goal"]
        return goal[:50]  # Truncate to reasonable length

    # Extract subject (noun phrases after common patterns)
    subject = None

    # Try to find subject from patterns like "about X", "for X", "X that/which"
    subject_patterns = [
        r'(?:about|regarding|concerning) ([\w\s]+?)(?:\s+(?:and|or|that|which|who)|[.,!?]|$)',
        r'(?:for|with) ([\w\s]+?)(?:\s+(?:and|or|that|which|who)|[.,!?]|$)',
        r'([\w\s]+?)(?:\s+that|which)',
    ]
    for pattern in subject_patterns:
        match = re.search(pattern, user_msg, re.IGNORECASE)
        if match:
            subject = match.group(1).strip()
            # Clean up common stop words at the end
            subject = re.sub(r'\s+(are|is|was|were|be|been|being|have|has|had|do|does|did|can|could|will|would|should|may|might)$', '', subject, flags=re.IGNORECASE)
            if len(subject) > 3:  # Must be substantial
                break

    # Shopping-related (transactional)
    shopping_keywords = ["for sale", "buy", "purchase", "shop", "price", "cost", "order", "available", "sell", "store", "vendor"]
    if any(kw in msg_lower for kw in shopping_keywords):
        if subject:
            return f"shopping for {subject}"
        # Try to extract item after shopping keywords
        match = re.search(r'(?:for sale|buy|purchase|shop|order|find)[^\w]+([\w\s]+?)(?:\s+(?:online|nearby|for|with)|[.,!?]|$)', msg_lower)
        if match:
            item = match.group(1).strip()
            if len(item) > 2:
                return f"shopping for {item}"
        return "shopping"

    # Care-related (informational/instructional)
    care_keywords = ["care", "how to", "need", "diet", "feed", "food", "cage", "habitat", "health", "disease", "illness", "clean", "maintain", "raise"]
    if any(kw in msg_lower for kw in care_keywords):
        if subject:
            return f"care for {subject}"
        match = re.search(r'(?:care for|care about|feed|diet for|diet of|health of|clean)[^\w]+([\w\s]+?)(?:\s+(?:need|require|is|are)|[.,!?]|$)', msg_lower)
        if match:
            item = match.group(1).strip()
            if len(item) > 2:
                return f"care for {item}"
        return "pet care"

    # Information-seeking (general learning)
    info_keywords = ["what is", "what are", "tell me about", "explain", "learn about", "understand", "information about", "facts about"]
    if any(kw in msg_lower for kw in info_keywords):
        if subject:
            return f"learning about {subject}"
        match = re.search(r'(?:what is|what are|tell me about|explain|learn about|understand)[^\w]+([\w\s]+?)(?:\s+(?:and|or|that)|[.,!?]|$)', msg_lower)
        if match:
            item = match.group(1).strip()
            if len(item) > 2:
                return f"learning about {item}"
        return "information seeking"

    # Finding/locating (navigational)
    finding_keywords = ["find", "where", "locate", "search", "look for", "breeder", "seller", "nearby", "near me", "in my area"]
    if any(kw in msg_lower for kw in finding_keywords):
        if subject:
            return f"finding {subject}"
        match = re.search(r'(?:find|where|locate|search for|look for)[^\w]+([\w\s]+?)(?:\s+(?:online|nearby|for|that)|[.,!?]|$)', msg_lower)
        if match:
            item = match.group(1).strip()
            if len(item) > 2:
                return f"finding {item}"
        return "searching"

    # Breeding-related
    breeding_keywords = ["breed", "breeding", "genetics", "litter", "pups", "babies", "mate", "reproduce"]
    if any(kw in msg_lower for kw in breeding_keywords):
        if subject:
            return f"breeding {subject}"
        match = re.search(r'(?:breed|breeding)[^\w]+([\w\s]+?)(?:\s+(?:and|or|with)|[.,!?]|$)', msg_lower)
        if match:
            item = match.group(1).strip()
            if len(item) > 2:
                return f"breeding {item}"
        return "breeding"

    # Comparison-related
    comparison_keywords = ["compare", "comparison", "difference between", "vs", "versus", "better", "best", "which is"]
    if any(kw in msg_lower for kw in comparison_keywords):
        if subject:
            return f"comparing {subject}"
        match = re.search(r'(?:compare|comparison of|difference between)[^\w]+([\w\s]+?)(?:\s+(?:and|vs|versus|with)|[.,!?]|$)', msg_lower)
        if match:
            item = match.group(1).strip()
            if len(item) > 2:
                return f"comparing {item}"
        return "comparison"

    # General interest (fallback)
    interest_keywords = ["interested in", "curious about", "thinking about", "considering"]
    if any(kw in msg_lower for kw in interest_keywords):
        if subject:
            return f"interested in {subject}"
        match = re.search(r'(?:interested in|curious about|thinking about|considering)[^\w]+([\w\s]+?)(?:\s+(?:and|or|for)|[.,!?]|$)', msg_lower)
        if match:
            item = match.group(1).strip()
            if len(item) > 2:
                return f"interested in {item}"

    # If we found a subject but no clear topic category, use generic format
    if subject and len(subject) > 3:
        return f"discussing {subject}"

    return None


def extract_action_from_tools(coordinator_plan: Optional[List[Dict[str, Any]]], tool_results: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Extract action summary from tools executed.

    Args:
        coordinator_plan: List of tools planned
        tool_results: Optional results from tool execution

    Returns:
        Action dict with summary, or None
    """
    if not coordinator_plan:
        return None

    tools_used = [tool.get("tool", "unknown") for tool in coordinator_plan]
    tool_names = ", ".join(tools_used[:3])  # First 3 tools

    action = {
        "action": "executed_tools",
        "tools": tools_used,
        "summary": f"Used {len(tools_used)} tool(s): {tool_names}",
        "timestamp": time.time()
    }

    # Add results summary if available
    if tool_results:
        if "results_count" in tool_results:
            action["results"] = tool_results["results_count"]
            action["summary"] += f" ({tool_results['results_count']} results)"

    return action


def extract_facts_from_capsule(capsule) -> Dict[str, List[str]]:
    """
    Extract facts from capsule claim summaries with content-based domain classification.

    Organizes claims by domain/topic using keyword analysis for better categorization.

    Args:
        capsule: CapsuleEnvelope object or dict with claim_summaries

    Returns:
        Dictionary mapping categories to lists of facts
    """
    if not capsule:
        return {}

    # Handle both CapsuleEnvelope object and dict
    if hasattr(capsule, 'claim_summaries'):
        claim_summaries = capsule.claim_summaries
    elif isinstance(capsule, dict) and "claim_summaries" in capsule:
        claim_summaries = capsule.get("claim_summaries", {})
    else:
        return {}

    if not claim_summaries:
        return {}

    facts: Dict[str, List[str]] = {}

    # Domain classification keywords
    domain_keywords = {
        "pricing": ["price", "cost", "$", "€", "£", "¥", "dollar", "cheap", "expensive", "affordable", "budget"],
        "care": ["care", "feed", "diet", "food", "cage", "habitat", "clean", "maintain", "health", "disease", "exercise"],
        "availability": ["available", "in stock", "out of stock", "sold out", "ships", "delivery", "location", "near"],
        "breeding": ["breed", "breeding", "litter", "pups", "babies", "genetics", "mate", "pregnant"],
        "characteristics": ["temperament", "behavior", "personality", "size", "color", "appearance", "trait", "characteristic"],
        "supplies": ["supplies", "equipment", "bedding", "toy", "wheel", "bottle", "bowl", "accessory"],
        "lifespan": ["lifespan", "live", "years", "age", "longevity", "expectancy"],
        "behavior": ["active", "nocturnal", "social", "solitary", "friendly", "aggressive", "playful"],
    }

    # Take top 10 claim summaries
    for claim_id, summary in list(claim_summaries.items())[:10]:
        # Truncate summary to 150 chars
        text = summary[:150] if isinstance(summary, str) else str(summary)[:150]

        if not text:
            continue

        # Classify domain based on content keywords
        domain = "general"  # Default
        text_lower = text.lower()

        # Check each domain's keywords
        max_matches = 0
        for domain_name, keywords in domain_keywords.items():
            match_count = sum(1 for kw in keywords if kw in text_lower)
            if match_count > max_matches:
                max_matches = match_count
                domain = domain_name

        # Fallback: try claim_id prefix if no keyword matches
        if domain == "general" and "_" in claim_id:
            prefix = claim_id.split("_")[0]
            # Only use prefix if it's a recogn izable domain
            if prefix in domain_keywords:
                domain = prefix

        if domain not in facts:
            facts[domain] = []
        facts[domain].append(text)

    return facts


def extract_action_from_ticket(ticket: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Extract action summary from task ticket.

    Args:
        ticket: Task ticket created by Guide

    Returns:
        Action dict or None
    """
    if not ticket or "goal" not in ticket:
        return None

    goal = ticket.get("goal", "")

    return {
        "action": "delegated_task",
        "summary": f"Delegated: {goal[:100]}",
        "ticket_id": ticket.get("ticket_id", "unknown"),
        "timestamp": time.time()
    }


import time


def extract_repository_from_tools(tool_records: List[Dict[str, Any]]) -> Optional[str]:
    """
    Extract repository path from tool execution records.

    Looks for 'repo' parameter in file.*, git.*, bash.* tool calls.

    Args:
        tool_records: List of executed tools with args

    Returns:
        Repository path or None
    """
    if not tool_records:
        return None

    for tool in tool_records:
        args = tool.get("args", {})
        # Check for repo parameter (common in file/git/bash tools)
        if "repo" in args and args["repo"]:
            return args["repo"]
        # Also check cwd parameter (alternative name)
        if "cwd" in args and args["cwd"]:
            return args["cwd"]

    return None


def extract_git_state(tool_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract git branch and modified files from git.status results.

    Parses git.status output to find:
    - Current branch
    - Modified files list
    - Staged/unstaged counts

    Args:
        tool_records: List of executed tools with results

    Returns:
        Dict with branch, modified, staged, unstaged keys
    """
    git_state = {}

    if not tool_records:
        return git_state

    for tool in tool_records:
        if tool.get("tool") != "git.status":
            continue

        result = tool.get("result", {})

        # Extract branch
        if "branch" in result:
            git_state["branch"] = result["branch"]

        # Extract modified files
        modified_files = []
        if "modified" in result and isinstance(result["modified"], list):
            modified_files.extend(result["modified"])
        if "staged" in result and isinstance(result["staged"], list):
            modified_files.extend(result["staged"])
        if "unstaged" in result and isinstance(result["unstaged"], list):
            modified_files.extend(result["unstaged"])

        if modified_files:
            git_state["modified"] = list(set(modified_files))[:10]  # Dedupe and limit to 10

        # Extract counts
        if "staged_count" in result:
            git_state["staged"] = result["staged_count"]
        if "unstaged_count" in result:
            git_state["unstaged"] = result["unstaged_count"]

    return git_state


def extract_test_results(tool_records: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Parse test results from bash.execute pytest/unittest or code.verify_suite runs.

    Extracts:
    - Pass/fail counts
    - Test status summary
    - Last action performed

    Args:
        tool_records: List of executed tools with results

    Returns:
        Dict with test_status, last_action keys, or None
    """
    if not tool_records:
        return None

    for tool in tool_records:
        tool_name = tool.get("tool", "")

        # code.verify_suite (structured output)
        if tool_name == "code.verify_suite":
            result = tool.get("result", {})
            if "summary" in result:
                return {
                    "test_status": result["summary"],
                    "last_action": f"Ran verification suite: {result.get('overall_status', 'unknown')}"
                }

        # bash.execute with pytest/unittest
        elif tool_name == "bash.execute":
            result = tool.get("result", {})
            output = result.get("stdout", "") + result.get("stderr", "")

            # Parse pytest output
            pytest_match = re.search(r'(\d+)\s+passed(?:,\s+(\d+)\s+failed)?', output)
            if pytest_match:
                passed = pytest_match.group(1)
                failed = pytest_match.group(2) or "0"
                total = int(passed) + int(failed)
                return {
                    "test_status": f"{passed}/{total} tests passed" if failed != "0" else f"{passed} tests passed",
                    "last_action": f"Ran pytest: {passed} passed, {failed} failed"
                }

            # Parse unittest output
            unittest_match = re.search(r'Ran\s+(\d+)\s+test', output)
            if unittest_match:
                total = unittest_match.group(1)
                failed_match = re.search(r'FAILED.*?failures=(\d+)', output)
                failed = failed_match.group(1) if failed_match else "0"
                passed = str(int(total) - int(failed))
                return {
                    "test_status": f"{passed}/{total} tests passed" if failed != "0" else f"{total} tests passed",
                    "last_action": f"Ran unittest: {passed} passed, {failed} failed"
                }

    return None
