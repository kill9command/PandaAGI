# Observability System

**Status:** SPECIFICATION
**Created:** 2025-12-28
**Updated:** 2026-01-04

---

## Overview

Observability for Pandora enables:
- **Debugging** - Understand why a turn failed or behaved unexpectedly
- **Optimization** - Identify bottlenecks in time and token usage
- **Quality tracking** - Monitor if the system is improving over time
- **Calibration** - Verify confidence scores match reality
- **Model tracking** - Know which model (REFLEX, MIND, VOICE, EYES) was used per phase

---

## Design Principles

### 1. Build on What Exists

Pandora already has strong observability foundations:

| Existing Artifact | What It Provides |
|-------------------|------------------|
| `transcripts/YYYYMMDD.jsonl` | Turn summaries, final response, timing |
| `transcripts/verbose/YYYYMMDD/*.json` | Full turn details |
| `panda-system-docs/users/{user_id}/turns/turn_NNNN/context.md` | Complete turn flow with all sections |
| `panda-system-docs/users/{user_id}/turns/turn_NNNN/research.md` | Research results with quality scores |
| `panda-system-docs/indexes/research_index.db` | Indexed research for querying |
| `panda-system-docs/indexes/turn_index.db` | Indexed turns for querying |

**Principle:** Extend these artifacts rather than creating parallel systems.

### 2. Observability Is a Document

Following the "everything is a document" pattern, observability data is stored as documents that can be:
- Indexed and searched
- Retrieved by Context Gatherer (for self-improvement)
- Decayed over time (old metrics become less relevant)

### 3. Aggregate for Trends, Detail for Debugging

- **Per-turn data:** Full detail for debugging specific issues
- **Aggregated data:** Trends over time for system health

---

## Component 1: Phase Timing & Token Usage

### Why This Matters

**Problem:** Without timing data, you can't identify bottlenecks. A turn that takes 400 seconds might be:
- 99% in internet.research (expected, CAPTCHA intervention)
- 50% in Planner (unexpected, need to investigate prompt)

**Problem:** Without token tracking, you can't:
- Know if you're approaching budget limits
- Optimize prompts for efficiency
- Identify which phases consume most tokens

**Problem:** Without model tracking, you can't:
- Verify the right model is being used per phase
- Identify if model misrouting is causing quality issues
- Calculate per-model token costs

### Data Model

```python
@dataclass
class PhaseTiming:
    """Timing and token usage for a single phase."""
    phase: str                    # "query_analyzer", "context_gatherer", "planner", etc.
    phase_number: int             # 0-7 (see LLM-ROLES for canonical phase list)

    # Model tracking (see architecture/LLM-ROLES/llm-roles-reference.md)
    model_used: str               # "REFLEX", "NERVES", "MIND", "VOICE", "EYES", or "NONE"

    # Timing
    started_at: datetime
    ended_at: datetime
    duration_ms: int

    # Token usage
    tokens_in: int                # Prompt tokens
    tokens_out: int               # Completion tokens
    tokens_total: int

    # LLM calls within phase
    llm_calls: int

    # Tool calls within phase (for Coordinator)
    tool_calls: List[ToolCallTiming]

@dataclass
class ToolCallTiming:
    """Timing for a single tool call."""
    tool_name: str
    started_at: datetime
    ended_at: datetime
    duration_ms: int
    success: bool
    error: Optional[str]

@dataclass
class TurnTiming:
    """Complete timing for a turn."""
    turn_number: int
    session_id: str

    # Overall
    total_duration_ms: int
    total_tokens: int

    # Per-phase breakdown
    phases: List[PhaseTiming]

    # Bottleneck identification
    slowest_phase: str
    slowest_phase_pct: float      # % of total time
    highest_token_phase: str
    highest_token_pct: float      # % of total tokens

    # Model usage summary
    tokens_by_model: Dict[str, int]  # {"REFLEX": 3500, "MIND": 45000, ...}
```

### Storage

**Per-turn:** All observability data goes in `metrics.json` (see Unified Schema section):
```
panda-system-docs/users/{user_id}/turns/turn_001211/
├── context.md
├── research.md
├── metrics.json         # All observability: timing, decisions, tools, quality
└── ...
```

