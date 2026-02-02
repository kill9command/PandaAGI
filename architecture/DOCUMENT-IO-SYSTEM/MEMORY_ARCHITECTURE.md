# Memory Architecture

**Status:** SPECIFICATION
**Created:** 2025-12-28
**Updated:** 2026-01-04
**Architecture:** PandaAI v2

---

## Overview

Planner-centric memory model where:
- **Everything is a document** with rich metadata
- **Planner orchestrates** all document operations
- **Coordinator executes** memory tools on Planner's behalf
- **One unified search** interface for all document types

**Role Assignments (see `architecture/LLM-ROLES/llm-roles-reference.md`):**
All text roles use MIND model (Qwen3-Coder-30B-AWQ) with different temperatures:
| Phase | Role | Temp |
|-------|------|------|
| Phase 0 | Query Analyzer | REFLEX (0.3) |
| Phase 1 | Reflection | REFLEX (0.3) |
| Phase 2 | Context Gatherer | MIND (0.5) |
| Phase 3 | Planner | MIND (0.5) |
| Phase 4 | Coordinator | MIND (0.5) + EYES for vision |
| Phase 5 | Synthesis | VOICE (0.7) |
| Phase 6 | Validation | MIND (0.5) |

---

## Core Principles

### 1. Phase 0 Routes, Reflection Gates, Context Gatherer Gathers ONCE, Planner Does Everything Else

**This is simple. Do not overcomplicate it.**

```
┌─────────────────────────────────────────────────────────────────┐
│                    MEMORY ACCESS RULES                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  QUERY ANALYZER (Phase 0):                                       │
│  ─────────────────────────                                       │
│  • Runs FIRST to classify and resolve query                      │
│  • Uses REFLEX model for fast classification                     │
│  • Resolves references ("that laptop" → specific product)        │
│  • Outputs: resolved_query, query_type, content_reference        │
│  • DONE. Query Analyzer never runs again this turn.              │
│                                                                  │
│  REFLECTION (Phase 1):                                           │
│  ─────────────────────                                           │
│  • Fast binary gate using REFLEX model                           │
│  • Decides PROCEED or CLARIFY                                    │
│  • Writes §1 (reflection decision)                               │
│  • If CLARIFY: pipeline exits, ask user                          │
│  • DONE. Reflection never runs again this turn.                  │
│                                                                  │
│  CONTEXT GATHERER (Phase 2):                                     │
│  ─────────────────────────────                                   │
│  • Runs ONCE after Phase 1 decides PROCEED                       │
│  • Uses MIND model for intelligent retrieval                     │
│  • Gathers ALL relevant context from ALL sources:                │
│      - Turn history (TurnIndexDB)                                │
│      - Past research (ResearchIndexDB)                           │
│      - User preferences (users/{user_id}/preferences.md)         │
│      - Intelligence cache (indexed by user_id)                   │
│  • Writes §2 (gathered context)                                  │
│  • DONE. Context Gatherer never runs again this turn.            │
│                                                                  │
│  PLANNER (Phase 3+):                                             │
│  ──────────────────                                              │
│  • Uses MIND model for planning and reasoning                    │
│  • Does EVERYTHING ELSE for the rest of the turn                 │
│  • Reads §2 (what Context Gatherer gave it)                      │
│  • Decides what tools to call                                    │
│  • Requests tools via Coordinator                                │
│  • Tool results go to §4                                         │
│  • Planner NEVER calls Context Gatherer again                    │
│                                                                  │
│  THAT'S IT. NO OVERLAP. NO CONFUSION.                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Context Gatherer's Job (2-phase process):**

1. **RETRIEVAL:** Parse query → search indexes → find relevant docs
2. **SYNTHESIS:** Extract useful info → compile into §2

**What goes in §2:**
```markdown
### Prior Research: [topic]
**Source:** turn_000815 (2025-12-13)
**Quality:** 0.85
**Key Findings:**
- Syrian Hamster available at $20 (Hubba-Hubba Hamstery)
```

**Token budget:** §2 capped at 2000 tokens. SmartSummarizer (NERVES model) compresses if over.

**After Phase 2 completes:** Context Gatherer is DONE. It does not run again. Planner takes over.

### 2. The context.md IS the Lesson

Every completed turn produces a context.md with:
- §0: What user asked
- §1: What reflection decided (PROCEED/CLARIFY)
- §2: What context was gathered
- §3: What plan was created
- §4: What tools executed and results
- §5: What response was synthesized
- §6: Whether it validated (APPROVE/RETRY/REVISE/FAIL)

**This context.md file IS the lesson.** No separate lesson extraction. No special "LEARN" decision.

Phase 7 indexes every context.md in TurnIndexDB. Future Context Gatherers search this index to find similar past turns. That's how the system learns.

**Learning is automatic:**
1. Turn completes → context.md saved → indexed in TurnIndexDB
2. Similar query arrives → Context Gatherer finds it → includes in §2
3. Planner sees what worked before → makes better decisions

No magic. No pattern detection. Just indexed context.md files.

### 3. Planner Orchestrates Everything Else

Planner is aware of all documents and can:
- **Search** for relevant documents
- **Create** new documents (memories, preferences, lessons)
- **Update** existing documents
- **Use** documents to inform planning

Planner uses todo lists to manage multi-step memory operations:
```
1. [in_progress] Search for relevant documents
2. [pending] Review found documents
3. [pending] Decide if more info needed
4. [pending] Continue planning
```

### 4. Documents with Rich Metadata (Not Rigid Types)

Every document shares the same metadata schema:
```python
DocumentMetadata:
    id: str                 # Unique identifier
    primary_topic: str      # "pet.hamster.syrian" or "electronics.laptop"
    keywords: List[str]     # ["hamster", "care", "breeding"]
    intent: str             # "transactional" | "informational"
    content_types: List[str] # ["vendor_info", "lesson", "preference"]
    scope: str              # "new" | "user" | "global"
    quality: float          # 0.0 - 1.0
    created_at: timestamp
    expires_at: timestamp   # Optional TTL
    doc_path: str           # Path to actual document
