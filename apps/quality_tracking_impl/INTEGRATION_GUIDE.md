# Quality Tracking System - Integration Guide

## Quick Start

This guide walks you through integrating the quality tracking system into Pandora to prevent toxic feedback loops and cache pollution.

**Architecture Note:** Pandora uses a **single-model multi-role reflection system**. One LLM plays multiple roles (Guide → Coordinator → Context Manager) through reflection cycles. Quality tracking enables the model to learn across all roles and improve over time.

## Files Created

```
project_build_instructions/quality_tracking_impl/
├── claim_quality.py              # Claim scoring logic
├── satisfaction_detector.py      # User satisfaction detection
├── context_filter.py             # Context injection filtering
├── migrate_claims_db.sql         # Database schema updates
├── test_quality_system.py        # Integration tests
└── INTEGRATION_GUIDE.md          # This file
```

## Integration Steps

### Phase 1: Database Migration (5 minutes)

1. **Backup existing claims database:**
   ```bash
   cp panda_system_docs/shared_state/claims.db \
      panda_system_docs/shared_state/claims.db.backup
   ```

2. **Run migration:**
   ```bash
   sqlite3 panda_system_docs/shared_state/claims.db < \
      project_build_instructions/quality_tracking_impl/migrate_claims_db.sql
   ```

3. **Verify migration:**
   ```bash
   sqlite3 panda_system_docs/shared_state/claims.db \
      "SELECT COUNT(*) as total, AVG(quality_score) as avg_quality FROM claims;"
   ```

### Phase 2: Orchestrator - Claim Quality Scoring (15 minutes)

1. **Copy claim quality module:**
   ```bash
   cp project_build_instructions/quality_tracking_impl/claim_quality.py \
      orchestrator/claim_quality.py
   ```

2. **Integrate into context_builder.py:**

   **File:** `orchestrator/context_builder.py`

   **Around line 10 (imports):**
   ```python
   from orchestrator.claim_quality import ClaimQualityScorer
   ```

   **Around line 368 (where claims are created):**
   ```python
   # OLD CODE (approximate):
   claim_record = {
       "claim_text": claim_text,
       "matched_intent": matched_intent,
       # ... other fields
   }

   # NEW CODE:
   quality_scorer = ClaimQualityScorer()

   # Score the claim
   claim_quality = quality_scorer.score_claim(
       query_intent=matched_intent,
       result_type=tool_metadata.get("result_type", "unknown"),
       tool_status=tool_metadata.get("status", "success"),
       tool_metadata=tool_metadata,
       claim_specificity=0.7,  # Adjust based on claim text analysis
       source_count=len(sources) if sources else 1
   )

   # Calculate TTL
   ttl_hours = quality_scorer.calculate_claim_ttl(
       claim_quality["overall_score"]
   )

   claim_record = {
       "claim_text": claim_text,
       "matched_intent": matched_intent,
       "result_type": tool_metadata.get("result_type"),
       "intent_alignment": claim_quality["intent_alignment"],
       "evidence_strength": claim_quality["evidence_strength"],
       "quality_score": claim_quality["overall_score"],
       "ttl_hours": ttl_hours,
       "created_at": datetime.utcnow().isoformat(),
       "expires_at": (datetime.utcnow() + timedelta(hours=ttl_hours)).isoformat(),
       # ... other fields
   }
   ```

3. **Update tool execution to return metadata:**

   Each tool in `orchestrator/*_mcp.py` should return metadata including:
   - `status`: "success" | "error" | "empty" | "partial"
   - `result_type`: "shopping_listings" | "care_guides" | "product_specs" | etc.
   - `data_quality`: Dict with structured, completeness, source_confidence

   **Example for commerce_mcp.py:**
   ```python
   def commerce_search(query: str, **kwargs):
       # ... existing code ...

       results = api_call(query)

       # Detect result type
       result_type = "shopping_listings" if any("price" in r for r in results) else "unknown"

       # Score data quality
       data_quality = {
           "structured": 0.9 if all(required_fields_present(r) for r in results) else 0.5,
           "completeness": len(results) / 10.0,  # Normalize by expected count
           "source_confidence": 0.8  # Based on API reliability
       }

       return {
           "results": results,
           "metadata": {
               "status": "success" if results else "empty",
               "result_type": result_type,
               "data_quality": data_quality
           }
       }
   ```

### Phase 3: Gateway - Satisfaction Detection (20 minutes)

1. **Copy satisfaction detector:**
   ```bash
   cp project_build_instructions/quality_tracking_impl/satisfaction_detector.py \
      project_build_instructions/gateway/response_quality.py
   ```

