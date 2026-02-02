"""
LLM-Driven Research Loop

The LLM (Research Planner) decides every action:
- search(query) - Execute a web search
- visit(url) - Visit a page and extract text
- done() - Finish with current findings

The system provides tools and executes them. The LLM decides strategy.
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from libs.gateway.turn_manager import TurnDirectory

from .state import (
    ResearchState,
    SearchResult,
    PageFindings,
    create_initial_state,
)
from .browser import ResearchBrowser, should_skip_url

logger = logging.getLogger(__name__)


@dataclass
class Phase1Intelligence:
    """Output of Phase 1 research."""
    success: bool
    goal: str
    context: str
    task: str

    # What we learned
    intelligence: dict
    findings: list

    # For Phase 2
    vendor_hints: list[str]
    search_terms: list[str]
    price_range: Optional[dict]

    # Metadata
    sources: list[str]
    research_state_md: str
    searches_used: int
    pages_visited: int
    elapsed_seconds: float

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "goal": self.goal,
            "context": self.context,
            "task": self.task,
            "intelligence": self.intelligence,
            "findings": self.findings,
            "vendor_hints": self.vendor_hints,
            "search_terms": self.search_terms,
            "price_range": self.price_range,
            "sources": self.sources,
            "searches_used": self.searches_used,
            "pages_visited": self.pages_visited,
            "elapsed_seconds": self.elapsed_seconds,
        }


class ResearchLoop:
    """
    LLM-driven research loop.

    The Research Planner LLM reads state and decides what to do next.
    """

    def __init__(
        self,
        session_id: str,
        llm_url: Optional[str] = None,
        llm_model: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        turn_dir: Optional["TurnDirectory"] = None,
        event_emitter: Optional[Any] = None,
        human_assist_allowed: bool = True,
    ):
        self.session_id = session_id
        self.llm_url = llm_url or os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
        self.llm_model = llm_model or os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
        self.llm_api_key = llm_api_key or os.getenv("SOLVER_API_KEY", "qwen-local")
        self.turn_dir = turn_dir  # For Document IO compliance (recipe-based prompts)
        self.event_emitter = event_emitter  # Progress event emission
        self.human_assist_allowed = human_assist_allowed  # Allow CAPTCHA intervention

        self.browser = ResearchBrowser(
            session_id=session_id,
            human_assist_allowed=human_assist_allowed,
        )

    async def _emit_event(self, event_type: str, data: dict):
        """Emit a progress event if event_emitter is configured."""
        if self.event_emitter:
            try:
                await self.event_emitter.emit(event_type, data)
            except Exception as e:
                logger.warning(f"[ResearchLoop] Event emission failed: {e}")

    async def execute(
        self,
        goal: str,
        intent: str = "informational",
        context: str = "",
        task: str = "",
        config: Optional[dict] = None,
    ) -> Phase1Intelligence:
        """
        Execute the LLM-driven research loop.

        Args:
            goal: The user's original query (preserves priority signals)
            intent: "informational" or "commerce"
            context: Session context from Planner (what we were discussing)
            task: Specific task from Planner (what to research)
            config: Optional config overrides (max_searches, max_visits, etc.)

        Returns:
            Phase1Intelligence with research results
        """
        logger.info(f"[ResearchLoop] Starting research")
        logger.info(f"[ResearchLoop] Goal: {goal}")
        if context:
            logger.info(f"[ResearchLoop] Context: {context[:100]}...")
        if task:
            logger.info(f"[ResearchLoop] Task: {task}")
        logger.info(f"[ResearchLoop] Intent: {intent}")

        start_time = time.time()
        state = create_initial_state(goal, intent, context, task, config)

        # Emit phase start event
        await self._emit_event("phase1_started", {
            "goal": goal,
            "intent": intent,
            "session_id": self.session_id,
        })

        try:
            # Main loop: Research Planner decides what to do
            while state.status == "in_progress":
                state.iteration += 1
                state.elapsed_seconds = time.time() - start_time

                # Check constraints
                if state.iteration > state.max_iterations:
                    logger.info("[ResearchLoop] Max iterations reached, forcing done")
                    break

                if state.elapsed_seconds > state.max_seconds:
                    logger.info("[ResearchLoop] Timeout reached, forcing done")
                    break

                # Get next action from Research Planner
                action = await self._get_planner_decision(state)

                if action is None:
                    logger.warning("[ResearchLoop] Planner returned no action, ending")
                    break

                logger.info(f"[ResearchLoop] Iteration {state.iteration}: {action.get('action')} - {action.get('reason', '')[:50]}")

                # Execute the action
                if action["action"] == "search":
                    await self._execute_search(state, action["query"])
                    await self._emit_event("search_complete", {
                        "query": action["query"],
                        "results_count": len(state.search_results),
                        "iteration": state.iteration,
                    })

                elif action["action"] == "visit":
                    await self._execute_visit(state, action["url"])
                    await self._emit_event("page_visited", {
                        "url": action["url"],
                        "pages_visited": len(state.visited_pages),
                        "iteration": state.iteration,
                    })

                elif action["action"] == "done":
                    state.status = "done"
                    logger.info(f"[ResearchLoop] Research complete: {action.get('reason', '')}")

                else:
                    logger.warning(f"[ResearchLoop] Unknown action: {action['action']}")
                    break

            # Build final result
            state.elapsed_seconds = time.time() - start_time

            # Emit phase complete event
            await self._emit_event("phase1_complete", {
                "success": True,
                "pages_visited": len(state.visited_pages),
                "searches_used": state.searches_used,
                "elapsed_seconds": state.elapsed_seconds,
            })

            return Phase1Intelligence(
                success=True,
                goal=goal,
                context=context,
                task=task,
                intelligence=state.intelligence,
                findings=self._extract_findings(state),
                vendor_hints=self._extract_vendor_hints(state),
                search_terms=self._extract_search_terms(state),
                price_range=state.intelligence.get("price_range"),
                sources=[p.url for p in state.visited_pages],
                research_state_md=state.to_markdown(),
                searches_used=state.searches_used,
                pages_visited=len(state.visited_pages),
                elapsed_seconds=state.elapsed_seconds,
            )

        except Exception as e:
            logger.error(f"[ResearchLoop] Error: {e}", exc_info=True)
            state.elapsed_seconds = time.time() - start_time

            return Phase1Intelligence(
                success=False,
                goal=goal,
                context=context,
                task=task,
                intelligence=state.intelligence,
                findings=[],
                vendor_hints=[],
                search_terms=[],
                price_range=None,
                sources=[p.url for p in state.visited_pages],
                research_state_md=state.to_markdown(),
                searches_used=state.searches_used,
                pages_visited=len(state.visited_pages),
                elapsed_seconds=state.elapsed_seconds,
            )

        finally:
            await self.browser.close()

    async def _get_planner_decision(self, state: ResearchState) -> Optional[dict]:
        """
        Get the next action from the Research Planner LLM.

        When turn_dir is available, uses recipe-based prompts (Document IO compliant).
        Falls back to legacy inline prompts when turn_dir is None.

        Returns:
            {"action": "search|visit|done", "query|url": "...", "reason": "..."}
        """
        # Build prompt for Research Planner
        # Use recipe-based prompt when turn_dir is available, otherwise use inline prompt
        if self.turn_dir:
            try:
                # Write current state for recipe to read
                state.write_to_turn(self.turn_dir)

                # Load recipe and build prompt
                from libs.gateway.recipe_loader import load_recipe
                from libs.gateway.doc_pack_builder import DocPackBuilder

                recipe = load_recipe("research/research_planner")
                builder = DocPackBuilder(use_smart_compression=True)
                pack = await builder.build_async(recipe, self.turn_dir)
                prompt = pack.as_prompt()

                logger.debug("[ResearchLoop] Using recipe-based prompt for planner")

            except Exception as e:
                # Log error but use inline prompt as fallback
                # TODO: Once recipe system is stable, make this a hard failure
                logger.warning(f"[ResearchLoop] Recipe loading failed: {e}, using inline prompt")
                prompt = self._build_planner_prompt(state)
        else:
            # No turn_dir provided - use inline prompt
            # This happens when called directly without Document IO context
            prompt = self._build_planner_prompt(state)

        try:
            import httpx

            messages = [
                {"role": "system", "content": "You are a research planner. Output valid JSON only."},
                {"role": "user", "content": prompt},
            ]

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self.llm_url,
                    json={
                        "model": self.llm_model,
                        "messages": messages,
                        "temperature": 0.5,  # MIND temperature for reasoning/planning
                        "max_tokens": 500,
                    },
                    headers={"Authorization": f"Bearer {self.llm_api_key}"},
                )
                response.raise_for_status()
                result = response.json()

            content = result["choices"][0]["message"]["content"]

            # Parse JSON from response
            action = self._parse_json_response(content)
            return action

        except Exception as e:
            logger.error(f"[ResearchLoop] Planner error: {e}")
            return None

    def _build_planner_prompt(self, state: ResearchState) -> str:
        """Build the prompt for the Research Planner."""
        state_md = state.to_markdown()

        remaining_searches = state.remaining_searches()
        remaining_visits = state.remaining_visits()
        remaining_time = state.max_seconds - state.elapsed_seconds

        prompt = f"""# Research Planner