```

**"Type" is just metadata:**

| Conceptual Type | How It's Represented |
|-----------------|---------------------|
| Context/Lesson | `content_types=["context"]` - the context.md file itself |
| Research | `content_types=["vendor_info", "pricing"]` |
| Site Knowledge | `topic="site.amazon.com"`, `content_types=["site_pattern"]` |
| Preference | `topic="user.preference"`, `content_types=["preference"]` |
| Memory/Fact | `topic="user.fact"`, `content_types=["memory"]` |

**Note:** Context.md files are indexed as lessons. No separate lesson extraction needed.

### 5. One Unified Search

Planner searches all documents with one interface:
```python
memory.search(
    query="laptops under $1000",        # Natural language or keywords
    topic_filter="electronics.laptop",  # Optional topic filter
    content_types=["vendor_info"],      # Optional content filter
    scope="user",                       # Optional scope filter
    session_id="user1",                 # Optional session filter
    min_quality=0.5,                    # Optional quality threshold
    include_expired=False               # Whether to include stale docs
)
```

---

## The Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                    PLANNER-CENTRIC MEMORY FLOW                    │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  User: "Find me laptops under $1000"                              │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ QUERY ANALYZER [REFLEX] (Phase 0)                          │  │
│  │                                                              │  │
│  │ - Resolve references ("that laptop" → specific)             │  │
│  │ - Classify query type                                       │  │
│  │ - Output: resolved_query, query_type                        │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                          │                                        │
│                          ▼                                        │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ CONTEXT GATHERER [MIND] (Phase 2)                          │  │
│  │                                                              │  │
│  │ - Parse query → topic: electronics.laptop                   │  │
│  │ - Load preferences.md from user directory                   │  │
│  │ - Get last 3 turns summary                                  │  │
│  │ - Pass to Planner                                           │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                          │                                        │
│                          ▼                                        │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ PLANNER [MIND] (Phase 3)                                   │  │
│  │                                                              │  │
│  │ Thinks: "Check what we already know about laptops"          │  │
│  │                                                              │  │
│  │ Todo:                                                        │  │
│  │ 1. [in_progress] Search for laptop documents                │  │
│  │ 2. [pending] Review documents                               │  │
│  │ 3. [pending] Plan next steps                                │  │
│  │                                                              │  │
│  │ → Coordinator: memory.search(query="laptop", ...)           │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                          │                                        │
│                          ▼                                        │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ COORDINATOR [MIND] (Phase 4)                               │  │
│  │                                                              │  │
│  │ Executes memory.search tool                                 │  │
│  │                                                              │  │
│  │ Returns: 2 documents found                                  │  │
│  │ - research_1209.md (48h old, quality 0.75)                  │  │
│  │ - turn_0042/context.md (laptop strategy, validated)         │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                          │                                        │
│                          ▼                                        │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ PLANNER [MIND] (loop back with results)                    │  │
│  │                                                              │  │
│  │ Reviews: "Found stale research (48h). Need fresh data."     │  │
│  │                                                              │  │
│  │ Todo:                                                        │  │
│  │ 1. [completed] Search for laptop documents                  │  │
│  │ 2. [completed] Review - found stale research                │  │
│  │ 3. [in_progress] Execute fresh internet research            │  │
│  │ 4. [pending] Save results                                   │  │
│  │                                                              │  │
│  │ → Coordinator: internet.research(query="laptops < $1000")   │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                          │                                        │
│                          ▼                                        │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ COORDINATOR [MIND] (Phase 4)                               │  │
│  │                                                              │  │
│  │ Executes internet.research tool                             │  │
│  │ → Page Intelligence captures pages                          │  │
│  │ → Extractions saved to research.md                          │  │
│  │ → Indexed in ResearchIndexDB                                │  │
│  │                                                              │  │
│  │ Returns: 15 laptops from 4 vendors                          │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                          │                                        │
│                          ▼                                        │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ PLANNER [MIND] (loop back with results)                    │  │
│  │                                                              │  │
│  │ Reviews: "Got fresh results. Notice user prefers RTX GPUs." │  │
│  │                                                              │  │
│  │ Todo:                                                        │  │
│  │ 1-3. [completed]                                             │  │
│  │ 4. [in_progress] Save user preference                       │  │
│  │ 5. [pending] Synthesize answer                              │  │
│  │                                                              │  │
│  │ → Coordinator: memory.save(                                  │  │
│  │     type="preference",                                       │  │
│  │     content="user prefers gaming laptops with RTX GPUs"     │  │
│  │   )                                                          │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                          │                                        │
│                          ▼                                        │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ PLANNER [MIND] (final)                                     │  │
│  │                                                              │  │
│  │ Todo:                                                        │  │
│  │ 1-4. [completed]                                             │  │
│  │ 5. [in_progress] Synthesize answer                          │  │
│  │                                                              │  │
│  │ → Synthesis [VOICE]: "Here are the best laptops..."         │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Memory Tools

### memory.search

Search all documents with unified interface:

```python
@tool
async def memory_search(
    query: str,                          # Natural language or keywords
    topic_filter: Optional[str] = None,  # Topic hierarchy filter
    content_types: Optional[List[str]] = None,  # Filter by content type
    scope: Optional[str] = None,         # new | user | global
    session_id: Optional[str] = None,    # Filter to specific session
    min_quality: float = 0.0,            # Minimum quality threshold
    include_expired: bool = False,       # Include stale documents
    limit: int = 10                      # Maximum results
) -> List[SearchResult]:
    """
    Search all document types with one interface.

    Searches across:
    - Research documents (ResearchIndexDB)
    - Turns/Lessons (TurnIndexDB - context.md files ARE the lessons)
    - Site knowledge (to be indexed)
    - Preferences (to be indexed)
    """
    pass
