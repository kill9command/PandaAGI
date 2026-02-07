# Phase 1 Search Query Builder (Structured Output)

Extract search components from the user's query. Output JSON only.

## Output Format

```json
{
  "keywords": ["main", "search", "terms"],
  "site": "domain.com or null",
  "quoted_phrase": "exact phrase or null",
  "context_keywords": ["from", "prior", "context"]
}
```

## Rules

1. **keywords**: Core search terms (2-6 words). Remove filler ("find me", "can you", "please").

   **IMPORTANT - Preserve price signals for commerce queries:**
   - Keep: "cheapest", "budget", "under $X", "best value", "deals"
   - Add source hints for commerce: "buying guide", "reddit", "recommendations"
   - Example: "cheapest laptop nvidia gpu" -> ["cheapest", "laptop", "nvidia", "gpu", "reddit", "recommendations"]

2. **site**: If user mentions a specific site, map to domain:
   - "Reddit", "r/" -> "reddit.com"
   - "ExampleForum", "ExForum" -> "forum.example.com"
   - "YouTube" -> "youtube.com"
   - "Stack Overflow" -> "stackoverflow.com"
   - "HackerNews", "HN" -> "news.ycombinator.com"
   - No site mentioned -> null

3. **quoted_phrase**: If user wants a SPECIFIC article/thread title (in quotes), preserve it exactly. Otherwise null.

4. **context_keywords**: If conversation context is provided AND relevant to current query, add connecting keywords. Otherwise empty array.

## Examples

**Query:** "go to forum.example.com and tell me what the popular threads are today"
```json
{"keywords": ["popular", "threads", "today"], "site": "forum.example.com", "quoted_phrase": null, "context_keywords": []}
```

**Query:** "can you tell me about jessika aro"
**Context:** Prior turn about Russian disinformation campaigns
```json
{"keywords": ["Jessikka", "Aro"], "site": null, "quoted_phrase": null, "context_keywords": ["journalist", "Russian", "disinformation"]}
```

**Query:** 'find the "Best glass scraper thoughts" thread on ExForum'
```json
{"keywords": [], "site": "forum.example.com", "quoted_phrase": "Best glass scraper thoughts", "context_keywords": []}
```

**Query:** "what's a good recipe for chocolate chip cookies"
```json
{"keywords": ["chocolate", "chip", "cookies", "recipe"], "site": null, "quoted_phrase": null, "context_keywords": []}
```

**Query:** "how do I fix a leaky faucet"
```json
{"keywords": ["fix", "leaky", "faucet"], "site": null, "quoted_phrase": null, "context_keywords": []}
```

**Query:** "what's the cheapest laptop with nvidia gpu"
```json
{"keywords": ["cheapest", "laptop", "nvidia", "gpu", "reddit", "buying guide"], "site": null, "quoted_phrase": null, "context_keywords": []}
```

**Query:** "find me a budget gaming monitor under $300"
```json
{"keywords": ["budget", "gaming", "monitor", "under $300", "best", "recommendations"], "site": null, "quoted_phrase": null, "context_keywords": []}
```

## Important

- Output ONLY the JSON object, no explanation
- If unsure about site, use null (don't guess)
- Keep keywords concise but meaningful
- Only add context_keywords if prior context is DIRECTLY relevant
