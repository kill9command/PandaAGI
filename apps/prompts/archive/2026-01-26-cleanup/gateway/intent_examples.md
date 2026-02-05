# Intent Classification Examples

This file contains examples for query intent classification. The system can add new examples over time as it learns from user queries.

**Format:** Each example shows a query pattern and its correct classification.

---

## Self-Extension Intent

Queries asking to build, create, or teach new capabilities.

| Query Pattern | Intent | Reasoning |
|--------------|--------|-----------|
| "build a skill for X" | self_extension | Creating new skill |
| "create a tool that does X" | self_extension | Building new tool |
| "teach yourself to X" | self_extension | Learning new capability |
| "add support for X" | self_extension | Extending capabilities |
| "implement X capability" | self_extension | Adding new feature to self |
| "build a skill for generating Mermaid diagrams" | self_extension | Skill creation request |
| "create an MCP tool for..." | self_extension | Tool building |
| "learn how to do X and remember it" | self_extension | Self-improvement |

---

## Commerce Intent

Queries about buying, finding products, or price comparisons.

| Query Pattern | Intent | Content Type | Reasoning |
|--------------|--------|--------------|-----------|
| "find X for sale" | commerce | varies | Purchase intent |
| "cheapest X" | commerce | varies | Price-focused purchase |
| "where to buy X" | commerce | varies | Shopping query |
| "best X under $Y" | commerce | varies | Budget shopping |
| "find me a Syrian hamster for sale" | commerce | pets | Live animal purchase |
| "cheapest laptop with RTX" | commerce | electronics | Tech product |
| "hamster toys and accessories" | commerce | general | Pet supplies (NOT pets) |
| "buy a GPU" | commerce | electronics | Hardware purchase |

---

## Navigation Intent

Queries requesting to visit a specific website or URL. **Use this when user names a specific site they want to GO TO.**

| Query Pattern | Intent | intent_metadata | Reasoning |
|--------------|--------|-----------------|-----------|
| "go to X.com" | navigation | target_url: https://X.com | Direct site visit |
| "visit X website" | navigation | target_url: https://X.com | Direct site visit |
| "navigate to X" | navigation | target_url: https://X.com | Direct navigation |
| "take me to X.com" | navigation | target_url: https://X.com | Direct navigation |
| "check X.com" | navigation | target_url: https://X.com | Direct site visit |
| "open the X website" | navigation | target_url: https://X.com | Direct site visit |

### Navigation with Task (IMPORTANT)
When user says "go to X AND do Y", it's still `navigation` with a `goal`:

| Query Pattern | Intent | intent_metadata | Reasoning |
|--------------|--------|-----------------|-----------|
| "go to reef2reef.com and find popular threads" | navigation | target_url: https://reef2reef.com, goal: find popular threads | Site + task |
| "visit amazon and show me deals" | navigation | target_url: https://amazon.com, goal: show deals | Site + task |
| "go to reddit and tell me what's trending" | navigation | target_url: https://reddit.com, goal: find trending content | Site + task |
| "check newegg for RTX 4080 prices" | navigation | target_url: https://newegg.com, goal: find RTX 4080 prices | Site + task |
| "open petco.com and find hamster supplies" | navigation | target_url: https://petco.com, goal: find hamster supplies | Site + task |

**Key rule:** If user mentions a specific site AND a task, use `navigation` with both `target_url` and `goal`. Do NOT use `informational`.

---

## Site Search Intent

