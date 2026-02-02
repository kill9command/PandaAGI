"""
Search Result Evaluator

Assesses the quality of search results to determine if additional queries are needed.
Uses both heuristics and optionally LLM-based evaluation.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

# Prompt file path
_PROMPTS_DIR = Path(__file__).parent.parent / "apps" / "prompts" / "filtering"
_SEARCH_RESULT_EVALUATOR_PROMPT_PATH = _PROMPTS_DIR / "search_result_evaluator.md"

# Prompt cache
_search_result_evaluator_prompt: Optional[str] = None


def _load_search_result_evaluator_prompt() -> str:
    """Load the search result evaluator prompt from file."""
    global _search_result_evaluator_prompt
    if _search_result_evaluator_prompt is None:
        if _SEARCH_RESULT_EVALUATOR_PROMPT_PATH.exists():
            _search_result_evaluator_prompt = _SEARCH_RESULT_EVALUATOR_PROMPT_PATH.read_text()
            logger.info(f"[SearchResultEvaluator] Loaded prompt from {_SEARCH_RESULT_EVALUATOR_PROMPT_PATH}")
        else:
            logger.warning(f"[SearchResultEvaluator] Prompt file not found: {_SEARCH_RESULT_EVALUATOR_PROMPT_PATH}")
            _search_result_evaluator_prompt = "Evaluate search results quality. Return JSON with satisfied, quality_score, gaps, recommendation, and suggested_refinements."
    return _search_result_evaluator_prompt


class SearchResultEvaluator:
    """Evaluates search result quality and determines if more searches are needed."""

    def __init__(
        self,
        solver_url: str,
        solver_model_id: str,
        solver_api_key: str,
        min_quality_threshold: float = 0.7
    ):
        """
        Initialize Search Result Evaluator.

        Args:
            solver_url: URL of the LLM solver service
            solver_model_id: Model ID to use for evaluation
            solver_api_key: API key for authentication
            min_quality_threshold: Minimum quality score to be satisfied (0.0-1.0)
        """
        self.solver_url = solver_url
        self.solver_model_id = solver_model_id
        self.solver_api_key = solver_api_key
        self.min_quality_threshold = min_quality_threshold

    async def evaluate_search_results(
        self,
        results: Dict,
        required_fields: Optional[List[str]] = None,
        goal: Optional[str] = None,
        use_llm: bool = False,
        token_budget: int = 300
    ) -> Dict:
        """
        Evaluate search results quality.

        Args:
            results: Search results to evaluate
            required_fields: Fields that must be present for satisfaction
            goal: Research goal to evaluate against
            use_llm: Whether to use LLM for deeper evaluation (costs tokens)
            token_budget: Token budget for LLM evaluation

        Returns:
            Dict containing:
                - satisfied: bool - Whether results meet quality threshold
                - quality_score: float - Overall quality score (0.0-1.0)
                - found_fields: List[str] - Fields found in results
                - missing_fields: List[str] - Required fields still missing
                - gaps: str - Description of what's missing
                - recommendation: str - "continue" or "stop"
                - suggested_refinements: List[str] - How to improve next query
        """
        logger.info("[ResultEvaluator] Evaluating search results")

        # Start with heuristic evaluation
        evaluation = self._heuristic_evaluation(results, required_fields, goal)

        # Optionally use LLM for deeper analysis
        if use_llm and not evaluation["satisfied"]:
            try:
                llm_eval = await self._llm_evaluation(
                    results, required_fields, goal, token_budget
                )
                # Merge LLM insights into heuristic evaluation
                evaluation.update(llm_eval)
            except Exception as e:
                logger.warning(f"[ResultEvaluator] LLM evaluation failed: {e}")

        logger.info(
            f"[ResultEvaluator] Quality: {evaluation['quality_score']:.2f}, "
            f"Satisfied: {evaluation['satisfied']}, "
            f"Recommendation: {evaluation['recommendation']}"
        )

        return evaluation

    def _heuristic_evaluation(
        self,
        results: Dict,
        required_fields: Optional[List[str]],
        goal: Optional[str]
    ) -> Dict:
        """
        Perform fast heuristic-based evaluation without LLM.

        Checks:
        - Number of results
        - Presence of required fields
        - Diversity of sources
        - Basic quality indicators
        """
        required_fields = required_fields or []

        # Extract search results
        search_results = results.get("organic_results", [])
        num_results = len(search_results)

        # Check for required fields in results
        found_fields = set()
        missing_fields = set(required_fields)

        for result in search_results:
            # Check what fields are present
            if "title" in result and result["title"]:
                found_fields.add("title")
            if "link" in result and result["link"]:
                found_fields.add("link")
            if "snippet" in result and result["snippet"]:
                found_fields.add("snippet")

            # For commerce queries, check for pricing indicators
            snippet = result.get("snippet", "").lower()
            if any(keyword in snippet for keyword in ["$", "price", "buy", "sale", "shop"]):
                found_fields.add("price")

        # Update missing fields
        missing_fields = missing_fields - found_fields

        # Calculate quality score
        quality_score = self._calculate_quality_score(
            num_results=num_results,
            found_fields=found_fields,
            required_fields=required_fields
        )

        # Determine satisfaction
        satisfied = quality_score >= self.min_quality_threshold

        # Generate gaps description
        gaps = self._describe_gaps(num_results, found_fields, missing_fields)

        # Make recommendation
        recommendation = "stop" if satisfied else "continue"

        # Suggest refinements if not satisfied
        suggested_refinements = []
        if not satisfied:
            suggested_refinements = self._suggest_refinements(
                num_results, found_fields, missing_fields
            )

        return {
            "satisfied": satisfied,
            "quality_score": quality_score,
            "found_fields": list(found_fields),
            "missing_fields": list(missing_fields),
            "gaps": gaps,
            "recommendation": recommendation,
            "suggested_refinements": suggested_refinements,
            "num_results": num_results
        }

    def _calculate_quality_score(
        self,
        num_results: int,
        found_fields: set,
        required_fields: List[str]
    ) -> float:
        """
        Calculate overall quality score (0.0-1.0).

        Factors:
        - Number of results (more is better, up to a point)
        - Presence of required fields
        - Diversity indicators
        """
        score = 0.0

        # Results count score (max 0.4)
        if num_results >= 5:
            score += 0.4
        elif num_results >= 3:
            score += 0.3
        elif num_results >= 1:
            score += 0.2

        # Required fields score (max 0.4)
        if required_fields:
            field_coverage = len(found_fields & set(required_fields)) / len(required_fields)
            score += 0.4 * field_coverage
        else:
            # If no required fields specified, give partial credit for common fields
            common_fields = {"title", "link", "snippet"}
            field_coverage = len(found_fields & common_fields) / len(common_fields)
            score += 0.4 * field_coverage

        # Basic quality indicators (max 0.2)
        if "price" in found_fields:
            score += 0.1  # Commerce indicator
        if num_results >= 3:
            score += 0.1  # Diversity indicator

        return min(1.0, score)

    def _describe_gaps(
        self,
        num_results: int,
        found_fields: set,
        missing_fields: set
    ) -> str:
        """Generate human-readable description of gaps."""
        gaps = []

        if num_results == 0:
            return "No results found"

        if num_results < 3:
            gaps.append(f"Only {num_results} result(s) found, need more variety")

        if missing_fields:
            gaps.append(f"Missing required fields: {', '.join(missing_fields)}")

        if "price" not in found_fields:
            gaps.append("No pricing information detected")

        return "; ".join(gaps) if gaps else "No significant gaps"

    def _suggest_refinements(
        self,
        num_results: int,
        found_fields: set,
        missing_fields: set
    ) -> List[str]:
        """Suggest how to refine the next query."""
        suggestions = []

        if num_results < 3:
            suggestions.append("Try broader or alternative keywords")

        if "price" in missing_fields or "price" not in found_fields:
            suggestions.append("Add pricing keywords (buy, sale, price, shop)")

        if num_results == 0:
            suggestions.append("Try different search engine or query approach")

        return suggestions

    async def _llm_evaluation(
        self,
        results: Dict,
        required_fields: Optional[List[str]],
        goal: Optional[str],
        token_budget: int
    ) -> Dict:
        """
        Use LLM for deeper result evaluation.

        This is more expensive but can provide nuanced assessment of:
        - Relevance to goal
        - Quality of sources
        - Completeness of information
        """
        logger.info("[ResultEvaluator] Performing LLM-based evaluation")

        # Prepare results summary for LLM
        results_summary = self._summarize_results_for_llm(results)

        # Load base prompt from file
        base_prompt = _load_search_result_evaluator_prompt()

        prompt = f"""{base_prompt}