**Aggregated:** Daily rollup in `panda-system-docs/observability/`:
```
panda-system-docs/observability/
├── daily/
│   ├── 2026-01-04.json  # Aggregated metrics for the day
│   └── ...
└── trends.db            # SQLite for trend queries
```

### Example Output

```json
{
  "turn_number": 1211,
  "total_duration_ms": 408518,
  "total_tokens": 12450,
  "phases": [
    {
      "phase": "query_analyzer",
      "phase_number": 0,
      "model_used": "REFLEX",
      "duration_ms": 450,
      "tokens_in": 500,
      "tokens_out": 180,
      "llm_calls": 1
    },
    {
      "phase": "context_gatherer",
      "phase_number": 2,
      "model_used": "MIND",
      "duration_ms": 1250,
      "tokens_in": 850,
      "tokens_out": 320,
      "llm_calls": 1
    },
    {
      "phase": "coordinator",
      "phase_number": 4,
      "model_used": "MIND",
      "duration_ms": 385000,
      "tokens_in": 2100,
      "tokens_out": 450,
      "llm_calls": 2,
      "tool_calls": [
        {
          "tool_name": "internet.research",
          "duration_ms": 384500,
          "success": true
        }
      ]
    }
  ],
  "slowest_phase": "coordinator",
  "slowest_phase_pct": 94.2,
  "tokens_by_model": {
    "REFLEX": 680,
    "MIND": 8770,
    "VOICE": 3000,
    "EYES": 0
  }
}
```

### Why Each Field

| Field | Why It's Useful |
|-------|-----------------|
| `duration_ms` | Identify slow phases |
| `tokens_in/out` | Optimize prompts, track costs |
| `llm_calls` | Detect excessive LLM calls in loops |
| `tool_calls` | Identify slow/failing tools |
| `slowest_phase_pct` | Quick bottleneck identification |
| `model_used` | Verify correct model routing, calculate per-model costs |
| `tokens_by_model` | Track token consumption by model tier |

---

## Component 2: Decision Trail

### Why This Matters

**Problem:** When a turn fails or behaves unexpectedly, you need to understand the decision chain:
- Why did Reflection say PROCEED when it should have asked for clarification?
- Why did Planner route to synthesis instead of coordinator?
- Why did Coordinator call internet.research twice?

**Problem:** context.md has this info, but it's buried in markdown. Need structured extraction.

### Data Model

```python
@dataclass
class Decision:
    """A single decision point in the turn."""
    phase: str
    phase_number: int             # 0-7
    model_used: str               # REFLEX, MIND, VOICE, EYES, NONE
    decision_type: str            # "route", "tool_call", "validation", etc.
    decision_value: str           # "coordinator", "DONE", "RETRY", etc.
    reasoning: str                # Why this decision was made
    confidence: Optional[float]   # If applicable

    # Context that influenced decision
    inputs: Dict[str, Any]        # What the phase saw

@dataclass
class DecisionTrail:
    """Complete decision trail for a turn."""
    turn_number: int
    session_id: str
    query: str

    decisions: List[Decision]

    # Outcome
    final_outcome: str            # "success", "retry", "fail"
    validation_result: str        # "APPROVE", "RETRY", "REVISE", "FAIL"

    # For debugging failed turns
    failure_point: Optional[str]  # Which decision led to failure
    failure_reason: Optional[str]
```

### Extraction from context.md

The decision trail is already in context.md - we just need to extract it:

