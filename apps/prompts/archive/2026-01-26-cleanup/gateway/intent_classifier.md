# Intent Classifier

Classify user queries into intent types for routing.

## Task

Classify this query into one of: navigation, site_search, commerce, informational

QUERY: {query}

## Definitions

- **navigation**: User wants to go to a specific website URL (e.g., "go to amazon.com", "visit forum.example.com")
- **site_search**: User wants to search WITHIN a specific NAMED site (e.g., "find laptops on amazon", "search reddit for X")
  CRITICAL: Only use site_search if a SPECIFIC site is named! "find vendors" without a site = commerce, NOT site_search
- **commerce**: User wants to buy something, find vendors/sellers, or search for products across the web (e.g., "cheapest laptop", "where to buy hamster", "for sale", "find vendors", "search for breeders", "find sellers", "additional vendors")
  IMPORTANT: Queries about finding vendors/sellers/breeders without naming a specific site = commerce
- **informational**: User wants to learn/understand something (e.g., "what is X", "how does X work")

## Output Format

JSON only, no explanation:
```json
{{"intent": "navigation|site_search|commerce|informational", "target_url": "url if navigation", "site_name": "site if site_search", "search_term": "term if site_search", "goal": "what user wants to achieve"}}
```

## Examples

- "Syrian hamsters for sale" -> commerce (searching for sellers across the web)
- "find additional vendors for hamsters" -> commerce (no specific site named)
- "search amazon for laptops" -> site_search (specific site: amazon)
- "what is a Syrian hamster" -> informational
