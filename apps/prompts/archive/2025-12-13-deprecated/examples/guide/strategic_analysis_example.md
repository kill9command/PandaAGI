# Strategic Analysis Example

## Complete STRATEGIC_ANALYSIS Format

```json
{
  "_type": "STRATEGIC_ANALYSIS",
  "cache_evaluation": {
    "previous_queries": ["find Syrian hamster breeders online"],
    "current_query": "what food and cage should I get for Syrian hamster",
    "intent_shift": "different",
    "decision": "fresh_search",
    "confidence": 0.97,
    "reasoning": "Previous query was about finding breeders (transactional/navigational). Current query is about care supplies (informational). Domain shift from 'finding sellers' to 'care recommendations' means breeder results won't help. Fresh search required."
  },
  "goal_decomposition": {
    "is_multi_goal": true,
    "identified_goals": ["hamster food recommendations", "hamster cage recommendations"],
    "execution_strategy": "parallel",
    "confidence": 0.93,
    "reasoning": "User asks for TWO things: food AND cage. These are independent care topics that can be researched simultaneously. Each needs separate search with appropriate keywords."
  },
  "success_criteria": {
    "must_contain_keywords": ["food", "diet", "cage", "habitat", "care"],
    "min_results": 3,
    "quality_preference": "verified_sources",
    "freshness_requirement": "recent",
    "confidence": 0.90,
    "reasoning": "Care advice should be current (pet care evolves) and from credible sources (vet sites, established breeders, care guides). Need specific actionable recommendations, not just product listings."
  }
}
```

## Cache Evaluation Decision Types

- **reuse_perfect**: Previous results fully answer current query; no new search needed
- **reuse_partial**: Some overlap; supplement cache with targeted new search
- **fresh_search**: Different intent, stale results, or no relevant cache

## Intent Shift Detection Rules

**CRITICAL:** Detect intent shifts by analyzing what TYPE of information the user needs, not just keywords.

### Intent Categories (Granular)

1. **Navigational-Directory**: Finding service providers, breeders, clinics
   - Examples: "find breeders", "hamster vets near me", "breeder directory"
   - Result type: Contact info, locations, directories

2. **Transactional-Retail**: Purchasing products from stores
   - Examples: "where can I buy", "hamster for sale", "purchase cage"
   - Result type: Store listings, product pages, prices

3. **Transactional-Individual**: Peer-to-peer sales, adoptions
   - Examples: "hamster adoption", "rehoming hamster", "buy from owner"
   - Result type: Classifieds, adoption posts, individual sellers

4. **Informational-Care**: How-to guides, requirements, general knowledge
   - Examples: "what food do they need", "cage size requirements", "how to care"
   - Result type: Articles, guides, specifications

5. **Informational-Product**: Product recommendations, comparisons
   - Examples: "best hamster food brands", "cage recommendations"
   - Result type: Product reviews, brand lists, comparisons

### Intent Shift Examples

**Example 1: Navigational → Transactional**
```
Previous: "find Syrian hamster breeders" (navigational-directory)
Current: "where can I buy a Syrian hamster" (transactional-retail)
→ intent_shift: "different"
→ decision: "fresh_search"
→ reasoning: "Query changed from finding breeder contacts to finding retail purchase options. User wants stores/products, not breeder directories."
```

**Example 2: Navigational → Informational**
```
Previous: "find hamster breeders near me" (navigational-directory)
Current: "what food and cage do they need" (informational-care)
→ intent_shift: "different"
→ decision: "fresh_search"
→ reasoning: "Intent shifted from finding service providers to learning care requirements. Breeder contact info won't answer care questions."
```

**Example 3: Informational → Informational (Same Type)**
```
Previous: "what food do hamsters need" (informational-care)
Current: "what are good hamster cage sizes" (informational-care)
→ intent_shift: "same"
→ decision: "reuse_perfect" OR "fresh_search" (depends on cache content)
→ reasoning: "Both queries seek care information. If cache has cage info, reuse. If not, fresh search."
```

**Example 4: Repeat Query with Poor Results**
```
Previous: "find Syrian hamster breeders" → returned only 1 result
Current: "find Syrian hamster breeders" (identical query)
→ intent_shift: "same"
→ decision: "fresh_search"
→ reasoning: "User repeating query indicates dissatisfaction with previous results (only 1 listing). Expand search scope or try different approach."
```

**Example 5: Generic Query with Stated Preference (Mismatch)**
```
Previous: "tell me about hamsters" (informational-care)
Conversation history includes: "The Syrian hamster is my favorite pet"
Cached results: Generic hamster information (no breed specificity)
Current: "can you find some for sale for me online?" (transactional-retail)
→ previous_intent_type: "informational-care"
→ current_intent_type: "transactional-retail"
→ intent_shift: "different"
→ decision: "fresh_search"
→ reasoning: "User previously stated 'Syrian hamster is my favorite pet.' Current query 'find some for sale' is generic but user's preference should constrain it. Cached results are for generic hamsters which doesn't match stated preference for Syrian hamsters. Fresh search required with preference constraint: 'Syrian hamster for sale'."
```

**Example 6: Generic Query with Stated Preference (Match)**
```
Previous: "find Syrian hamster for sale" (transactional-retail)
Conversation history includes: "Syrian hamster is my favorite"
Cached results: 5 Syrian hamster purchase options
Current: "are there any others?" (transactional-retail)
→ previous_intent_type: "transactional-retail"
→ current_intent_type: "transactional-retail"
→ intent_shift: "same"
→ decision: "reuse_perfect"
→ reasoning: "User asks for 'others' - generic query, but previous search was for Syrian hamsters matching their stated preference. Cache contains relevant Syrian hamster results. Preference continuity maintained."
```

**Example 7: Explicit Override of Stated Preference**
```
Previous: "find Syrian hamster breeders" (navigational-directory)
Conversation history includes: "Syrian hamster is my favorite"
Current: "what about Roborovski hamster breeders instead?" (navigational-directory)
→ previous_intent_type: "navigational-directory"
→ current_intent_type: "navigational-directory"
→ intent_shift: "same"
→ decision: "fresh_search"
→ reasoning: "User explicitly requested Roborovski hamsters, overriding previous preference for Syrian hamsters. Cache contains Syrian hamster breeders, but query explicitly requests different breed. Fresh search required despite preference history."
```

### Detection Checklist

Before deciding cache reuse, ask:
1. **Does current query ask for DIFFERENT TYPE of result?**
   - Directory vs products vs guides vs specifications
   - If yes → intent_shift: "different", decision: "fresh_search"

2. **Is current query IDENTICAL or VERY SIMILAR to previous?**
   - Check if previous results were poor quality (low count, low scores)
   - If repeat + poor quality → decision: "fresh_search" with expanded params

3. **Do cached results actually ANSWER current query?**
   - Breeder contacts DON'T answer "where to buy products"
   - Care guides DON'T answer "find breeders"
   - If no → decision: "fresh_search"

## Goal Decomposition Strategies

- **parallel**: Independent goals, can search simultaneously ("find X AND Y")
- **sequential**: Dependent goals, must complete in order ("analyze X then recommend Y")
- **single**: One unified goal

## Confidence Scoring Guidelines

- **0.9-1.0 (Very High)**: Obvious decision, clear intent, no ambiguity
- **0.7-0.89 (High)**: Strong evidence, minor ambiguity
- **0.5-0.69 (Medium)**: Uncertain, could go either way
- **0.0-0.49 (Low)**: Guessing, need clarification

After emitting STRATEGIC_ANALYSIS, create your ticket based on these decisions.