```python
def extract_decision_trail(context_md: str) -> DecisionTrail:
    """
    Extract structured decision trail from context.md.

    §0 (Query Analyzer) → Resolved query, query_type
    §1 (Reflection) → Decision: PROCEED/CLARIFY
    §3 (Planner) → Route To: coordinator/synthesis
    §4 (Coordinator) → Step N: TOOL_CALL/DONE/BLOCKED
    §6 (Validation) → Result: APPROVE/RETRY/REVISE/FAIL
    """
    decisions = []

    # Parse §0 for Query Analyzer output
    analyzer = parse_section(context_md, 0)
    decisions.append(Decision(
        phase="query_analyzer",
        phase_number=0,
        model_used="REFLEX",
        decision_type="resolve",
        decision_value=analyzer.query_type,
        reasoning=analyzer.reasoning
    ))

    # Parse §1 for Reflection decision
    reflection = parse_section(context_md, 1)
    decisions.append(Decision(
        phase="reflection",
        phase_number=1,
        model_used="REFLEX",
        decision_type="proceed",
        decision_value=reflection.decision,  # PROCEED, etc.
        reasoning=reflection.reasoning
    ))

    # Parse §3 for Planner routing
    planner = parse_section(context_md, 3)
    decisions.append(Decision(
        phase="planner",
        phase_number=3,
        model_used="MIND",
        decision_type="route",
        decision_value=planner.route_to,  # coordinator, synthesis
        reasoning=planner.planning_notes
    ))

    # Parse §4 for Coordinator steps
    coordinator = parse_section(context_md, 4)
    for step in coordinator.steps:
        decisions.append(Decision(
            phase="coordinator",
            phase_number=4,
            model_used="MIND",
            decision_type="step",
            decision_value=step.action,  # TOOL_CALL, DONE, BLOCKED
            reasoning=step.reasoning
        ))

    # Parse §6 for Validation
    validation = parse_section(context_md, 6)
    decisions.append(Decision(
        phase="validation",
        phase_number=6,
        model_used="MIND",
        decision_type="validation",
        decision_value=validation.result,  # APPROVE, RETRY, REVISE, FAIL
        reasoning=validation.issues or "Passed all checks"
    ))

    return DecisionTrail(decisions=decisions, ...)
```

### Storage

**Per-turn:** Decisions are stored in `metrics.json` alongside timing (see Unified Schema):
```json
{
  "timing": { ... },
  "decisions": [
    {
      "phase": "query_analyzer",
      "phase_number": 0,
      "model_used": "REFLEX",
      "decision_type": "resolve",
      "decision_value": "followup",
      "reasoning": "References 'that laptop' from prior turn"
    },
    {
      "phase": "reflection",
      "phase_number": 1,
      "model_used": "REFLEX",
      "decision_type": "proceed",
      "decision_value": "PROCEED",
      "reasoning": "Query is clear and actionable"
    },
    {
      "phase": "planner",
      "phase_number": 3,
      "model_used": "MIND",
      "decision_type": "route",
      "decision_value": "coordinator",
      "reasoning": "No cached research found, need fresh data"
    }
  ]
}
```

### Why Each Field

| Field | Why It's Useful |
|-------|-----------------|
| `decision_value` | Quick scan of what happened |
| `reasoning` | Understand why (for debugging) |
| `inputs` | What context influenced the decision |
| `failure_point` | Quickly identify where things went wrong |
| `model_used` | Verify correct model made the decision |
| `phase_number` | Quick identification of pipeline stage |

---

## Component 3: Research Quality Trends

### Why This Matters

**Problem:** Without tracking quality over time, you can't tell if:
- Recent changes improved or degraded research quality
- Certain topics have consistently poor results
- The system is learning effectively

**Problem:** Individual research.md files have quality scores, but no aggregation.

### Data Model

```python
@dataclass
class ResearchQualityMetrics:
    """Quality metrics for a single research."""
    research_id: str
    turn_number: int
    topic: str
    intent: str

    # Quality scores (from research.md)
    completeness: float
    source_quality: float
    extraction_success: float
    overall_quality: float

    # Outcome
    validation_result: str        # Did it pass validation?
    claims_count: int
    rejected_count: int           # Claims that were rejected

    # Confidence
    initial_confidence: float
    was_used: bool                # Was this research used in response?

@dataclass
class QualityTrend:
    """Aggregated quality metrics over time."""
    period: str                   # "daily", "weekly"
    date: str

    # Volume
    total_researches: int
    total_turns: int

    # Validation outcomes
    approve_rate: float
    revise_rate: float
    retry_rate: float
    fail_rate: float

    # Quality averages
    avg_completeness: float
    avg_source_quality: float
    avg_extraction_success: float
    avg_overall_quality: float

    # Cache effectiveness
    cache_hit_rate: float
    avg_claims_per_research: float

    # Topic breakdown
    quality_by_topic: Dict[str, float]
```

### Aggregation Queries

