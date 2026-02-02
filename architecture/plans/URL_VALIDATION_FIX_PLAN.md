# URL Validation Fix Plan

**Date:** 2026-01-26
**Issue:** Corrupted URLs passing validation and reaching users
**Root Cause:** LLM-based validation unreliable for pattern matching

---

## Problem Summary

Turn 112 produced a response with a corrupted URL:
```
https://www.newegg.com/msi-thin-gf63/p/NB7Z0000000000000000000000...
```

The validation phase has explicit rules to catch this pattern (in `apps/prompts/validator/core.md` lines 363-372):
```markdown
**Fake URL patterns (FAIL even if in evidence):**
- Placeholder IDs: `/p/NB7Z0000000000000000`, `/product-123`, `/item/ABC123`
- All zeros or sequential: `/p/000000000`, `/id/123456789`
```

But the LLM marked `urls_verified: true` anyway.

---

## Investigation Findings

### What Works

| Component | Status | Evidence |
|-----------|--------|----------|
| Recipe system | ✅ | `load_recipe("validator")` loads correctly |
| Prompt loading | ✅ | `validator/core.md` is read (1550 tokens) |
| URL rules in prompt | ✅ | Lines 349-427 have detailed URL checks |
| DocPackBuilder | ✅ | Builds prompt correctly with context |
| Unified flow calls validator | ✅ | `_phase6_validation()` uses recipe |

### What Fails

| Component | Issue |
|-----------|-------|
| LLM pattern matching | Unreliable - marked garbage URL as "verified" |
| No programmatic backup | System trusts LLM completely for URL checks |

### Root Cause

The validator prompt has the right **rules** but wrong **procedure**:

1. **URL check is in "Additional Validation Checks" section** - Not in the mandatory numbered steps (Steps 1-8)
2. **No `check_details.urls_verified`** - The output schema shows details for 4 checks, but not URLs
3. **No "show your work" requirement** - LLM can output `urls_verified: true` without analysis
4. **`hallucinated_urls` field exists but isn't required** - Easy to skip

The LLM has the rules but isn't forced to follow the procedure.

### Why Prompt Improvement Is The Primary Fix

The CLAUDE.md principle states:
> "When an LLM makes a bad decision, the fix is ALWAYS better context/prompts, NOT programmatic workarounds."

The current prompt failure isn't because LLMs can't do pattern matching. It's because:

1. **URL check isn't mandatory** - It's in "Additional Checks", not Steps 1-8
2. **No output structure for URL analysis** - LLM can skip showing its work
3. **No explicit failure instruction** - Doesn't say "if fake URL, MUST return RETRY"

By making the prompt more explicit and requiring structured output, we make the LLM reliable. The programmatic check is defense-in-depth, not a replacement.

---

## Architecture Context

**Relevant Spec:** `architecture/main-system-patterns/phase6-validation.md`

The validation phase is designed as an LLM-based quality gate. However, the spec doesn't prohibit programmatic checks - it just describes the LLM's role.

**Quote from architecture:**
> Phase 6 validates response quality before delivery. The validator checks claims, hallucinations, query relevance, and formatting.

Adding programmatic checks **enhances** the validation phase without conflicting with architecture.

---

## Fix Plan

### Fix 0: Improve Validator Prompt (Make LLM Reliable)

**File:** `apps/prompts/validator/core.md`

**Problem:** URL verification is in "Additional Validation Checks" (line 315+), not in the mandatory Steps 1-8. The LLM treats it as optional.

**Changes needed:**

#### Change 0a: Add URL Verification as Step 5.5 (Mandatory)

Insert after Step 5 (Hallucination Check), before Step 6:

```markdown
### Step 5.5: URL Verification (MANDATORY for commerce queries)

For EACH URL in the response (§5):

1. **List all URLs found:**
   ```
   URLs in response:
   - https://newegg.com/p/NB7Z0000000000...
   - https://amazon.com/dp/B0CK...
   ```

2. **Check each URL exists in evidence (§2 or §4):**
   ```
   URL 1: https://newegg.com/p/NB7Z0000000000...
   - Found in §2? NO
   - Found in §4? NO
   - Status: HALLUCINATED
   ```

3. **Check each URL for fake patterns:**
   - Repeated zeros: `/p/NB7Z0{15,}` → FAKE
   - Placeholder IDs: `/product-123` → FAKE
   - No product path: `https://newegg.com` alone → FAKE