2. **Integrate into gateway app.py:**

   **File:** `project_build_instructions/gateway/app.py`

   **Around imports:**
   ```python
   from project_build_instructions.gateway.response_quality import UserSatisfactionDetector
   ```

   **Around the main process loop (after Guide response, before returning):**
   ```python
   # Track session quality
   session_quality_tracker = getattr(request.state, 'session_quality', {})

   # Store turn metadata
   current_turn = {
       "turn_id": len(session_quality_tracker.get("turns", [])) + 1,
       "user_query": user_message,
       "intent": matched_intent,
       "response_quality": guide_response.get("predicted_quality", 0.5),
       "claims_used": [c["claim_id"] for c in context_claims],
       "intent_fulfilled": guide_response.get("intent_fulfilled", True)
   }

   # Detect satisfaction from previous turn (if exists)
   if session_quality_tracker.get("turns"):
       prev_turn = session_quality_tracker["turns"][-1]
       detector = UserSatisfactionDetector()
       satisfaction = detector.analyze_follow_up(
           original_query=prev_turn["user_query"],
           original_intent=prev_turn["intent"],
           response="",  # We don't need full response text
           follow_up_query=user_message,
           follow_up_intent=matched_intent
       )

       # Update previous turn with satisfaction score
       prev_turn["user_satisfaction"] = (
           0.9 if satisfaction["satisfied"] == True
           else 0.1 if satisfaction["satisfied"] == False
           else 0.5
       )

       # Propagate feedback to claims
       if prev_turn["user_satisfaction"] < 0.4:
           # User was dissatisfied - update claim quality
           for claim_id in prev_turn["claims_used"]:
               update_claim_quality_from_feedback(
                   claim_id,
                   prev_turn["user_satisfaction"]
               )

   # Store turn in session
   if "turns" not in session_quality_tracker:
       session_quality_tracker["turns"] = []
   session_quality_tracker["turns"].append(current_turn)
   request.state.session_quality = session_quality_tracker
   ```

3. **Add claim quality update function:**
   ```python
   def update_claim_quality_from_feedback(claim_id: str, satisfaction_score: float):
       """Update claim quality based on user feedback."""
       # Connect to claims DB
       conn = sqlite3.connect("panda_system_docs/shared_state/claims.db")
       cursor = conn.cursor()

       # Update claim
       cursor.execute("""
           UPDATE claims
           SET user_feedback_score = ?,
               times_reused = times_reused + 1,
               times_helpful = times_helpful + CASE WHEN ? > 0.6 THEN 1 ELSE 0 END,
               last_used_at = ?
           WHERE claim_id = ?
       """, (satisfaction_score, satisfaction_score, datetime.utcnow().isoformat(), claim_id))

       # If quality drops too low, mark for deprecation
       cursor.execute("""
           UPDATE claims
           SET deprecated = 1,
               deprecation_reason = 'Low user satisfaction'
           WHERE claim_id = ? AND quality_score < 0.3
       """, (claim_id,))

       conn.commit()
       conn.close()
   ```

### Phase 4: Gateway - Context Filtering (20 minutes)

1. **Copy context filter:**
   ```bash
   cp project_build_instructions/quality_tracking_impl/context_filter.py \
      project_build_instructions/gateway/context_filter.py
   ```

2. **Replace context injection logic:**

   **File:** `project_build_instructions/gateway/app.py`

   **Around imports:**
   ```python
   from project_build_instructions.gateway.context_filter import ContextInjectionFilter
   ```

   **Around L2067-2082 (context injection):**

   **BEFORE (dangerous):**
   ```python
   # OLD CODE - injects full Q&A pairs
   context_items.append({
       "type": "learned_pattern",
       "content": f"Question: {prev_query}\nAnswer: {prev_response}"
   })
   ```

   **AFTER (safe):**
   ```python
   # NEW CODE - use context filter
   context_filter = ContextInjectionFilter(quality_threshold=0.6)

   # Fetch historical patterns with quality metadata
   historical_patterns = fetch_historical_patterns(session_id)

   # Filter and convert to metadata-only
   safe_patterns = context_filter.filter_historical_patterns(
       historical_patterns,
       current_intent=matched_intent,
       max_patterns=3
   )

   # Generate safe context block
   if safe_patterns:
       context_block = context_filter.create_context_injection_block(
           historical_patterns,
           matched_intent,
           max_patterns=3
       )
       context_items.append({
           "type": "historical_context",
           "content": context_block
       })
   ```

3. **Update cache filtering (L2112-2115):**

   **BEFORE:**
   ```python
   # OLD CODE - NULL intents bypass filter
   if claim.matched_intent not in intent_domains:
       continue
   ```

   **AFTER:**
   ```python
   # NEW CODE - strict filtering
   # Rule 1: Require matched_intent
   if not claim.matched_intent:
       continue  # Skip claims without intent metadata

   # Rule 2: Intent must match current domain
   if claim.matched_intent not in intent_domains:
       continue

   # Rule 3: Quality threshold
   if claim.quality_score < 0.5:
       continue  # Skip low-quality claims

   # Rule 4: Result type must align with intent
   context_filter = ContextInjectionFilter()
   should_use, reason = context_filter.should_inject_historical_pattern(
       {
           "intent": claim.matched_intent,
           "result_type": claim.result_type,
           "quality_score": claim.quality_score,
           "intent_fulfilled": True  # Assume yes if in cache
       },
       current_intent=matched_intent
   )
   if not should_use:
       logger.debug(f"Skipping claim {claim.id}: {reason}")
       continue
   ```

