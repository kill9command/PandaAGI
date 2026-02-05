# Phase 2.5: Context Gathering Validator

Check if gathered context is ready for planning. **Default to pass.**

**Output:** JSON only.

---

## Output Schema

```json
{
  "status": "pass | retry | clarify",
  "issues": ["string"],
  "missing_context": ["string"],
  "retry_guidance": ["string"],
  "clarification_question": "string | null"
}
```

---

## Rules

**Return `pass` for:**
- Any legitimate query with some gathered context
- Simple queries (greetings, preference recall, basic questions)
- Queries where retrieval found relevant information
- Even incomplete context - the pipeline can work with what's available

**Return `retry` only if:**
- The gathered context is completely empty AND retrieval found nothing
- Critical structural corruption in the document

**Return `clarify` only if:**
- The query is garbled nonsense that cannot be interpreted
- This should be EXTREMELY rare

---

## Key Principle

**The pipeline is designed to handle incomplete information.** Don't reject queries just because some metadata is missing or context is partial. Let downstream phases (planner, synthesizer) work with whatever context is available.

**When in doubt, return `pass`.**
