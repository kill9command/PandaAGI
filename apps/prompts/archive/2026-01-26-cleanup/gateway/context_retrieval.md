# Context Gatherer - Retrieval Phase Prompt (2-Phase)

## Purpose
Phase 1 of the 2-phase context gatherer. Combines turn identification AND context evaluation in a single pass.

## Prompt Template

TURN INDEX:
{turn_index}

LOADED CONTEXTS (top {context_count} turns):
{context_bundle}

{followup_hint}

---

CURRENT QUERY: {query}

===== YOUR TASK =====

1. IDENTIFY which turns from the index are relevant to the CURRENT QUERY
2. EVALUATE the loaded contexts - what info can be used directly?
3. DECIDE if any links need to be followed for more detail

Output JSON with this structure:
```json
{
  "turns": [
    {
      "turn": <turn_number>,
      "relevance": "critical|high|medium|low",
      "reason": "why this turn is relevant",
      "usable_info": "specific info from this turn that can be used directly (MUST come from the turn's content above, NOT from the current query)"
    }
  ],
  "links_to_follow": [
    {
      "turn": <turn_number>,
      "path": "path/to/research.md or research.json",
      "reason": "why we need more detail from this doc",
      "extract": ["products", "prices", "recommendations"]
    }
  ],
  "sufficient": true/false,
  "missing_info": "what info is still needed (if any)",
  "reasoning": "your reasoning process"
}
```

## Key Rules

1. **RULE ZERO (FOLLOW-UPS):** For follow-up queries (containing "it", "that", "some", "again", "more"), the N-1 turn (immediately preceding) is ALWAYS CRITICAL. It contains the subject being referenced.

2. **RULE ONE (TOPIC RELEVANCE):** Only mark turns as relevant if their topic matches the current query. A laptop query should not pull in hamster turns, and vice versa.

3. **RULE TWO (RECENCY):** More recent turns are generally more relevant than older ones.

4. **RULE THREE (DIRECT INFO):** Extract usable information directly - don't just note that information exists.

5. **RULE FOUR (RELATED DOCUMENTS):** When you see a "Related Documents" section or "Has Research" link in a turn, check if the linked document contains information relevant to the current query. If so, add it to `links_to_follow`.

6. **RULE FIVE (CONTENT REFERENCES):** When the user references something mentioned in a prior turn's response (a thread, article, product, etc.), follow the toolresults.md link. The `extracted_links` array contains `{title, url}` pairs - match the referenced item to get its URL, and include that URL in usable_info so the Planner can navigate to it.

7. **RULE SIX (QUERY-SCOPE MATCHING):** When extracting `usable_info`, only include information that matches the scope of the CURRENT query. If a prior turn contains extra attributes or qualifiers not mentioned in the current query, DO NOT include them.

8. **RULE SEVEN (USABLE_INFO SOURCE - CRITICAL):** The `usable_info` field MUST contain information that actually exists in the prior turn's content shown in LOADED CONTEXTS above. Do NOT attribute information from the CURRENT QUERY to prior turns. If a prior turn asked a question but didn't receive an answer, `usable_info` should reflect that (e.g., "user asked about X but no answer was provided"). Never hallucinate that a prior turn contains information it doesn't have.

9. **RULE EIGHT (NO URL FABRICATION):** When extracting `usable_info`, only include URLs that are EXPLICITLY present in the source content. If a turn mentions "at Newegg" or "from Amazon" but has no actual URL, do NOT invent one. Report the vendor name without a fabricated link.

10. **RULE NINE (METADATA QUESTIONS):** When the user asks about metadata of previously visited content (page count, reply count, author, date, length, etc.), the answer is likely in the prior turn's data - NOT new research. Look for:
   - `page_metadata` in toolresults.md (contains total_pages, total_replies, etc.)
   - Page info in the summary text ("**Page Info:** Total pages: X")
   - These questions should be marked as `sufficient: true` if the prior turn has this data.

   **Example:**
   - Query: "best eggnog recipe"
   - Prior turn: "vegan eggnog recipe using cashews and almond milk"
   - WRONG usable_info: "vegan eggnog recipe using cashews" (introduces "vegan")
   - RIGHT usable_info: "eggnog recipe found" or just mark as medium relevance without carrying over the "vegan" constraint

   The current query's terms define the scope. Prior turns may have had different constraints - don't let those contaminate the current search.

Example Related Documents section:
```markdown
## Related Documents
- [Research](./research.md) | [[turns/turn_000815/research|Research]]
- [Metrics](./metrics.json) | [[turns/turn_000815/metrics|Metrics]]
```

If the query needs pricing data and you see a Research link, add it to `links_to_follow`:
```json
{
  "links_to_follow": [
    {"turn": 815, "path": "turn_000815/research.md", "reason": "contains pricing details", "extract": ["products", "prices"]}
  ]
}
```
