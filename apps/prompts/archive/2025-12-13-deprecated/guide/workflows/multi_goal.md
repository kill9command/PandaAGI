# Multi-Goal Query Detection

## 🎯 Detecting Multi-Goal Queries (CRITICAL)

**BEFORE creating any ticket, check if the user is asking for MULTIPLE distinct things.**

### Detection Patterns

- User explicitly says "AND": "find X AND Y AND Z"
- User lists multiple items: "find breeders, supplies, and care guides"
- User asks compound question: "what food do they need and what cage should I get?"

### When You Detect Multi-Goal Queries

**1. Identify each distinct goal:**
- Goal 1: "find hamster breeders"
- Goal 2: "find hamster supplies"
- Goal 3: "find care guides"

**2. Create SEPARATE subtasks for each goal:**
```json
{
  "_type": "TICKET",
  "goal": "Find Syrian hamster breeders AND supplies AND care guides",
  "subtasks": [
    {"kind": "research", "q": "Syrian hamster breeder near me", "why": "find breeders"},
    {"kind": "research", "q": "Syrian hamster supplies cage food", "why": "find supplies"},
    {"kind": "research", "q": "Syrian hamster care guide", "why": "find care information"}
  ]
}
```

**3. Verify ALL goals in capsule:**
- After receiving capsule, check if results cover ALL subtasks
- If only partial: note missing goals in answer
- Example: "I found breeders and care guides, but didn't find specific supplies listings"

### Intent-Specific Subtasks

Each subtask needs appropriate query refinement:
- **Breeders**: Add "breeder", "available", exclude "-book", "-guide", "-cage"
- **Supplies**: Add "for sale", "buy", exclude "-breeder", "-adoption"
- **Care info**: Add "guide", "how to", "care", exclude "-for sale", "-buy"

### Example Multi-Goal Ticket

```json
{
  "_type": "TICKET",
  "analysis": "User wants three distinct things: breeders, supplies, and care guides",
  "reflection": {
    "plan": "Create three separate research queries with intent-specific filters",
    "assumptions": ["Each goal needs different search strategy", "User wants all three"],
    "risks": ["May get mixed results if queries aren't specific enough"],
    "success_criteria": "At least 2 results per goal"
  },
  "goal": "Find Syrian hamster breeders AND supplies AND care guides",
  "micro_plan": [
    "Search for breeders with breeder-specific filters",
    "Search for supplies with shopping filters",
    "Search for care guides with informational filters"
  ],
  "subtasks": [
    {"kind": "research", "q": "Syrian hamster breeder near me available", "why": "find live animal breeders", "negative_keywords": ["-book", "-guide", "-cage"]},
    {"kind": "research", "q": "Syrian hamster cage food supplies for sale", "why": "find pet supplies", "negative_keywords": ["-breeder", "-adoption"]},
    {"kind": "research", "q": "Syrian hamster care guide how to", "why": "find care information", "negative_keywords": ["-for sale", "-buy"]}
  ]
}
```
