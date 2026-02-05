# Context Gatherer - Synthesis Phase Prompt (2-Phase)

## Purpose
Phase 2 of the 2-phase context gatherer. Combines extraction (if links present) AND compilation into final context.md section 1.

## Prompt Template

CURRENT QUERY: {query}
TURN NUMBER: {turn_number}

===== DIRECT INFORMATION =====
{direct_info_section}

{linked_docs_section}

{supplementary_section}

===== YOUR TASK =====

{extraction_task}COMPILE: Create the section 1 Gathered Context section for context.md.

Structure your output as MARKDOWN with these sections (ONLY include sections that have RELEVANT content):
- ### Repository Context (if code mode with repo - INCLUDE FIRST if present in supplementary sources)
- ### Topic Classification (Topic + Intent)
- ### Prior Turn Context (what we learned from relevant turns)
- ### User Preferences (ONLY if preferences are relevant to the current query topic)
- ### Forever Memory Knowledge (ONLY if knowledge documents relate to the current query topic)
- ### Prior Research Intelligence (if research index matches exist AND relate to query)
- ### Cached Intelligence (if intelligence cache hit AND relates to query)
- ### Relevant Strategy Lessons (if lessons matched AND relate to query)
- ### Memory Status (summary of what context is available)

CRITICAL - RELEVANCE FILTERING:
**OMIT sections entirely if their content is NOT relevant to the current query.**

Example:
- Query: "tell me about Russian troll farms"
- Forever Memory has: russian_information_warfare_history.md → INCLUDE in Forever Memory Knowledge
- Stored Preferences has: "favorite hamster: Syrian" → OMIT User Preferences section entirely (hamsters are not relevant to troll farms)

Example:
- Query: "find me a Syrian hamster for sale"
- Forever Memory has: russian_information_warfare_history.md → OMIT Forever Memory Knowledge (troll farms not relevant to hamster shopping)
- Stored Preferences has: "favorite hamster: Syrian" → INCLUDE in User Preferences (directly relevant)

IMPORTANT: If the supplementary sources contain "### Repository Context", include it FIRST in your output - this provides critical context for code mode queries.

Output MARKDOWN only (no JSON wrapper).

## Key Rules

1. **PRESERVE SPECIFICS:** Keep vendor names, prices, product names, AND source URLs/links.

2. **NEVER INVENT URLs (CRITICAL):** If the source data says "at Newegg" or "from Amazon" but has NO actual URL, do NOT create one. Only include URLs that are explicitly present in the source material.

   **WRONG:** Source says "Price: $699 at Newegg" → Output: "[Newegg](https://www.newegg.com/msi-thin-gf63-laptop/)"
   **RIGHT:** Source says "Price: $699 at Newegg" → Output: "Price: $699 at Newegg" (no URL)
   **RIGHT:** Source says "Price: $699 - https://newegg.com/p/N82E..." → Output: "[Newegg](https://newegg.com/p/N82E...)"

3. **PRESERVE SOURCES (CRITICAL):** When forever memory contains `**Sources:**` or `**Source:**` blocks, COPY THEM VERBATIM to your output. Do NOT summarize sources as prose.

   **WRONG:** "Key sources include Jessikka Aro's work..."
   **RIGHT:**
   ```
   **Sources:**
   - See: russian_info_warfare_system
   - Jessikka Aro 'Putin's Trolls'
   ```

   Place source blocks directly after the relevant content section.

3. **COMPRESS VERBOSITY:** Remove redundant information, but keep source attribution.

4. **MAINTAIN STRUCTURE:** Follow the section format above.

5. **BE CONCISE:** Target ~500-800 words for the entire section.

6. **CODE MODE:** If Repository Context is present, it should appear FIRST as it provides critical context for code-related queries.

7. **QUERY-FOCUSED FILTERING (CRITICAL):** Only include information that directly relates to the current query's terms. If prior turns contain extra attributes or constraints not mentioned in the current query (e.g., prior turn says "vegan eggnog" but current query just asks for "eggnog"), DO NOT include those extra attributes ("vegan"). The gathered context must NOT introduce terms, filters, or constraints that the user did not specify. Match the query scope exactly.

   **Example:**
   - Query: "best eggnog recipe"
   - Prior turn had: "vegan eggnog recipe with cashews"
   - WRONG: Include "vegan" → biases the search
   - RIGHT: Include "eggnog recipe" only → matches query scope