You are planning web research to help answer a user's question.

{state_md}

## Constraints
- You can search up to {remaining_searches} more times
- You can visit up to {remaining_visits} more pages
- You have {remaining_time:.0f} seconds remaining

## Your Decision

Consider both the user's original query AND the context/task to understand what to research.

Think about:
1. Do I have enough information to answer the user well?
2. If not, what's missing?
3. Should I search, visit a page, or am I done?

For commerce queries, make sure you have:
- Understanding of what makes a good product
- Price expectations
- Recommended models/brands from real users

Output ONE action as JSON (no markdown, just JSON):
- {{"action": "search", "query": "your search terms", "reason": "why"}}
- {{"action": "visit", "url": "https://...", "reason": "why"}}
- {{"action": "done", "reason": "why I have enough"}}

Important:
- Use the CONTEXT to understand what specific product/topic to research
- Use the GOAL to understand user priorities (cheapest, best, fastest, etc.)
- If you've already visited the most relevant pages and have good information, call done
- If you need more information, visit the most promising unvisited page from search results
- If you have no search results yet, search first

JSON:"""

        return prompt

    async def _execute_search(self, state: ResearchState, query: str):
        """Execute a search and update state."""
        if not state.can_search():
            logger.warning("[ResearchLoop] No searches remaining")
            return

        result = await self.browser.search(query)

        if result.success and result.results:
            # Score the results
            scored = await self._score_search_results(state.goal, state.intent, result.results)

            # Update state
            state.add_search_results(scored)
            logger.info(f"[ResearchLoop] Search found {len(scored)} results")
        else:
            logger.warning(f"[ResearchLoop] Search failed: {result.error}")

    async def _execute_visit(self, state: ResearchState, url: str):
        """Visit a page and update state."""
        if not state.can_visit():
            logger.warning("[ResearchLoop] No visits remaining")
            return

        if state.is_url_visited(url):
            logger.info(f"[ResearchLoop] Already visited: {url}")
            return

        if should_skip_url(url):
            logger.info(f"[ResearchLoop] Skipping (social media): {url}")
            return

        result = await self.browser.visit(url)

        if result.success and result.text:
            # Extract findings using Content Extractor LLM
            findings = await self._extract_page_content(
                state.goal, state.intent, url, result.title, result.text
            )

            if findings:
                # Add to state
                page_findings = PageFindings(
                    url=url,
                    visited_at=datetime.now().isoformat(),
                    relevance=findings.get("relevance", 0.5),
                    confidence=findings.get("confidence", 0.5),
                    summary=findings.get("summary", ""),
                    findings=findings,
                )
                state.add_page_findings(page_findings)

                # Update intelligence
                intel_update = self._findings_to_intelligence(findings)
                if intel_update:
                    state.update_intelligence(intel_update)

                logger.info(f"[ResearchLoop] Extracted findings from {url}")
        else:
            if result.blocked:
                logger.warning(f"[ResearchLoop] Page blocked ({result.blocker_type}): {url}")
            else:
                logger.warning(f"[ResearchLoop] Visit failed: {result.error}")

    async def _score_search_results(
        self, goal: str, intent: str, results: list[dict]
    ) -> list[SearchResult]:
        """Score search results using Result Scorer LLM."""
        # Format results for scoring
        results_text = ""
        for i, r in enumerate(results, 1):
            results_text += f"{i}. {r.get('title', 'No title')}\n"
            results_text += f"   URL: {r.get('url', '')}\n"
            if r.get("snippet"):
                results_text += f"   Snippet: {r.get('snippet', '')[:100]}...\n"
            results_text += "\n"

        prompt = f"""# Result Scorer

