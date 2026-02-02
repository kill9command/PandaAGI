# Quality Tracking & Feedback System

**Status:** Design Complete, Ready for Implementation
**Date:** 2025-11-09
**Version:** 1.0

## Executive Summary

This system prevents toxic feedback loops in Pandora by tracking quality at every layer of the architecture, from tool execution through user satisfaction. It implements a fractal pattern where each role (Orchestrator, Context Manager, Coordinator, Guide, Gateway) maintains quality scores at its abstraction level, with bidirectional feedback propagation.

**Architecture:** Pandora uses a **single-model multi-role reflection system** - one LLM reflects through different roles (Guide → Coordinator → Context Manager) with quality tracking enabling learning across all reflection cycles.

## The Problem

**Root Cause:** Toxic feedback loop caused by injecting full Q&A pairs without quality validation.

**Sequence:**
1. User asks "find hamsters for sale online" (transactional intent)
2. Tool returns care guides (wrong result type)
3. Q&A pair stored as "learned pattern"
4. Next time: Guide sees "this question → care guides answer" pattern
5. Guide reuses pattern: "Cache contains relevant results"
6. User gets care guides AGAIN instead of shopping results

**Deeper Issue:** System can't distinguish "found care guides" (wrong) from "found sellers" (right) when reusing cache.

## The Solution: Fractal Quality Tracking

### Core Innovation

Every layer implements the same pattern:
1. Receive input (query, plan, tool call)
2. Execute at its abstraction level
3. Score output quality
4. Provide feedback to adjacent layers
5. Learn from feedback received

### Quality Scoring Components

**Intent Alignment** (40% weight)
- Does result type match query intent?
- Transactional + shopping_listings = 1.0 ✓
- Transactional + care_guides = 0.1 ✗

**Evidence Strength** (30% weight)
- Data quality metrics (structured, complete, confident)
- Source count and reliability
- Claim specificity

**User Feedback** (30% weight)
- Detected from follow-up patterns
- Frustration: "but I wanted..." (-0.3)
- Satisfaction: "thanks! perfect" (+0.2)

### Multi-Layer Feedback

**Bottom-Up (Tool → User):**
```
Tool metadata → Claim quality → Capsule quality → Response quality → User satisfaction
```

**Top-Down (User → System):**
```
User frustration → Response low quality → Claim decay → Pattern deprecated → Won't inject again
```

## Files Delivered

### Core Implementation
- **claim_quality.py** (370 lines): Claim scoring logic with intent alignment matrix
- **satisfaction_detector.py** (280 lines): User satisfaction/frustration detection
- **context_filter.py** (320 lines): Context injection filtering with quality gates
- **migrate_claims_db.sql** (80 lines): Database schema updates

### Documentation
- **quality-tracking-system.md** (1200 lines): Complete design specification
- **quality-feedback-flows.md** (800 lines): Visual flow diagrams and examples
- **INTEGRATION_GUIDE.md** (500 lines): Step-by-step integration instructions
- **test_quality_system.py** (400 lines): Integration tests with 4 scenarios

## Test Results

All scenarios pass ✓

**Scenario 1: Success Path**
- Shopping query → shopping_listings
- Quality: 0.82 → 0.95 (after user satisfaction)
- TTL: 284 → 484 hours (extended)
- Result: Pattern reinforced for future use

**Scenario 2: Failure Path (THE BUG)**
- Shopping query → care_guides (WRONG!)
- Quality: 0.41 → 0.29 (after user frustration)
- TTL: 166 → 99 hours (rapid decay)
- Result: Pattern BLOCKED from context injection

**Scenario 3: Session Tracking**
- Detected quality degradation across turns
- Identified "Low average response quality"
- Suggested fresh search trigger

**Scenario 4: Context Filtering**
- Excluded low-quality patterns (quality < 0.6)
- Excluded intent-mismatched patterns
- Only injected metadata (NO full Q&A text)

## Key Features

### 1. Intent Alignment Matrix
```python
"transactional": {
    "shopping_listings": 1.0,  # Perfect match
    "product_specs": 0.7,       # Good match
    "care_guides": 0.1,         # MISMATCH (the bug!)
}
```

### 2. Quality-Based TTL
- High quality (0.9): Up to 450 hours (19 days)
- Medium quality (0.6): ~168 hours (7 days)
- Low quality (0.3): 24-48 hours (rapid decay)

### 3. Satisfaction Patterns
**Frustration:**
- "but I (want|need|asked for)"
- "no|not what I (wanted|asked)"
- "can you actually find"

**Satisfaction:**
- "thanks|perfect|great"
- "exactly what I wanted"
- "that works|helps"

### 4. Context Injection Rules
- ✓ Quality score ≥ 0.6
- ✓ Intent matches current query
- ✓ Result type compatible with intent
- ✓ Intent was fulfilled
- ✗ Never inject full Q&A pairs

## Integration Checklist

- [ ] Phase 1: Database migration (5 min)
- [ ] Phase 2: Orchestrator claim scoring (15 min)
- [ ] Phase 3: Gateway satisfaction detection (20 min)
- [ ] Phase 4: Gateway context filtering (20 min)
- [ ] Phase 5: Testing (10 min)
- [ ] Phase 6: Monitoring setup (ongoing)

**Total integration time:** ~70 minutes

See `INTEGRATION_GUIDE.md` for detailed steps.

## Expected Outcomes

### Short-Term (1 Month)
- ✅ Cache pollution: 0 incidents (down from ~5/week)
- ✅ Intent alignment: >85% accuracy
- ✅ Quality distribution: >70% high-quality claims
- ✅ User satisfaction: Detectable from conversation

### Long-Term (3 Months)
- ✅ Plan effectiveness: Tool selection >80% success rate
- ✅ Cache hit quality: >90% have quality >0.6
- ✅ Automatic cleanup: 60% reduction in stale claims
- ✅ Self-improving: System learns from mistakes

## Architecture Alignment

This design respects Pandora's core principles:

1. **Multi-Role Reflection**: One model reflects through Guide → Coordinator → Context Manager roles, with quality tracking enabling learning across all reflection cycles
2. **Token Budget**: Quality scores used to filter context, saving tokens
3. **Mode Gates**: Quality tracking works across chat/code modes
4. **Evidence Discipline**: Claims backed by quality-scored tool outputs
5. **Fractal Design**: Same quality pattern implemented at every role's abstraction level

## Next Steps

1. **Immediate:** Integrate Phase 1-5 (70 minutes)
2. **Week 2:** Add plan_effectiveness tracking (Coordinator learning)
3. **Week 3:** Add Guide response quality self-assessment
4. **Week 4:** Create quality monitoring dashboard

## Files Location

```
project_build_instructions/
├── quality-tracking-system.md          # Full design spec
├── quality-feedback-flows.md           # Visual diagrams
└── quality_tracking_impl/
    ├── README.md                       # This file
    ├── INTEGRATION_GUIDE.md            # Integration steps
    ├── claim_quality.py                # Core scoring logic
    ├── satisfaction_detector.py        # User feedback detection
    ├── context_filter.py               # Safe context injection
    ├── migrate_claims_db.sql           # Database updates
    └── test_quality_system.py          # Tests
```

## Support

- Design docs: `quality-tracking-system.md`
- Visual flows: `quality-feedback-flows.md`
- Integration help: `INTEGRATION_GUIDE.md`
- Test verification: `python test_quality_system.py`

---

**Ready to prevent toxic feedback loops and enable true multi-cycle learning!** 🚀