### Phase 5: Testing (10 minutes)

1. **Run unit tests:**
   ```bash
   cd project_build_instructions/quality_tracking_impl
   python test_quality_system.py
   ```

2. **Expected output:**
   - ✓ Scenario 1: Success path tracked and reinforced
   - ✓ Scenario 2: Failure path detected and blocked from reuse
   - ✓ Scenario 3: Session quality degradation detected
   - ✓ Scenario 4: Context injection filtered correctly

3. **Test with real query:**
   ```bash
   curl -X POST http://localhost:9000/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{
       "messages": [{"role": "user", "content": "find syrian hamsters for sale online"}],
       "mode": "chat"
     }'
   ```

   **Expected behavior:**
   - Should use `commerce.search` tool
   - Should return shopping listings (NOT care guides)
   - Quality score should be high (>0.7)
   - Follow-up queries should work correctly

### Phase 6: Monitoring (Ongoing)

1. **Check claim quality distribution:**
   ```bash
   sqlite3 panda_system_docs/shared_state/claims.db <<EOF
   SELECT
       CASE
           WHEN quality_score >= 0.7 THEN 'High (0.7-1.0)'
           WHEN quality_score >= 0.4 THEN 'Medium (0.4-0.7)'
           ELSE 'Low (0.0-0.4)'
       END as quality_tier,
       COUNT(*) as count,
       AVG(quality_score) as avg_score,
       AVG(ttl_hours) as avg_ttl_hours
   FROM claims
   WHERE deprecated = 0
   GROUP BY quality_tier;
   EOF
   ```

2. **Monitor deprecated claims:**
   ```bash
   sqlite3 panda_system_docs/shared_state/claims.db \
     "SELECT COUNT(*), deprecation_reason FROM claims WHERE deprecated = 1 GROUP BY deprecation_reason;"
   ```

3. **Check intent alignment:**
   ```bash
   sqlite3 panda_system_docs/shared_state/claims.db \
     "SELECT matched_intent, result_type, AVG(intent_alignment) as avg_alignment, COUNT(*) as count FROM claims GROUP BY matched_intent, result_type ORDER BY avg_alignment;"
   ```

## Rollback Plan

If issues arise, you can rollback:

1. **Restore database:**
   ```bash
   cp panda_system_docs/shared_state/claims.db.backup \
      panda_system_docs/shared_state/claims.db
   ```

2. **Revert code changes:**
   ```bash
   git checkout orchestrator/context_builder.py
   git checkout project_build_instructions/gateway/app.py
   ```

3. **Remove new modules:**
   ```bash
   rm orchestrator/claim_quality.py
   rm project_build_instructions/gateway/response_quality.py
   rm project_build_instructions/gateway/context_filter.py
   ```

## Performance Considerations

- **Database indexes:** Migration creates indexes on quality_score, matched_intent, result_type
- **Context filtering:** Adds ~5ms per request (negligible)
- **Claim scoring:** Adds ~2ms per claim creation (one-time cost)
- **Satisfaction detection:** Adds ~3ms per turn (regex matching)

**Total overhead:** ~10ms per request (acceptable)

## Success Criteria

After integration, you should see:

- ✓ Cache pollution incidents: 0 (down from ~5/week)
- ✓ Intent alignment: >85% of claims have alignment >0.7
- ✓ Quality distribution: >70% of active claims with quality >0.6
- ✓ User satisfaction: Detectable from conversation flow
- ✓ Automatic cleanup: Low-quality claims deprecated within 24-48 hours

## Troubleshooting

### Issue: Claims still have NULL intent

**Solution:** The migration marks NULL intent claims as deprecated. New claims should always have intent. Check that `matched_intent` is being passed to claim creation.

### Issue: Quality scores all 0.5

**Solution:** Tool metadata not being passed correctly. Verify that tools are returning `result_type` and `data_quality` in their metadata.

### Issue: Context filter too aggressive

**Solution:** Lower the quality threshold from 0.6 to 0.5:
```python
context_filter = ContextInjectionFilter(quality_threshold=0.5)
```

### Issue: Satisfaction detection not working

**Solution:** Check that follow-up queries are being compared against previous turn. Verify session state persistence.

## Next Steps

After successful integration:

1. **Phase 7: Coordinator Learning** (Week 2)
   - Implement plan_effectiveness.py
   - Track tool selection success rates
   - Update Coordinator prompt with learned preferences

2. **Phase 8: Guide Prompt Enhancement** (Week 2)
   - Add response quality self-assessment
   - Teach Guide when to use cache vs fresh search
   - Add intent fulfillment tracking

3. **Phase 9: Dashboard** (Week 3)
   - Create admin endpoint for quality metrics
   - Visualize quality trends over time
   - Alert on quality degradation

## Support

For questions or issues:
1. Check test output: `python test_quality_system.py`
2. Review logs: `tail -f gateway.log orchestrator.log`
3. Inspect claims DB: `sqlite3 panda_system_docs/shared_state/claims.db`
4. Consult design docs: `project_build_instructions/quality-tracking-system.md`