```

### memory.save

Save new documents (memories, preferences, lessons):

```python
@tool
async def memory_save(
    content: str,                        # Document content
    doc_type: str,                       # preference | memory | site_knowledge
    topic: str,                          # Topic classification
    keywords: List[str],                 # Keywords for search
    scope: str = "new",                  # new | user | global
    ttl_hours: Optional[int] = None      # Time to live
) -> str:
    """
    Save a new document to the memory system.

    Returns document ID.
    """
    pass
```

### memory.retrieve

Get specific document by ID or path:

```python
@tool
async def memory_retrieve(
    doc_id: Optional[str] = None,        # Document ID
    doc_path: Optional[str] = None       # Or document path
) -> Document:
    """
    Retrieve a specific document by ID or path.
    """
    pass
```

---

## Existing Search Infrastructure

### ResearchIndexDB (`lib/gateway/research_index_db.py`)

SQLite index for research documents:
- **Topic hierarchy** - `pet.hamster` matches `pet.hamster.syrian`
- **Intent filtering** - transactional, informational
- **Quality ranking** - completeness, source quality, overall
- **Freshness decay** - confidence decays over time
- **Scope filtering** - new, user, global
- **Keyword search** - `search_by_keywords()`
- **Content needs** - `search_by_content_needs()`
- **Related topics** - `find_related()`
- **Scope promotion** - new → user → global based on usage
- **Deduplication** - superseding logic for overlapping research

**Database:** `panda-system-docs/indexes/research_index.db`

### TurnIndexDB (`lib/gateway/turn_index_db.py`)

SQLite index for turns (context.md files = lessons):
- **Session filtering** - `get_session_turns()`
- **Keyword search** - `search_by_keywords()`
- **Timestamp ordering** - newest first
- **Pattern retrieval** - find similar past contexts

**Database:** `panda-system-docs/indexes/turn_index.db`

**Canonical Schema:**
```sql
CREATE TABLE turn_index (
    id TEXT PRIMARY KEY,
    turn_number INTEGER,
    session_id TEXT,

    -- Topic & Intent (for similarity search)
    topic TEXT,                    -- "electronics.laptop", "pet.hamster"
    intent TEXT,                   -- "transactional", "informational"

    -- Validation Outcome
    validation_outcome TEXT,       -- APPROVE, RETRY, REVISE, FAIL
    strategy_summary TEXT,         -- What plan was used (from §3)
    quality_score REAL,            -- Overall turn quality 0.0-1.0 (this IS the confidence)

    -- User Feedback (implicit detection, from USER_FEEDBACK_SYSTEM)
    user_feedback_status TEXT,     -- 'rejected' | 'accepted' | 'neutral'
    rejection_detected_in TEXT,    -- turn_id where rejection was detected

    -- Timestamps
    created_at REAL,

    -- Searchable content
    keywords TEXT,                 -- Comma-separated keywords
    doc_path TEXT                  -- Path to context.md
);