4. **Decision:**
   - Any hallucinated URL → set `urls_verified: false`, add to `hallucinated_urls`
   - Any fake URL pattern → set `urls_verified: false`, decision = RETRY
   - All URLs valid → set `urls_verified: true`

**You MUST show your URL analysis in the output.**
```

#### Change 0b: Add `check_details.urls_verified` to Output Schema

Add to the check_details example (around line 49):

```json
"check_details": {
  ...existing checks...,
  "urls_verified": {
    "score": 0.0,
    "evidence": [],
    "issues": ["https://newegg.com/p/NB7Z000... - repeated zeros pattern (FAKE)"]
  }
}
```

#### Change 0c: Make `url_analysis` Required Field

Add to output schema:

```json
{
  ...existing fields...,
  "url_analysis": {
    "urls_found": ["list of all URLs in §5"],
    "urls_in_evidence": ["list of URLs that exist in §2 or §4"],
    "urls_hallucinated": ["list of URLs not in evidence"],
    "urls_fake_pattern": ["list of URLs matching fake patterns"],
    "analysis_notes": "Brief explanation of URL check results"
  }
}
```

#### Change 0d: Add Explicit Failure Instruction

Add after the fake URL patterns list:

```markdown
**CRITICAL:** If you find ANY URL matching these fake patterns, you MUST:
1. Set `urls_verified: false`
2. Set `decision: "RETRY"`
3. Add the URL to `url_analysis.urls_fake_pattern`
4. Add suggested_fix: "Evidence contains fake/placeholder URLs - re-research needed"

DO NOT approve a response with fake URLs, even if everything else looks good.
```

---

### Fix 1: Add Programmatic URL Health Check

**File:** `libs/core/url_health.py` (new)

**Purpose:** Single source of truth for URL validation. Detects:
- Repeated characters (e.g., `0000000000`)
- Placeholder patterns (e.g., `/p/NB7Z0{20,}`)
- Excessive length (>2000 chars)
- Malformed structure

**Why here:** `libs/core/` is shared utilities. URL health checking is needed by multiple components.

```python
# Key function signature
def check_url_health(url: str) -> URLHealthReport:
    """
    Returns:
        URLHealthReport with:
        - status: HEALTHY | MALFORMED | SUSPICIOUS
        - issues: List of specific problems
        - sanitized: Cleaned version if recoverable
    """
```

### Fix 2: Integrate Check into Phase 6 Validation

**File:** `libs/gateway/unified_flow.py`

**Location:** `_phase6_validation()` method, before LLM call

**Change:** Add programmatic URL check as pre-filter:

```python
async def _phase6_validation(self, ...):
    # NEW: Programmatic URL check before LLM
    url_issues = self._check_urls_programmatically(response)
    if url_issues:
        logger.warning(f"[UnifiedFlow] Programmatic URL check failed: {url_issues}")
        # Decide: auto-fix or RETRY?
        if self._can_sanitize_urls(response, url_issues):
            response = self._sanitize_urls(response)
            all_issues.append(f"Sanitized malformed URLs: {url_issues}")
        else:
            # Unrecoverable - need fresh research
            return ValidationResult(
                decision="RETRY",
                issues=url_issues,
                suggested_fixes=["Re-research needed - evidence contains malformed URLs"]
            )

    # Continue to LLM validation...