```sql
-- Daily quality trend
SELECT
    DATE(created_at) as date,
    COUNT(*) as total,
    AVG(overall_quality) as avg_quality,
    SUM(CASE WHEN validation_result = 'APPROVE' THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as approve_rate,
    SUM(CASE WHEN validation_result = 'REVISE' THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as revise_rate,
    SUM(CASE WHEN validation_result = 'RETRY' THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as retry_rate,
    SUM(CASE WHEN validation_result = 'FAIL' THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as fail_rate
FROM research_index
WHERE created_at > datetime('now', '-30 days')
GROUP BY DATE(created_at)
ORDER BY date DESC;

-- Quality by topic
SELECT
    primary_topic,
    COUNT(*) as count,
    AVG(overall_quality) as avg_quality
FROM research_index
WHERE created_at > datetime('now', '-7 days')
GROUP BY primary_topic
ORDER BY count DESC
LIMIT 10;
```

### Storage

**Daily rollup** in `panda-system-docs/observability/daily/YYYY-MM-DD.json`:
```json
{
  "date": "2026-01-04",
  "research_quality": {
    "total_researches": 15,
    "avg_overall_quality": 0.72,
    "validation_outcomes": {
      "approve": 0.40,
      "revise": 0.38,
      "retry": 0.18,
      "fail": 0.04
    },
    "cache_hit_rate": 0.34,
    "quality_by_topic": {
      "electronics.laptop": 0.75,
      "pet.hamster": 0.68
    }
  }
}
```

### Why Each Field

| Field | Why It's Useful |
|-------|-----------------|
| `validation_outcomes` | Track if validation pass rate is improving |
| `avg_overall_quality` | Single number for "is research getting better?" |
| `cache_hit_rate` | Is memory system working? |
| `quality_by_topic` | Identify topics that need improvement |

---

## Component 4: Tool Execution Stats

### Why This Matters

**Problem:** Without tool stats, you can't identify:
- Which tools are unreliable
- Which sites are frequently blocked
- Whether tool performance is degrading

**Problem:** Tool failures are scattered across individual turn logs.

### Data Model

```python
@dataclass
class ToolExecution:
    """A single tool execution."""
    tool_name: str
    turn_number: int
    timestamp: datetime

    # Execution details
    duration_ms: int
    success: bool
    error_type: Optional[str]     # "timeout", "blocked", "rate_limit", etc.
    error_message: Optional[str]

    # For internet.research
    sites_attempted: List[str]
    sites_succeeded: List[str]
    sites_blocked: List[str]
    captcha_encountered: bool
    captcha_resolved: bool

@dataclass
class ToolStats:
    """Aggregated stats for a tool."""
    tool_name: str
    period: str                   # "daily", "weekly"

    # Volume
    total_calls: int

    # Success rate
    success_rate: float

    # Timing
    avg_duration_ms: int
    p50_duration_ms: int
    p95_duration_ms: int

    # Error breakdown
    errors_by_type: Dict[str, int]

    # For internet.research specifically
    captcha_rate: float
    blocked_sites: Dict[str, int]  # site -> block count

@dataclass
class SiteReliability:
    """Reliability stats for a specific site."""
    domain: str

    total_attempts: int
    success_rate: float
    avg_extraction_quality: float
    block_count: int
    last_blocked: Optional[datetime]

    # Recommendation
    status: str                   # "reliable", "degraded", "blocked"
```

### Storage

**Per-tool tracking** in `panda-system-docs/observability/tools.db`:
```sql
CREATE TABLE tool_executions (
    id INTEGER PRIMARY KEY,
    tool_name TEXT,
    turn_number INTEGER,
    timestamp REAL,
    duration_ms INTEGER,
    success BOOLEAN,
    error_type TEXT,
    error_message TEXT
);

CREATE TABLE site_attempts (
    id INTEGER PRIMARY KEY,
    tool_execution_id INTEGER,
    domain TEXT,
    success BOOLEAN,
    blocked BOOLEAN,
    extraction_quality REAL,
    FOREIGN KEY (tool_execution_id) REFERENCES tool_executions(id)
);

-- Index for common queries
CREATE INDEX idx_tool_name_timestamp ON tool_executions(tool_name, timestamp);
CREATE INDEX idx_domain ON site_attempts(domain);
```