---

## Current Task

**Research Goal:** {goal or "Find relevant information"}

**Required Fields:** {required_fields or "None specified"}

**Search Results Summary:**
{results_summary}

Evaluate the results and provide your assessment."""

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.solver_url}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.solver_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.solver_model_id,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,
                        "max_tokens": token_budget
                    }
                )
                response.raise_for_status()
                result = response.json()

                content = result["choices"][0]["message"]["content"]

                # Parse JSON response
                import json
                start_idx = content.find('{')
                end_idx = content.rfind('}') + 1
                json_str = content[start_idx:end_idx]
                llm_eval = json.loads(json_str)

                return llm_eval

        except Exception as e:
            logger.error(f"[ResultEvaluator] LLM evaluation failed: {e}", exc_info=True)
            raise

    def _summarize_results_for_llm(self, results: Dict, max_results: int = 5) -> str:
        """Summarize search results for LLM evaluation."""
        search_results = results.get("organic_results", [])[:max_results]

        summary_lines = []
        for i, result in enumerate(search_results, 1):
            title = result.get("title", "No title")
            snippet = result.get("snippet", "No snippet")
            link = result.get("link", "No link")

            summary_lines.append(f"{i}. {title}")
            summary_lines.append(f"   URL: {link}")
            summary_lines.append(f"   Snippet: {snippet}")
            summary_lines.append("")

        return "\n".join(summary_lines)


async def evaluate_search_results(
    results: Dict,
    required_fields: Optional[List[str]] = None,
    goal: Optional[str] = None,
    use_llm: bool = False,
    token_budget: int = 300,
    min_quality_threshold: float = 0.7,
    solver_url: str = "http://127.0.0.1:8000",
    solver_model_id: str = "qwen3-coder",
    solver_api_key: str = "qwen-local"
) -> Dict:
    """
    Convenience function to evaluate search results.

    This is the main entry point for other modules to use.
    """
    evaluator = SearchResultEvaluator(
        solver_url=solver_url,
        solver_model_id=solver_model_id,
        solver_api_key=solver_api_key,
        min_quality_threshold=min_quality_threshold
    )

    return await evaluator.evaluate_search_results(
        results=results,
        required_fields=required_fields,
        goal=goal,
        use_llm=use_llm,
        token_budget=token_budget
    )