-- Indexes for common queries
CREATE INDEX idx_session ON turn_index(session_id);
CREATE INDEX idx_topic ON turn_index(topic);
CREATE INDEX idx_validation ON turn_index(validation_outcome);
CREATE INDEX idx_created ON turn_index(created_at);
CREATE INDEX idx_feedback ON turn_index(user_feedback_status);
```

**Note:** Quality score IS the confidence. No separate calibration needed.

---

## Document Storage

All runtime data stored under `panda-system-docs/`:

```
panda-system-docs/                    # Runtime data root
│
├── users/                            # Per-user persistent data
│   └── {user_id}/                    # e.g., "alice", "bob"
│       ├── preferences.md            # User preferences
│       ├── facts.md                  # Learned facts about user
│       └── turns/                    # User's turn history
│           └── turn_000001/
│               ├── context.md        # THE LESSON - complete turn (§0-§6)
│               ├── research.md       # Research results
│               ├── research.json     # Research metadata (indexed)
│               ├── query_analysis.json  # Phase 0 output
│               ├── ticket.md         # Task ticket from Planner
│               ├── toolresults.md    # Tool execution results
│               ├── metrics.json      # Observability data
│               ├── metadata.json     # Turn metadata (indexed)
│               └── webpage_cache/    # Cached page visit data
│                   └── {url_slug}/
│                       ├── manifest.json
│                       ├── page_content.md
│                       └── extracted_data.json
│
├── site_knowledge/                   # Global - LLM-learned site patterns
│   ├── amazon.com.json
│   └── bestbuy.com.json
│
├── observability/                    # Global - Aggregated metrics
│   ├── daily/                        # Daily rollup JSON files
│   └── trends.db                     # SQLite for trend queries
│
└── indexes/                          # Database indexes
    ├── turn_index.db                 # TurnIndexDB - indexes all users' turns
    ├── research_index.db             # ResearchIndexDB - indexes research docs
    └── source_reliability.db         # Source validation tracking
```

**Per-User Storage:**

User preferences and facts are stored as **markdown files** in per-user directories. This approach:
- Provides natural isolation between users
- Makes data human-readable and easy to debug
- Integrates with the existing markdown-based document system
- Turn numbers are per-user (each user starts at turn 1)

**Preference file format** (`preferences.md`):
```markdown
# User Preferences

## General

- **favorite_hamster:** Syrian
- **preference:** I prefer gaming laptops with RTX GPUs