### Example Dashboard Query

```sql
-- Tool reliability (last 7 days)
SELECT
    tool_name,
    COUNT(*) as total_calls,
    AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) as success_rate,
    AVG(duration_ms) as avg_duration,
    COUNT(DISTINCT error_type) as error_types
FROM tool_executions
WHERE timestamp > strftime('%s', 'now') - 7*24*3600
GROUP BY tool_name
ORDER BY total_calls DESC;

-- Blocked sites
SELECT
    domain,
    COUNT(*) as block_count,
    MAX(timestamp) as last_blocked
FROM site_attempts
WHERE blocked = 1
  AND timestamp > strftime('%s', 'now') - 7*24*3600
GROUP BY domain
ORDER BY block_count DESC
LIMIT 10;
```

### Why Each Field

| Field | Why It's Useful |
|-------|-----------------|
| `success_rate` | Quick health check per tool |
| `errors_by_type` | Identify systemic issues (all timeouts? all blocked?) |
| `blocked_sites` | Know which sites to avoid or fix |
| `captcha_rate` | Track if anti-bot measures are increasing |
| `p95_duration_ms` | Identify tail latency issues |

---

## Component 5: Confidence Calibration Dashboard

### Why This Matters

**Problem:** The Universal Confidence System assumes our confidence scores are accurate. Without calibration tracking:
- We might be systematically overconfident (trust stale data)
- We might be systematically underconfident (re-research unnecessarily)
- We can't tune temperature scaling or decay rates

**Problem:** Calibration requires tracking predicted confidence vs. actual outcomes over time.

### Data Model

```python
@dataclass
class ConfidencePrediction:
    """A single confidence prediction and its outcome."""
    prediction_id: str
    timestamp: datetime

    # What was predicted
    content_type: str             # "price", "availability", "strategy", etc.
    source_id: str                # Specific source (site, selector, etc.)
    predicted_confidence: float

    # What actually happened
    validated: bool               # Was this prediction validated?
    validation_success: Optional[bool]  # Did it turn out correct?
    validation_timestamp: Optional[datetime]

@dataclass
class CalibrationMetrics:
    """Calibration metrics for a content type or source."""
    segment: str                  # Content type or source ID
    period: str                   # "daily", "weekly", "all_time"

    # Sample size
    total_predictions: int
    validated_predictions: int

    # Calibration
    expected_calibration_error: float  # ECE
    avg_predicted_confidence: float
    avg_actual_accuracy: float
    calibration_gap: float        # predicted - actual

    # Bucketed calibration (for calibration curves)
    buckets: List[CalibrationBucket]

    # Recommendation
    suggested_temperature: float  # T > 1 means overconfident
    trend: str                    # "improving", "stable", "degrading"

@dataclass
class CalibrationBucket:
    """One bucket in a calibration curve."""
    confidence_range: Tuple[float, float]  # e.g., (0.7, 0.8)
    count: int
    avg_confidence: float
    actual_accuracy: float
    gap: float                    # confidence - accuracy
```

### Expected Calibration Error (ECE)

```python
def calculate_ece(predictions: List[ConfidencePrediction], n_buckets: int = 10) -> float:
    """
    Calculate Expected Calibration Error.

    ECE = Σ (|accuracy_i - confidence_i| × n_i / N)

    Where:
      - accuracy_i = actual accuracy in bucket i
      - confidence_i = average confidence in bucket i
      - n_i = number of samples in bucket i
      - N = total samples
    """
    # Create buckets
    bucket_size = 1.0 / n_buckets
    buckets = [[] for _ in range(n_buckets)]

    for pred in predictions:
        if pred.validated and pred.validation_success is not None:
            bucket_idx = min(int(pred.predicted_confidence / bucket_size), n_buckets - 1)
            buckets[bucket_idx].append(pred)

    # Calculate ECE
    total = sum(len(b) for b in buckets)
    if total == 0:
        return 0.0

    ece = 0.0
    for bucket in buckets:
        if len(bucket) > 0:
            avg_conf = sum(p.predicted_confidence for p in bucket) / len(bucket)
            accuracy = sum(1 for p in bucket if p.validation_success) / len(bucket)
            ece += abs(accuracy - avg_conf) * len(bucket) / total

    return ece
```