Score these search results for relevance to the goal.

## Goal
{goal}

## Intent
{intent}

## Search Results
{results_text}

## Score Each Result

For each result (by number), output:
- score: 0.0 to 1.0 (how relevant/useful it likely is)
- type: forum | review | vendor | news | official | other
- priority: must_visit | should_visit | maybe | skip

Consider:
- Does the title suggest relevant content?
- Is this a trustworthy source type for this query?
- For commerce: prioritize reviews and forums over vendors

Output as JSON array, ranked by score (highest first):
[{{"index": 1, "score": 0.9, "type": "forum", "priority": "must_visit"}}, ...]

JSON:"""

        try:
            import httpx

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.llm_url,
                    json={
                        "model": self.llm_model,
                        "messages": [
                            {"role": "system", "content": "You are a result scorer. Output valid JSON array only."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.3,  # REFLEX temperature
                        "max_tokens": 1000,
                    },
                    headers={"Authorization": f"Bearer {self.llm_api_key}"},
                )
                response.raise_for_status()
                result = response.json()

            content = result["choices"][0]["message"]["content"]
            scores = self._parse_json_response(content)

            if not isinstance(scores, list):
                scores = []

        except Exception as e:
            logger.warning(f"[ResearchLoop] Scoring failed, using defaults: {e}")
            scores = []

        # Build scored results
        scored_results = []
        scores_by_index = {s.get("index", i+1): s for i, s in enumerate(scores)}

        for i, r in enumerate(results, 1):
            score_info = scores_by_index.get(i, {})
            scored_results.append(SearchResult(
                url=r.get("url", ""),
                title=r.get("title", ""),
                snippet=r.get("snippet", ""),
                score=score_info.get("score", 0.5),
                source_type=score_info.get("type", "unknown"),
                priority=score_info.get("priority", "maybe"),
            ))

        # Sort by score descending
        scored_results.sort(key=lambda x: x.score, reverse=True)
        return scored_results

    async def _extract_page_content(
        self, goal: str, intent: str, url: str, title: str, text: str
    ) -> Optional[dict]:
        """Extract findings from page text using Content Extractor LLM."""
        prompt = f"""# Content Extractor