---

*Updated automatically by turn saver*
```

**Facts file format** (`facts.md`):
```markdown
# User Facts

## Remembered Facts

- User lives in California
- Budget is typically under $1500

---

*Updated automatically by turn saver*
```

**No separate lessons directory.** The context.md files in each user's turns/ directory ARE the lessons. TurnIndexDB indexes them with:
- Topic and intent
- Validation outcome (APPROVE, RETRY, REVISE, FAIL)
- Strategy used (what plan worked)
- Quality score

---

## Source Reliability Tracking

`memory/source_reliability.db` stores extraction outcomes by domain and is used by the
SourceQualityScorer to rank and filter sources. This is **global system
knowledge** (shared across users), not session-scoped, because reliability is
site-specific rather than user-specific.

**Logged Fields (per extraction):**
- `domain`, `extraction_type`, `success`, `confidence`, `timestamp`

**Default success criteria:**
- >= 2 items extracted
- Required fields present for the goal
- Validator passes (no conflicts flagged)

Aggregated reliability is refreshed periodically and used in the quality blend
for future source selection.

## User Identity Model (No Session Lifecycle)

The system is **stateless per-turn** with **persistent document storage**. There is no session start or end.

### What "session_id" Really Means

```python
# session_id is a USER IDENTITY, not a temporary session
session_id = "user1"  # Persistent user namespace
```

**session_id** is used for:
- Namespace for user-specific data (preferences, research)
- Filter for Context Gatherer ("get user's history")
- Scope boundary (user scope vs. global scope)

### Why No Session Lifecycle?

| Traditional Concern | How Pandora Handles It |
|--------------------|------------------------|
| Load state on start | Context Gatherer retrieves per-turn |
| Save state on end | Phase 7 saves after every turn |
| Cleanup stale data | TTL + confidence decay (automatic) |
| Promote useful docs | Continuous based on usage count |
| Track conversation | TurnIndexDB indexes all turns |

### Each Turn Is Self-Contained

```
Turn N arrives
    ↓
Phase 0 [REFLEX] resolves query references
    ↓
Context Gatherer [MIND] retrieves relevant history from persistent storage
    ↓
Planner/Coordinator/Synthesis [MIND/VOICE] execute
    ↓
Phase 7 saves everything (context.md, research.md, indexes)
    ↓
Turn complete - no in-memory state carried forward
```

The system is always "on" - no initialization needed, no cleanup needed.

---

## Scope Promotion

Documents graduate from new → user → global based on trust scores and usage.

**See `UNIVERSAL_CONFIDENCE_SYSTEM.md` for the canonical trust calculation and promotion thresholds.**

```
NEW ──────────────► USER ──────────────► GLOBAL
(just created)     (proven useful)      (universally useful)
```

| Scope | Description | Persistence |
|-------|-------------|-------------|
| **NEW** | Just created, unproven | TTL expiration (24h default) |
| **USER** | Proven useful for this user | Persists indefinitely |
| **GLOBAL** | Useful across all users | Highest trust level |

### Promotion/Demotion Thresholds

| Transition | Trust Required | Other Requirements |
|------------|----------------|-------------------|
| New → User | >= 0.50 | usage >= 3, age >= 1 hour |
| User → Global | >= 0.80 | usage >= 10, age >= 24 hours |
| Global → User (demotion) | < 0.80 | - |
| User → New (demotion) | < 0.50 | - |

### What Counts as "Use"?

A document is "used" when it appears in §2 (Gathered Context) and contributes to the turn. Outcome is recorded in Phase 7:

| Validation Outcome | Effect on Trust |
|--------------------|-----------------|
| APPROVE | validation_success++ (trust calibrates upward) |
| RETRY | validation_count++ only (trust calibrates downward) |
| FAIL | validation_count++ only (trust calibrates downward) |
| REVISE | No change (intermediate state) |

---

## Integration with Existing Phases

```
Phase 0: Query Analyzer [REFLEX]
         - Resolve references in query
         - Classify query type
         - Identify content references from prior turns

Phase 1: Reflection [REFLEX]
         - Fast binary gate
         - PROCEED or CLARIFY decision
         - If CLARIFY: exit to user

Phase 2: Context Gatherer [MIND]
         - Parse query → topic, intent
         - Load preferences
         - Search for similar past context.md files
         - Include patterns in §2
         - Pass to Planner