### Temperature Scaling Recommendation

```python
def suggest_temperature(predictions: List[ConfidencePrediction]) -> float:
    """
    Suggest temperature scaling factor based on calibration.

    If system is overconfident (predicts 0.85, actually 0.70):
      - Temperature > 1.0 to soften confidence

    If system is underconfident (predicts 0.70, actually 0.85):
      - Temperature < 1.0 to sharpen confidence

    Uses graduated calibration:
      - < 5 predictions: no adjustment (return 1.0)
      - 5-9 predictions: blend calculated with neutral (0.5 weight)
      - >= 10 predictions: use calculated value
    """
    n = len(predictions)

    if n < 5:
        return 1.0  # Not enough data for any adjustment

    avg_predicted = sum(p.predicted_confidence for p in predictions) / n
    avg_actual = sum(1 for p in predictions if p.validation_success) / n

    if avg_actual == 0:
        return 1.0

    # Temperature that would correct the calibration
    # Higher temperature = lower confidence (for overconfident systems)
    calculated = avg_predicted / avg_actual

    # Clamp to reasonable range
    calculated = max(0.5, min(2.0, calculated))

    # Graduated blending for low-N samples
    if n < 10:
        # Blend with neutral (1.0) - some signal is better than none
        # but low-N calibration should be conservative
        weight = 0.5
        return calculated * weight + 1.0 * (1 - weight)

    return calculated
```

**Graduated Calibration Rationale:**

| Predictions | Behavior | Rationale |
|-------------|----------|-----------|
| < 5 | Return 1.0 (no adjustment) | Too few samples for meaningful calibration |
| 5-9 | Blend: 50% calculated + 50% neutral | Some signal, but hedge toward neutral |
| >= 10 | Use calculated value | Sufficient data for reliable calibration |

### Storage

**Predictions table** in `panda-system-docs/observability/calibration.db`:
```sql
CREATE TABLE confidence_predictions (
    id TEXT PRIMARY KEY,
    timestamp REAL,
    content_type TEXT,
    source_id TEXT,
    predicted_confidence REAL,
    validated BOOLEAN DEFAULT FALSE,
    validation_success BOOLEAN,
    validation_timestamp REAL
);

CREATE INDEX idx_content_type ON confidence_predictions(content_type);
CREATE INDEX idx_source_id ON confidence_predictions(source_id);
CREATE INDEX idx_timestamp ON confidence_predictions(timestamp);
```

### Calibration Dashboard Output

```json
{
  "date": "2026-01-04",
  "overall_ece": 0.08,
  "overall_status": "well_calibrated",

  "by_content_type": {
    "price": {
      "predictions": 45,
      "avg_predicted": 0.85,
      "avg_actual": 0.72,
      "ece": 0.13,
      "status": "overconfident",
      "suggested_temperature": 1.18
    },
    "availability": {
      "predictions": 32,
      "avg_predicted": 0.80,
      "avg_actual": 0.65,
      "ece": 0.15,
      "status": "overconfident",
      "suggested_temperature": 1.23
    },
    "strategy": {
      "predictions": 28,
      "avg_predicted": 0.90,
      "avg_actual": 0.88,
      "ece": 0.02,
      "status": "well_calibrated",
      "suggested_temperature": 1.02
    }
  },

  "recommendations": [
    "Apply temperature scaling T=1.18 to price confidence",
    "Apply temperature scaling T=1.23 to availability confidence",
    "Strategy confidence is well calibrated, no change needed"
  ]
}
```

### Why Each Field

| Field | Why It's Useful |
|-------|-----------------|
| `ece` | Single number for "how calibrated is this?" |
| `calibration_gap` | Direction of miscalibration (over/under) |
| `suggested_temperature` | Actionable fix for overconfidence |
| `by_content_type` | Different content may need different calibration |
| `trend` | Is calibration improving or degrading? |

---

## Unified Observability Schema

### Per-Turn Artifact

Each turn gets a `metrics.json` file combining all observability data:

```
panda-system-docs/users/{user_id}/turns/turn_001211/
├── context.md
├── research.md
├── research.json
├── metrics.json          # All observability data for this turn
└── webpage_cache/
```

**metrics.json structure:**
```json
{
  "turn_number": 1211,
  "session_id": "henry",
  "timestamp": "2026-01-04T21:06:10Z",

  "timing": {
    "total_duration_ms": 408518,
    "total_tokens": 12450,
    "phases": [...],
    "tokens_by_model": {
      "REFLEX": 680,
      "MIND": 8770,
      "VOICE": 3000,
      "EYES": 0
    }
  },

  "decisions": [
    {"phase": "query_analyzer", "phase_number": 0, "model_used": "REFLEX", "decision_value": "followup", ...},
    {"phase": "reflection", "phase_number": 1, "model_used": "REFLEX", "decision_value": "PROCEED", ...},
    {"phase": "context_gatherer", "phase_number": 2, "model_used": "MIND", "decision_value": "sufficient", ...},
    {"phase": "planner", "phase_number": 3, "model_used": "MIND", "decision_value": "coordinator", ...}
  ],

  "tools": [
    {"tool": "internet.research", "duration_ms": 384500, "success": true, ...}
  ],

  "quality": {
    "research_quality": 0.69,
    "validation_result": "APPROVE",
    "claims_count": 2
  },

  "confidence_predictions": [
    {"content_type": "price", "predicted": 0.80, ...}
  ]
}
```

### Daily Aggregation

Daily rollup in `panda-system-docs/observability/daily/YYYY-MM-DD.json`:

```json
{
  "date": "2026-01-04",
  "turns": 15,

  "timing": {
    "avg_duration_ms": 45000,
    "p50_duration_ms": 32000,
    "p95_duration_ms": 180000,
    "total_tokens": 187000,
    "bottleneck_phases": {"coordinator": 12, "planner": 2, "synthesis": 1},
    "tokens_by_model": {
      "REFLEX": 12500,
      "MIND": 135000,
      "VOICE": 39500,
      "EYES": 0
    }
  },

  "decisions": {
    "reflection_proceed_rate": 0.93,
    "planner_coordinator_rate": 0.80,
    "validation_outcomes": {"APPROVE": 10, "REVISE": 2, "RETRY": 2, "FAIL": 1}
  },

  "tools": {
    "internet.research": {"calls": 12, "success_rate": 0.92, "avg_duration_ms": 45000},
    "memory.search": {"calls": 8, "success_rate": 1.0, "avg_duration_ms": 120}
  },

  "quality": {
    "avg_research_quality": 0.72,
    "cache_hit_rate": 0.34
  },

  "calibration": {
    "overall_ece": 0.08,
    "recommendations": ["Apply T=1.18 to price confidence"]
  }
}
```

### Trend Database

SQLite for trend queries: `panda-system-docs/observability/trends.db`

```sql
-- Daily metrics for trend analysis
CREATE TABLE daily_metrics (
    date TEXT PRIMARY KEY,
    turns INTEGER,
    avg_duration_ms REAL,
    total_tokens INTEGER,
    approve_rate REAL,
    revise_rate REAL,
    retry_rate REAL,
    fail_rate REAL,
    avg_research_quality REAL,
    cache_hit_rate REAL,
    overall_ece REAL,
    -- Model-level token tracking
    tokens_reflex INTEGER,
    tokens_nerves INTEGER,
    tokens_mind INTEGER,
    tokens_voice INTEGER,
    tokens_eyes INTEGER
);

-- Tool metrics per day
CREATE TABLE daily_tool_metrics (
    date TEXT,
    tool_name TEXT,
    calls INTEGER,
    success_rate REAL,
    avg_duration_ms REAL,
    PRIMARY KEY (date, tool_name)
);

-- Site reliability per day
CREATE TABLE daily_site_metrics (
    date TEXT,
    domain TEXT,
    attempts INTEGER,
    success_rate REAL,
    block_count INTEGER,
    PRIMARY KEY (date, domain)
);

-- Model usage per day (for cost tracking)
CREATE TABLE daily_model_metrics (
    date TEXT,
    model TEXT,
    calls INTEGER,
    tokens_in INTEGER,
    tokens_out INTEGER,
    avg_duration_ms REAL,
    PRIMARY KEY (date, model)
);
```