```

### Fix 3: Add URL Check to Validation Checklist Output

**File:** `libs/gateway/unified_flow.py`

**Location:** `_write_validation_section()` method

**Change:** Include programmatic URL check result in §6 output:

```markdown
**Validation Checklist:**
- [x] Claims match evidence
- [x] No hallucinations
- [x] Response addresses query
- [ ] Coherent formatting
- [x] URLs verified (programmatic)  <-- NEW: separate from LLM check
- [x] URLs verified (LLM)
- [x] Prices cross-checked
```

### Fix 4: Clean Up Corrupted Data (One-Time)

**Action:** Delete or fix turn 112's corrupted files

**Files affected:**
- `panda_system_docs/obsidian_memory/Users/henry/turns/turn_000112/response.md`
- `panda_system_docs/obsidian_memory/Users/henry/turns/turn_000112/context.md`

**Options:**
1. Delete entire turn (cleanest)
2. Manually fix URLs (preserves other data)

---

## Implementation Order

| Order | Fix | Effort | Impact |
|-------|-----|--------|--------|
| 1 | Fix 4: Clean corrupted data | 5 min | Immediate relief |
| 2 | **Fix 0: Improve validator prompt** | 20 min | Makes LLM reliable |
| 3 | Fix 1: Create url_health.py | 30 min | Programmatic backup |
| 4 | Fix 2: Integrate into validation | 30 min | Defense in depth |
| 5 | Fix 3: Update checklist output | 15 min | Better visibility |

**Note:** Fix 0 (prompt improvement) is the primary fix. Fix 1-2 (programmatic check) is defense in depth for when the LLM still fails.

---

## Detection & Notification (Your Request)

You asked for: "detect garbage, tell us about it, work together to correct"

### Detection
- Programmatic check runs on every response
- Logs warning when bad URLs found
- Records in §6 validation output

### Notification
- Warning in logs: `[UnifiedFlow] Programmatic URL check failed: ...`
- §6 shows: `URLs verified (programmatic): FAILED - [reasons]`
- Response includes: "Note: Some links may be unavailable"

### Correction Workflow
When bad URL detected:
1. **If sanitizable** → Auto-fix and continue (with note in §6)
2. **If unrecoverable + commerce query** → RETRY for fresh research
3. **If unrecoverable + info query** → Continue without links (user can search manually)

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `apps/prompts/validator/core.md` | **MODIFY** | Add Step 5.5, require url_analysis output |
| `libs/core/url_health.py` | CREATE | URL validation utility (backup) |
| `libs/core/__init__.py` | MODIFY | Export new module |
| `libs/gateway/unified_flow.py` | MODIFY | Add pre-check to validation |
| Turn 112 files | DELETE | Clean corrupted data |

---

## Testing Plan

1. **Unit test url_health.py:**
   - Test known-bad patterns (zeros, placeholders)
   - Test edge cases (long URLs, unusual chars)
   - Test good URLs aren't rejected

2. **Integration test:**
   - Create response with bad URL
   - Verify programmatic check catches it
   - Verify RETRY/sanitize behavior

3. **Regression test:**
   - Run existing test queries
   - Verify good responses still pass

---

## Why This Is Simple

This fix is simple because:

1. **Primary fix is prompt improvement** - Make the LLM do what it's supposed to do
2. **Programmatic check is backup** - Defense in depth, not replacement
3. **No architecture changes** - Enhances existing validation phase
4. **Clear separation** - LLM validates semantics, code validates patterns
5. **Graceful handling** - Sanitize when possible, RETRY when not

**The philosophy:**
- First, make the LLM reliable by improving the prompt (Fix 0)
- Then, add programmatic backup for the rare cases where it still fails (Fix 1-2)

The complex "5-layer self-healing" was over-engineered. This is the minimum effective fix.

---

## Success Criteria

After implementation:
- [ ] **LLM catches bad URLs** - Validator outputs `urls_verified: false` for fake patterns
- [ ] **LLM shows work** - `url_analysis` field populated with URL-by-URL check
- [ ] **Programmatic backup works** - Catches what LLM misses
- [ ] Turn 112's corrupted URL would be caught by EITHER check
- [ ] Bad URLs trigger RETRY or get sanitized (not passed to user)
- [ ] Logs show when either check catches issues
- [ ] §6 output shows both LLM and programmatic results
- [ ] Good URLs continue to pass validation