Phase 3: Planner [MIND]
         - Sees past patterns in §2
         - Orchestrates memory operations
         - Creates todo list
         - Loops until planning complete (see PLANNER_COORDINATOR_LOOP.md)

Phase 4: Coordinator [MIND]
         - Executes memory.search, memory.save
         - Executes internet.research (Page Intelligence via MCP tools)
         - Returns results to Planner
         - Vision tasks use EYES [Qwen3-VL-8B] (cold load)

Phase 5: Synthesis [VOICE]
         - Uses gathered documents from §2 and §4
         - Generates user-facing response

Phase 6: Validation [MIND]
         - Validates response
         - Records outcome (APPROVE, RETRY, REVISE, FAIL)

Phase 7: Save (No LLM - procedural)
         - Indexes context.md in TurnIndexDB (this IS the lesson)
         - Indexes research.md in ResearchIndexDB
         - Updates site knowledge if validation failed then succeeded
```

---

## How Learning Works (No Magic)

**There is NO special "LEARN" decision. There is NO §7.**

The context.md file (§0-§6) IS the lesson. Every turn's context.md gets indexed in TurnIndexDB. That's it.

```
Turn completes → context.md saved → indexed in TurnIndexDB
                                           ↓
Similar query arrives → Context Gatherer [MIND] searches TurnIndexDB
                                           ↓
                     → Finds similar past context.md
                                           ↓
                     → Includes key info in §2
                                           ↓
Planner [MIND] sees §2 → Knows what worked before → Makes better decisions
```

**What gets indexed for similarity search:**
- Topic (e.g., "electronics.laptop", "pet.hamster")
- Intent (commerce, informational)
- Validation outcome (APPROVE, RETRY, REVISE, FAIL)
- Quality score

**How Context Gatherer uses past turns:**
1. Search TurnIndexDB for similar topic + intent
2. Prefer turns that validated successfully (APPROVE)
3. Include summary in §2 so Planner can see what worked

**Legacy cleanup - COMPLETED:**
- ~~`lib/gateway/lesson_store.py`~~ - Deleted
- ~~`lib/gateway/lesson_extractor.py`~~ - Deleted
- ~~`panda_system_docs/lessons/`~~ - Deleted

---

## Turn Archival Policy

### Retention Tiers

| Age | Status | Storage |
|-----|--------|---------|
| 0-30 days | **Active** | Full context.md and research.md preserved |
| 30+ days | **Archived** | Summary in turn_index.db, originals in cold storage |

### Archival Process

When a turn reaches 30 days:

1. **Generate summary** (no LLM needed - extract from existing metadata):
```python
summary = {
    "query": context_doc.section_0,  # Original query
    "intent": metadata.intent,
    "outcome": metadata.validation_outcome,  # APPROVE, FAIL, etc.
    "key_claims": extract_top_claims(context_doc.section_4, limit=3),
    "revision_count": metadata.revision_count
}
```

2. **Update turn_index.db** with summary:
```sql
UPDATE turn_index
SET archived = TRUE,
    summary_json = '{...}',
    doc_path = 'panda-system-docs/archive/2025-11/{user_id}/turn_000815/'
WHERE turn_id = 'turn_000815';
```

3. **Move originals to cold storage:**
```
panda-system-docs/archive/2025-11/{user_id}/turn_000815/
├── context.md      # Original, preserved
├── research.md     # Original, preserved
└── metadata.json   # Original, preserved
```

### Retrieval from Archive

- **Summaries are searchable** - turn_index.db still contains summary_json
- **Originals accessible** - Just slower (different path)

### Archival Script

```bash
# Run weekly via cron
scripts/archive_old_turns.py --age-days 30 --dry-run  # Preview
scripts/archive_old_turns.py --age-days 30            # Execute
```

---

## Related Documents

- `architecture/LLM-ROLES/llm-roles-reference.md` - Model assignments per phase
- `architecture/main-system-patterns/phase*.md` - Detailed phase documentation
- `architecture/UNIVERSAL_CONFIDENCE_SYSTEM.md` - Trust calculation and promotion
- `architecture/DOCUMENT-IO-SYSTEM/` - context.md specification

---

**Last Updated:** 2026-01-04 (Adapted for PandaAI v2 with Phase 0 and model assignments)
