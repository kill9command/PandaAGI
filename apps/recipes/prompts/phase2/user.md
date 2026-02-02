# Phase 2: Context Gatherer - User Prompt Template

## Original Query

{query}

## Query Analysis (from Phase 0)

{query_analysis}

## Available Turn Summaries

{turn_summaries}

## Memory Store Contents

{memory_results}

## Research Cache Headers

{research_cache_headers}

## Your Task

Analyze the query and available sources to gather all relevant context. Consider:

1. Which prior turns discuss topics related to this query?
2. What user preferences affect how to answer this query?
3. Is there cached research that can be reused?
4. What is missing that would require new research?

Output your GatheredContext JSON.