---

## Implementation Integration

### Where Metrics Are Collected

| Phase | Phase # | Model | Metrics Collected |
|-------|---------|-------|-------------------|
| Query Analyzer | 0 | REFLEX | Query resolution, query type |
| Reflection | 1 | REFLEX | PROCEED/CLARIFY decision |
| Context Gatherer | 2 | MIND | Retrieval timing, context sources |
| Planner | 3 | MIND | Routing decision, intent classification |
| Coordinator | 4 | MIND (EYES for vision) | Tool execution timing, success/failure |
| Synthesis | 5 | VOICE | Response generation timing |
| Validation | 6 | MIND | Validation outcome, quality assessment |
| Save | 7 | NONE | Aggregation and persistence |

**Model Reference:** See `architecture/LLM-ROLES/llm-roles-reference.md` for complete model stack details.

### Collection Flow

```
Turn Execution
    │
    ├── Phase 0: record query analysis, model=REFLEX
    │
    ├── Each phase: record start/end time, tokens, model used
    │
    ├── Coordinator: record tool calls (EYES for vision sub-tasks)
    │
    ├── Validation: record outcome
    │
    ▼
Phase 7 (Save)
    │
    ├── Write metrics.json to turn directory
    │
    ├── Update trends.db with this turn's data
    │
    └── (Daily) Generate daily rollup at midnight
```

---

## Debugging Workflows

### "Why did this turn fail?"

```bash
# 1. Find the turn (replace {user_id} with actual user)
cat panda-system-docs/users/{user_id}/turns/turn_001211/metrics.json | jq '.decisions'

# 2. See the decision trail
# → Query Analyzer (REFLEX): resolved_query, query_type=followup
# → Reflection (REFLEX): PROCEED
# → Context Gatherer (MIND): sufficient
# → Planner (MIND): coordinator
# → Coordinator (MIND): TOOL_CALL internet.research
# → Coordinator (MIND): BLOCKED (rate_limit_exceeded)
# → Validation (MIND): RETRY

# 3. Check the tool failure
cat panda-system-docs/users/{user_id}/turns/turn_001211/metrics.json | jq '.tools'
# → internet.research: error_type="rate_limit_exceeded"

# 4. Check which model was used at failure point
cat panda-system-docs/users/{user_id}/turns/turn_001211/metrics.json | jq '.decisions[] | select(.decision_value == "BLOCKED")'
# → model_used: "MIND", phase: "coordinator"
```

### "Is research quality improving?"

```sql
-- Trend over last 14 days
SELECT date, avg_research_quality, approve_rate as success_rate
FROM daily_metrics
WHERE date > date('now', '-14 days')
ORDER BY date;
```

### "Which sites are unreliable?"

```sql
-- Sites with high block rates
SELECT domain, SUM(attempts) as total, SUM(block_count) as blocks,
       SUM(block_count) * 1.0 / SUM(attempts) as block_rate
FROM daily_site_metrics
WHERE date > date('now', '-7 days')
GROUP BY domain
HAVING block_rate > 0.1
ORDER BY block_rate DESC;
```

### "Is our confidence calibrated?"

```bash
# Check latest calibration
cat panda-system-docs/observability/daily/2026-01-04.json | jq '.calibration'

# → overall_ece: 0.08 (good if < 0.10)
# → price: overconfident by 0.13, apply T=1.18
```

### "Which model is consuming the most tokens?"

```sql
-- Token consumption by model (last 7 days)
SELECT
    model,
    SUM(tokens_in + tokens_out) as total_tokens,
    AVG(tokens_in + tokens_out) as avg_tokens_per_call,
    SUM(calls) as total_calls
FROM daily_model_metrics
WHERE date > date('now', '-7 days')
GROUP BY model
ORDER BY total_tokens DESC;
```

---

## Related Documents

- `architecture/LLM-ROLES/llm-roles-reference.md` - Model stack and phase mapping
- `architecture/main-system-patterns/phase*.md` - Detailed phase documentation
- `architecture/DOCUMENT-IO-SYSTEM/` - context.md specification

---

**Last Updated:** 2026-01-04