Extract useful information from this page.

## Goal
{goal}

## Intent
{intent}

## Page URL
{url}

## Page Title
{title}

## Page Content
{text[:8000]}

## What to Extract

### For Informational Queries:
- key_facts: Important information relevant to the goal (list)
- recommendations: Any advice or suggestions (list)

### For Commerce Queries:
- recommended_products: Products mentioned positively (list of names)
- price_expectations: Price ranges mentioned (object with min/max)
- specs_to_look_for: Features users recommend (list)
- warnings: Things to avoid, common issues (list)
- vendors_mentioned: Where users suggest buying (list)

### Always Include:
- relevance: 0.0-1.0 how relevant was this page
- confidence: 0.0-1.0 how confident in the extracted info
- summary: 1-2 sentence summary of what was useful

Output as JSON:"""

        try:
            import httpx

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self.llm_url,
                    json={
                        "model": self.llm_model,
                        "messages": [
                            {"role": "system", "content": "You are a content extractor. Output valid JSON only."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.5,  # MIND temperature
                        "max_tokens": 1500,
                    },
                    headers={"Authorization": f"Bearer {self.llm_api_key}"},
                )
                response.raise_for_status()
                result = response.json()

            content = result["choices"][0]["message"]["content"]
            findings = self._parse_json_response(content)
            return findings if isinstance(findings, dict) else None

        except Exception as e:
            logger.warning(f"[ResearchLoop] Extraction failed: {e}")
            return None

    def _findings_to_intelligence(self, findings: dict) -> dict:
        """Convert page findings to intelligence updates."""
        intel = {}

        # Recommended products
        if findings.get("recommended_products"):
            intel["recommended_models"] = findings["recommended_products"]

        # Price expectations
        if findings.get("price_expectations"):
            intel["price_range"] = findings["price_expectations"]

        # Specs to look for
        if findings.get("specs_to_look_for"):
            intel["what_to_look_for"] = findings["specs_to_look_for"]

        # Warnings
        if findings.get("warnings"):
            intel["user_warnings"] = findings["warnings"]

        # Vendors
        if findings.get("vendors_mentioned"):
            intel["vendors_mentioned"] = findings["vendors_mentioned"]

        # Key facts (informational)
        if findings.get("key_facts"):
            intel["key_facts"] = findings["key_facts"]

        # Recommendations (informational)
        if findings.get("recommendations"):
            intel["recommendations"] = findings["recommendations"]

        return intel

    def _extract_findings(self, state: ResearchState) -> list:
        """Extract consolidated findings from state."""
        findings = []

        # Add key facts
        if state.intelligence.get("key_facts"):
            findings.extend(state.intelligence["key_facts"])

        # Add recommendations
        if state.intelligence.get("recommendations"):
            findings.extend(state.intelligence["recommendations"])

        # Add what to look for
        if state.intelligence.get("what_to_look_for"):
            findings.extend(state.intelligence["what_to_look_for"])

        return findings

    def _extract_vendor_hints(self, state: ResearchState) -> list[str]:
        """Extract vendor hints for Phase 2."""
        return state.intelligence.get("vendors_mentioned", [])

    def _extract_search_terms(self, state: ResearchState) -> list[str]:
        """Extract useful search terms for Phase 2."""
        terms = []

        # Add recommended models as search terms
        if state.intelligence.get("recommended_models"):
            terms.extend(state.intelligence["recommended_models"])

        return terms

    def _parse_json_response(self, content: str) -> Optional[dict | list]:
        """Parse JSON from LLM response, handling markdown code blocks."""
        # Strip markdown code blocks if present
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first and last lines (code block markers)
            lines = [l for l in lines if not l.startswith("```")]
            content = "\n".join(lines)

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Try to find JSON in the content
            import re
            json_match = re.search(r'(\{.*\}|\[.*\])', content, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(1))
                except:
                    pass
            logger.warning(f"[ResearchLoop] Could not parse JSON: {content[:200]}")
            return None


async def execute_research(
    goal: str,
    intent: str = "informational",
    context: str = "",
    task: str = "",
    session_id: Optional[str] = None,
    config: Optional[dict] = None,
    event_emitter: Optional[Any] = None,
    human_assist_allowed: bool = True,
    turn_dir_path: Optional[str] = None,
) -> Phase1Intelligence:
    """
    Execute LLM-driven research.

    Args:
        goal: The user's original query (preserves priority signals like "cheapest")
        intent: "informational" or "commerce"
        context: Session context from Planner (what we were discussing)
        task: Specific task from Planner (what to research)
        session_id: Browser session ID
        config: Optional config overrides
        event_emitter: Optional event emitter for progress events
        human_assist_allowed: Whether to allow human intervention for CAPTCHAs
        turn_dir_path: Turn directory path for Document IO compliance

    Returns:
        Phase1Intelligence with research results
    """
    session_id = session_id or f"research_{int(time.time())}"

    # Load turn_dir if path provided
    turn_dir = None
    if turn_dir_path:
        try:
            from libs.gateway.turn_manager import TurnDirectory
            turn_dir = TurnDirectory(Path(turn_dir_path))
        except Exception as e:
            logger.warning(f"[execute_research] Could not load turn_dir: {e}")

    loop = ResearchLoop(
        session_id=session_id,
        turn_dir=turn_dir,
        event_emitter=event_emitter,
        human_assist_allowed=human_assist_allowed,
    )
    return await loop.execute(
        goal=goal,
        intent=intent,
        context=context,
        task=task,
        config=config,
    )