Queries to search FOR something WITHIN a specific named site (but user doesn't have a direct URL).

| Query Pattern | Intent | intent_metadata | Reasoning |
|--------------|--------|-----------------|-----------|
| "search X on amazon" | site_search | site_name: amazon.com, search_term: X | Site-specific search |
| "find X on reddit" | site_search | site_name: reddit.com, search_term: X | Site-specific search |
| "look for X on ebay" | site_search | site_name: ebay.com, search_term: X | Site-specific search |
| "what does newegg have for X" | site_search | site_name: newegg.com, search_term: X | Site product query |
| "search reef2reef for protein skimmers" | site_search | site_name: reef2reef.com, search_term: protein skimmers | Forum search |
| "find hamster threads on reddit" | site_search | site_name: reddit.com, search_term: hamster threads | Forum search |

### Navigation vs Site Search

| Query | Intent | Why |
|-------|--------|-----|
| "go to amazon.com" | navigation | User wants to GO there |
| "search amazon for laptops" | site_search | User wants to SEARCH within |
| "visit reef2reef.com and find popular threads" | navigation | User wants to GO + do task |
| "find popular threads on reef2reef" | site_search | User wants to SEARCH within |
| "take me to reddit" | navigation | User wants to GO there |
| "what's on reddit about hamsters" | site_search | User wants to SEARCH within |

---

## Informational Intent

General research and learning queries.

| Query Pattern | Intent | Reasoning |
|--------------|--------|-----------|
| "what is X" | informational | Definition request |
| "how does X work" | informational | Explanation request |
| "explain X" | informational | Learning query |
| "research X" | informational | Research request |
| "learn about X" | informational | Educational query |
| "tell me about X" | informational | Information request |

---

## Greeting Intent

Small talk, thanks, and social queries.

| Query Pattern | Intent | Reasoning |
|--------------|--------|-----------|
| "hello" | greeting | Greeting |
| "hi there" | greeting | Greeting |
| "thanks" | greeting | Gratitude |
| "thank you for your help" | greeting | Gratitude |
| "how are you" | greeting | Social |

---

## Preference Intent

User stating preferences or constraints.

| Query Pattern | Intent | Reasoning |
|--------------|--------|-----------|
| "my budget is $X" | preference | Budget constraint |
| "I prefer X" | preference | Preference statement |
| "I like X better" | preference | Preference statement |
| "I need X" | preference | Requirement statement |

---

## Recall Intent

Queries about previous findings or memory.

| Query Pattern | Intent | Reasoning |
|--------------|--------|-----------|
| "what did you find" | recall | Previous findings |
| "show me what you found" | recall | Previous findings |
| "remember when we discussed X" | recall | Memory lookup |
| "what was that X we talked about" | recall | Memory lookup |

---

## Code Mode Intents

### Edit Intent
| Query Pattern | Intent | Mode | Reasoning |
|--------------|--------|------|-----------|
| "fix the bug in X" | edit | code | Bug fix |
| "update the function" | edit | code | Modification |
| "change X to Y" | edit | code | Modification |

### Create Intent
| Query Pattern | Intent | Mode | Reasoning |
|--------------|--------|------|-----------|
| "create a new X" | create | code | New file/component |
| "add a new test file" | create | code | New file |
| "write a component for X" | create | code | New component |

### Git Intent
| Query Pattern | Intent | Mode | Reasoning |
|--------------|--------|------|-----------|
| "commit these changes" | git | code | Git operation |
| "push to main" | git | code | Git operation |
| "create a branch for X" | git | code | Git operation |

### Test Intent
| Query Pattern | Intent | Mode | Reasoning |
|--------------|--------|------|-----------|
| "run the tests" | test | code | Test execution |
| "check if tests pass" | test | code | Test execution |
| "test the auth module" | test | code | Test execution |

### Refactor Intent
| Query Pattern | Intent | Mode | Reasoning |
|--------------|--------|------|-----------|
| "refactor X to use Y" | refactor | code | Code restructure |
| "clean up this code" | refactor | code | Code cleanup |
| "restructure the X module" | refactor | code | Code restructure |

---

## Disambiguation Notes

### Pets vs General
- "buy a hamster" → pets (live animal)
- "buy hamster food" → general (pet supplies)
- "find a dog" → pets (live animal)
- "dog toys" → general (pet supplies)

### Self-Extension vs Informational
- "learn about X" → informational (just learning)
- "learn how to X and remember it" → self_extension (building capability)
- "build a skill for X" → self_extension (creating new skill)
- "what is Mermaid.js" → informational
- "build a Mermaid diagram skill" → self_extension

### Navigation vs Site Search vs Informational

**Navigation** (user names a site and wants to GO THERE):
- "go to amazon.com" → navigation
- "visit reef2reef.com and find popular threads" → navigation (site + task)
- "take me to reddit" → navigation
- "check newegg for deals" → navigation (site + task)

**Site Search** (user names a site and wants to SEARCH WITHIN it):
- "search amazon for laptops" → site_search
- "find X on reddit" → site_search
- "what does reef2reef say about protein skimmers" → site_search

**Informational** (NO specific site mentioned):
- "what are popular aquarium forums" → informational
- "find information about hamster care" → informational
- "research laptop prices" → informational

**CRITICAL:** If the query mentions a specific site (domain name), it's either `navigation` or `site_search`, NEVER `informational`.

---

## Adding New Examples

When adding new examples:
1. Find the appropriate intent section
2. Add the query pattern, intent, and brief reasoning
3. If creating a new intent type, add a new section with header

The system will use these examples to improve classification accuracy over time.
