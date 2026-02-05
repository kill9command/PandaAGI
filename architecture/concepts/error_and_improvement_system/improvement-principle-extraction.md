# Improvement Principle Extraction

**Version:** 2.0
**Updated:** 2026-02-03

---

## 1. Purpose

When a response goes through revision (REVISE → APPROVE), the system extracts a transferable principle explaining **why the revision was better**. These principles are stored in memory and retrieved for future similar queries.

This is how the system learns from its own mistakes without code changes.

---

## 2. Trigger

Principle extraction triggers when:

1. Validation decides APPROVE
2. At least one revision happened before approval
3. Revision hints exist (the validator explained what needed fixing)

If the response was approved on the first attempt, there's nothing to learn — no extraction occurs.

---

## 3. Extraction Flow

```
Iteration 1: Synthesis → Validation (REVISE, hints: "use table format")
                              ↓
                    Store: original_response, revision_hints
                              ↓
Iteration 2: Synthesis (with hints) → Validation (APPROVE)
                              ↓
                    Extract principle (async, non-blocking)
                              ↓
                    Store in memory
                              ↓
Future queries: Context Gatherer finds principle → includes in §2
```

Extraction runs asynchronously — it doesn't add latency to the user's response.

---

## 4. What a Principle Contains

| Field | Purpose |
|-------|---------|
| **Category** | Type of improvement (formatting, completeness, accuracy, tone) |
| **Trigger pattern** | What kind of query this principle applies to |
| **Description** | What to do differently and why it works |
| **Source turn** | Where this was learned |
| **Confidence** | Starting confidence, adjustable over time based on usage |

---

## 5. Retrieval

Principles are retrieved like any other memory. The Context Gatherer searches all memory paths during Phase 2 — semantic similarity matches the current query to principle trigger patterns. Relevant principles appear in §2 alongside other context.

No special retrieval logic is needed. The existing memory search handles it.

---

## 6. Example

**Query:** "find the cheapest gaming laptops"

**Original response** (got REVISE):
> The MSI Thin costs $749.99 at Amazon. The ASUS TUF Dash F15 costs $799.99 at Best Buy. The Lenovo IdeaPad Gaming 3 costs $649.99...

**Revision hints:** "Use table format for price comparisons"

**Revised response** (got APPROVE):

| Laptop | Price | Retailer |
|--------|-------|----------|
| Lenovo IdeaPad Gaming 3 | $649.99 | Amazon |
| MSI Thin | $749.99 | Amazon |
| ASUS TUF Dash F15 | $799.99 | Best Buy |

**Extracted principle:**
- Category: `formatting`
- Trigger: `price comparison queries`
- Description: "When comparing multiple products by price, use a table format with Product, Price, and Retailer columns for easy scanning."

**Future query:** "compare prices for mechanical keyboards"

Context Gatherer finds this principle via semantic match ("price comparison") and includes it in §2. Synthesis sees the principle and uses table format from the start — no revision needed.

---

## 7. Related Documents

- Validation: `architecture/main-system-patterns/phase7-validation.md`
- Confidence system: `architecture/concepts/confidence_system/UNIVERSAL_CONFIDENCE_SYSTEM.md`
- Error handling: `architecture/concepts/error_and_improvement_system/ERROR_HANDLING.md`

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-24 | Initial specification |
| 2.0 | 2026-02-03 | Distilled to pure concept. Removed Python code, file paths, token budgets, truncation specifics, and async implementation tradeoffs. |

---

**Last Updated:** 2026-02-03
