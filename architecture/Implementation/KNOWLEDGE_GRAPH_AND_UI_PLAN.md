# Implementation Plan: Knowledge Graph, Phase Visualization & Compounding Context

**Status:** PLAN
**Created:** 2026-01-25
**Scope:** Three major features inspired by Rowboat architecture

---

## Executive Summary

This plan implements three interconnected features:

1. **Obsidian-Style Knowledge Graph** - Entity extraction, bidirectional backlinks, relationship tracking
2. **Phase Visualization UI** - Real-time display of Phase 0-7 in the chat interface
3. **Compounding Context** - Entity-centric documents that update as new information arrives

---

## Part 1: Knowledge Graph with Backlinks

### Current State

| Component | Location | Status |
|-----------|----------|--------|
| Turn Index | `panda_system_docs/turn_index.db` | ✓ Exists - topic/keyword indexing |
| Research Index | `panda_system_docs/research_index.db` | ✓ Exists - quality scoring, confidence decay |
| Obsidian Vault | `panda_system_docs/obsidian_memory/` | ✓ Exists - forward links only |
| Entity Database | - | ✗ Missing |
| Backlink Index | - | ✗ Missing |
| Relationship Graph | - | ✗ Missing |

### Gap Analysis

**What's Missing:**
1. **Entity Extraction Pipeline** - No system to identify and normalize entities (vendors, products, people, sites)
2. **Backlink Index** - Wiki links are one-way only, can't find "all docs linking TO this doc"
3. **Relationship Database** - No way to express "Vendor X sells Product Y" or "Thread Z recommends Vendor X"
4. **Entity Deduplication** - Same product/vendor can appear in multiple documents without linking

### Architecture Design

```
┌─────────────────────────────────────────────────────────────────────┐
│                      KNOWLEDGE GRAPH ARCHITECTURE                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │   ENTITIES   │───▶│ RELATIONSHIPS│◀───│  DOCUMENTS   │          │
│  │   (SQLite)   │    │   (SQLite)   │    │  (Markdown)  │          │
│  └──────────────┘    └──────────────┘    └──────────────┘          │
│         │                   │                   │                   │
│         ▼                   ▼                   ▼                   │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │   MENTIONS   │    │   BACKLINKS  │    │  FRONTMATTER │          │
│  │  (entity→doc)│    │  (doc↔doc)   │    │  (YAML meta) │          │
│  └──────────────┘    └──────────────┘    └──────────────┘          │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Database Schema

**File:** `libs/gateway/knowledge_graph_db.py` (NEW)

```sql
-- Core entity table
CREATE TABLE entities (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,      -- vendor, product, person, site, topic, thread
    canonical_name TEXT NOT NULL,   -- Normalized name: "Poppybee Hamstery"
    aliases TEXT,                   -- JSON array: ["poppybee", "poppybee hamstery llc"]
    first_seen_turn INTEGER,        -- When entity was first discovered
    last_seen_turn INTEGER,         -- Most recent mention
    confidence REAL DEFAULT 0.5,    -- Entity confidence score
    entity_data TEXT,               -- JSON: {url, price_range, location, etc.}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(entity_type, canonical_name)
);

-- Entity mentions in documents
CREATE TABLE entity_mentions (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER REFERENCES entities(id),
    document_path TEXT NOT NULL,    -- obsidian_memory/Knowledge/Products/hamster.md
    turn_number INTEGER,            -- Which turn added this mention
    mention_context TEXT,           -- Surrounding text snippet
    property_name TEXT,             -- price, url, recommendation
    property_value TEXT,            -- $75, https://..., "highly recommended"
    confidence REAL DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Entity relationships
CREATE TABLE relationships (
    id INTEGER PRIMARY KEY,
    source_entity_id INTEGER REFERENCES entities(id),
    target_entity_id INTEGER REFERENCES entities(id),
    relationship_type TEXT NOT NULL,  -- sells, recommends, mentioned_in, competes_with
    confidence REAL DEFAULT 0.5,
    weight REAL DEFAULT 1.0,          -- Strength of relationship
    source_document TEXT,             -- Where relationship was discovered
    source_turn INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_entity_id, target_entity_id, relationship_type)
);

-- Document backlinks (bidirectional)
CREATE TABLE backlinks (
    id INTEGER PRIMARY KEY,
    source_file TEXT NOT NULL,        -- File containing the link
    target_file TEXT NOT NULL,        -- File being linked to
    link_text TEXT,                   -- [[Syrian Hamster]] or [[vendor:Poppybee]]
    link_type TEXT DEFAULT 'wiki',    -- wiki, entity, url
    line_number INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_file, target_file, link_text)
);

-- Indexes for fast queries
CREATE INDEX idx_entities_type ON entities(entity_type);
CREATE INDEX idx_entities_name ON entities(canonical_name);
CREATE INDEX idx_mentions_entity ON entity_mentions(entity_id);
CREATE INDEX idx_mentions_doc ON entity_mentions(document_path);
CREATE INDEX idx_relationships_source ON relationships(source_entity_id);
CREATE INDEX idx_relationships_target ON relationships(target_entity_id);
CREATE INDEX idx_backlinks_source ON backlinks(source_file);
CREATE INDEX idx_backlinks_target ON backlinks(target_file);
```

### Entity Types

| Type | Example | Properties |
|------|---------|------------|
| `vendor` | Poppybee Hamstery | url, location, ships_to, rating, specialty |
| `product` | Syrian Hamster | price, vendor_id, category, in_stock |
| `person` | user mentions | - |
| `site` | reef2reef.com | domain, category, trust_score |
| `topic` | hamster care | parent_topic, aliases |
| `thread` | "Best hamster breeders 2025" | url, site_id, date, author |

### Implementation Tasks

#### Task 1.1: Create Knowledge Graph Database Module

**File:** `libs/gateway/knowledge_graph_db.py`

```python
from dataclasses import dataclass
from typing import List, Dict, Optional, Any
import sqlite3
import json
from pathlib import Path

@dataclass
class Entity:
    id: int
    entity_type: str
    canonical_name: str
    aliases: List[str]
    confidence: float
    entity_data: Dict[str, Any]
    first_seen_turn: int
    last_seen_turn: int

@dataclass
class Relationship:
    source_entity: Entity
    target_entity: Entity
    relationship_type: str
    confidence: float
    weight: float

class KnowledgeGraphDB:
    """
    Manages entity extraction, relationships, and backlinks.

    Usage:
        kg = KnowledgeGraphDB()

        # Add entity
        vendor_id = kg.add_entity("vendor", "Poppybee Hamstery",
            aliases=["poppybee"],
            data={"url": "https://...", "location": "TX"})

        # Add relationship
        kg.add_relationship(vendor_id, product_id, "sells", confidence=0.9)

        # Query relationships
        vendors = kg.get_entities_by_relationship(product_id, "sells", reverse=True)

        # Get backlinks to a document
        backlinks = kg.get_backlinks_to("Knowledge/Products/syrian-hamster.md")
    """

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or Path("panda_system_docs/knowledge_graph.db")
        self._init_db()

    def add_entity(self, entity_type: str, canonical_name: str,
                   aliases: List[str] = None, data: Dict = None,
                   turn_number: int = 0) -> int:
        """Add or update an entity."""
        pass

    def find_entity(self, name: str, entity_type: str = None) -> Optional[Entity]:
        """Find entity by name or alias."""
        pass

    def add_relationship(self, source_id: int, target_id: int,
                        relationship_type: str, confidence: float = 0.5,
                        source_document: str = None, turn: int = 0):
        """Add relationship between entities."""
        pass

    def get_relationships(self, entity_id: int,
                         relationship_type: str = None,
                         direction: str = "outgoing") -> List[Relationship]:
        """Get relationships for an entity."""
        pass

    def add_backlink(self, source_file: str, target_file: str,
                    link_text: str, link_type: str = "wiki"):
        """Register a backlink between documents."""
        pass

    def get_backlinks_to(self, target_file: str) -> List[Dict]:
        """Get all documents linking TO this file."""
        pass

    def get_links_from(self, source_file: str) -> List[Dict]:
        """Get all documents this file links TO."""
        pass

    def scan_document_links(self, file_path: Path):
        """Scan a markdown file and register all links."""
        pass

    def rebuild_backlink_index(self):
        """Scan all obsidian_memory files and rebuild backlink index."""
        pass
```

#### Task 1.2: Entity Extraction Pipeline

**File:** `libs/gateway/entity_extractor.py`

```python
from typing import List, Dict, Tuple
from dataclasses import dataclass

@dataclass
class ExtractedEntity:
    text: str               # Original text: "Poppybee Hamstery"
    entity_type: str        # vendor, product, site, etc.
    canonical_name: str     # Normalized: "Poppybee Hamstery"
    confidence: float       # Extraction confidence
    properties: Dict        # {url: "...", price: "$75"}
    context: str            # Surrounding text for verification

class EntityExtractor:
    """
    Extracts entities from research results and documents.

    Uses pattern matching + LLM for complex extraction.
    """

    # Pattern-based extraction (fast, high precision)
    VENDOR_PATTERNS = [
        r"(?:from|at|via|by)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",  # "from Poppybee Hamstery"
        r"([\w\s]+)\s+(?:sells|offers|has)",                       # "Petco sells"
    ]

    PRICE_PATTERNS = [
        r"\$(\d+(?:\.\d{2})?)",                                    # $75.00
        r"(\d+)\s*(?:dollars|USD)",                                # 75 dollars
    ]

    SITE_PATTERNS = [
        r"(?:on|at|from)\s+([\w-]+\.(?:com|org|net|io))",         # "on reef2reef.com"
        r"(https?://[\w.-]+)",                                     # Full URLs
    ]

    def extract_from_text(self, text: str, context: Dict = None) -> List[ExtractedEntity]:
        """Extract entities from text using patterns."""
        pass

    def extract_from_research(self, research_result: Dict) -> List[ExtractedEntity]:
        """Extract entities from internet.research results."""
        pass

    def extract_with_llm(self, text: str, entity_types: List[str]) -> List[ExtractedEntity]:
        """Use LLM for complex extraction (slower, more accurate)."""
        pass

    def normalize_entity(self, entity: ExtractedEntity) -> ExtractedEntity:
        """Normalize entity name (lowercase, strip, dedupe)."""
        pass

    def deduplicate(self, entities: List[ExtractedEntity]) -> List[ExtractedEntity]:
        """Merge duplicate entities."""
        pass
```

#### Task 1.3: Integrate Entity Extraction into Research Flow

**File:** `libs/gateway/unified_flow.py` (MODIFY)

After `_execute_internet_research` returns, extract and store entities:

```python
# In _execute_internet_research or after tool execution
async def _process_research_entities(
    self,
    research_result: Dict,
    context_doc: ContextDocument,
    turn_number: int
):
    """Extract entities from research results and store in knowledge graph."""
    from libs.gateway.entity_extractor import EntityExtractor
    from libs.gateway.knowledge_graph_db import get_knowledge_graph_db

    extractor = EntityExtractor()
    kg = get_knowledge_graph_db()

    # Extract entities from findings
    for finding in research_result.get("findings", []):
        entities = extractor.extract_from_text(finding.get("content", ""))

        for entity in entities:
            # Add to knowledge graph
            entity_id = kg.add_entity(
                entity_type=entity.entity_type,
                canonical_name=entity.canonical_name,
                aliases=[entity.text] if entity.text != entity.canonical_name else [],
                data=entity.properties,
                turn_number=turn_number
            )

            # Add mention
            kg.add_mention(
                entity_id=entity_id,
                document_path=f"turns/turn_{turn_number:06d}/context.md",
                turn_number=turn_number,
                context=entity.context,
                confidence=entity.confidence
            )

    # Extract relationships (vendor sells product, thread recommends vendor)
    # ... relationship extraction logic
```

#### Task 1.4: Backlink Scanner for Obsidian Vault

**File:** `libs/gateway/backlink_scanner.py`

```python
import re
from pathlib import Path
from typing import List, Tuple

class BacklinkScanner:
    """
    Scans markdown files for wiki links and builds backlink index.
    """

    WIKI_LINK_PATTERN = r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]'  # [[target]] or [[target|display]]

    def scan_file(self, file_path: Path) -> List[Tuple[str, str, int]]:
        """
        Scan a file for wiki links.

        Returns: [(target_file, link_text, line_number), ...]
        """
        pass

    def rebuild_all_backlinks(self, vault_path: Path):
        """Scan entire vault and rebuild backlink index."""
        pass

    def get_orphan_files(self) -> List[Path]:
        """Find files with no backlinks (potential cleanup)."""
        pass
```

#### Task 1.5: Update Obsidian Memory Writer

**File:** `libs/gateway/obsidian_memory.py` (MODIFY)

When writing/updating documents, automatically:
1. Extract entities and register them
2. Register backlinks for any wiki links
3. Update frontmatter with entity IDs

```yaml
---
title: Syrian Hamster Research
created: 2026-01-25
updated: 2026-01-25
entities:
  - id: 42
    type: product
    name: Syrian Hamster
  - id: 15
    type: vendor
    name: Poppybee Hamstery
backlinks: 3  # Auto-updated count
---
```

---

## Part 2: Phase Visualization UI

### Current State

| Component | Location | Status |
|-----------|----------|--------|
| SSE Infrastructure | `apps/services/gateway/routers/thinking.py` | ✓ Works |
| ThinkingVisualizer | `static/app_v2.js` lines 3029+ | ✓ Works but wrong phases |
| HTML Stage Cards | `static/index.html` lines 229-354 | ✓ 6 cards (need 9) |
| Event Emission | `libs/gateway/unified_flow.py` | ⚠️ Inconsistent naming |

### Gap Analysis

**Current stage names (wrong):**
- `query_received`, `guide_analyzing`, `coordinator_planning`, `orchestrator_executing`, `guide_synthesizing`, `response_complete`

**Correct phase names (needed):**
- `phase_0_query_analyzer`
- `phase_1_reflection`
- `phase_2_context_gatherer`
- `phase_3_planner`
- `phase_4_executor`
- `phase_5_coordinator` (called per tool)
- `phase_6_synthesis`
- `phase_7_validation`
- `phase_8_save` (optional display)

### Implementation Tasks

#### Task 2.1: Update HTML Template with 9 Phase Cards

**File:** `static/index.html` (MODIFY)

Replace the 6-card thinking panel with 9 phase cards:

```html
<!-- Thinking Visualization Panel -->
<div id="thinking-panel" class="thinking-panel">
  <div class="thinking-header">
    <span class="thinking-title">Pipeline Progress</span>
    <button class="thinking-toggle" onclick="toggleThinkingPanel()">▼</button>
  </div>
  <div class="thinking-stages">
    <!-- Phase 0: Query Analyzer -->
    <div class="thinking-stage" data-stage="phase_0" style="display:none;">
      <div class="stage-icon" style="background:#68a8ef;">📩</div>
      <div class="stage-content">
        <div class="stage-header">
          <span class="stage-title">Query Analyzer</span>
          <span class="stage-badge pending">pending</span>
        </div>
        <div class="stage-details">
          <span class="stage-duration"></span>
          <span class="stage-reasoning"></span>
        </div>
        <div class="stage-confidence-bar"><div class="confidence-fill"></div></div>
      </div>
    </div>

    <!-- Phase 1: Reflection -->
    <div class="thinking-stage" data-stage="phase_1" style="display:none;">
      <div class="stage-icon" style="background:#9b6bef;">🤔</div>
      <div class="stage-content">
        <div class="stage-header">
          <span class="stage-title">Reflection</span>
          <span class="stage-badge pending">pending</span>
        </div>
        <div class="stage-details">
          <span class="stage-duration"></span>
          <span class="stage-reasoning"></span>
        </div>
        <div class="stage-confidence-bar"><div class="confidence-fill"></div></div>
      </div>
    </div>

    <!-- Phase 2: Context Gatherer -->
    <div class="thinking-stage" data-stage="phase_2" style="display:none;">
      <div class="stage-icon" style="background:#6bef9b;">📚</div>
      <div class="stage-content">
        <div class="stage-header">
          <span class="stage-title">Context Gatherer</span>
          <span class="stage-badge pending">pending</span>
        </div>
        <div class="stage-details">
          <span class="stage-duration"></span>
          <span class="stage-reasoning"></span>
        </div>
        <div class="stage-confidence-bar"><div class="confidence-fill"></div></div>
      </div>
    </div>

    <!-- Phase 3: Planner -->
    <div class="thinking-stage" data-stage="phase_3" style="display:none;">
      <div class="stage-icon" style="background:#ffa500;">📋</div>
      <div class="stage-content">
        <div class="stage-header">
          <span class="stage-title">Planner</span>
          <span class="stage-badge pending">pending</span>
        </div>
        <div class="stage-details">
          <span class="stage-duration"></span>
          <span class="stage-reasoning"></span>
        </div>
        <div class="stage-confidence-bar"><div class="confidence-fill"></div></div>
      </div>
    </div>

    <!-- Phase 4: Executor -->
    <div class="thinking-stage" data-stage="phase_4" style="display:none;">
      <div class="stage-icon" style="background:#ef6b9b;">⚙️</div>
      <div class="stage-content">
        <div class="stage-header">
          <span class="stage-title">Executor</span>
          <span class="stage-badge pending">pending</span>
        </div>
        <div class="stage-details">
          <span class="stage-duration"></span>
          <span class="stage-reasoning"></span>
        </div>
        <div class="stage-confidence-bar"><div class="confidence-fill"></div></div>
      </div>
    </div>

    <!-- Phase 5: Coordinator (Tool Calls) -->
    <div class="thinking-stage" data-stage="phase_5" style="display:none;">
      <div class="stage-icon" style="background:#ef9b6b;">🔧</div>
      <div class="stage-content">
        <div class="stage-header">
          <span class="stage-title">Coordinator</span>
          <span class="stage-badge pending">pending</span>
        </div>
        <div class="stage-details">
          <span class="stage-duration"></span>
          <span class="stage-reasoning"></span>
        </div>
        <div class="stage-confidence-bar"><div class="confidence-fill"></div></div>
        <!-- Tool call sub-items -->
        <div class="tool-calls"></div>
      </div>
    </div>

    <!-- Phase 6: Synthesis -->
    <div class="thinking-stage" data-stage="phase_6" style="display:none;">
      <div class="stage-icon" style="background:#6befa8;">✨</div>
      <div class="stage-content">
        <div class="stage-header">
          <span class="stage-title">Synthesis</span>
          <span class="stage-badge pending">pending</span>
        </div>
        <div class="stage-details">
          <span class="stage-duration"></span>
          <span class="stage-reasoning"></span>
        </div>
        <div class="stage-confidence-bar"><div class="confidence-fill"></div></div>
      </div>
    </div>

    <!-- Phase 7: Validation -->
    <div class="thinking-stage" data-stage="phase_7" style="display:none;">
      <div class="stage-icon" style="background:#a8ef6b;">✓</div>
      <div class="stage-content">
        <div class="stage-header">
          <span class="stage-title">Validation</span>
          <span class="stage-badge pending">pending</span>
        </div>
        <div class="stage-details">
          <span class="stage-duration"></span>
          <span class="stage-reasoning"></span>
        </div>
        <div class="stage-confidence-bar"><div class="confidence-fill"></div></div>
      </div>
    </div>

    <!-- Phase 8: Complete -->
    <div class="thinking-stage" data-stage="phase_8" style="display:none;">
      <div class="stage-icon" style="background:#7fd288;">✅</div>
      <div class="stage-content">
        <div class="stage-header">
          <span class="stage-title">Complete</span>
          <span class="stage-badge pending">pending</span>
        </div>
        <div class="stage-details">
          <span class="stage-duration"></span>
          <span class="stage-reasoning"></span>
        </div>
      </div>
    </div>
  </div>
</div>
```

#### Task 2.2: Update ThinkingVisualizer JavaScript

**File:** `static/app_v2.js` (MODIFY)

```javascript
class ThinkingVisualizer {
  constructor() {
    this.stages = {};
    this.startTime = null;
    this.traceId = null;

    // Phase configuration
    this.phaseConfig = {
      phase_0: { name: 'Query Analyzer', icon: '📩', color: '#68a8ef' },
      phase_1: { name: 'Reflection', icon: '🤔', color: '#9b6bef' },
      phase_2: { name: 'Context Gatherer', icon: '📚', color: '#6bef9b' },
      phase_3: { name: 'Planner', icon: '📋', color: '#ffa500' },
      phase_4: { name: 'Executor', icon: '⚙️', color: '#ef6b9b' },
      phase_5: { name: 'Coordinator', icon: '🔧', color: '#ef9b6b' },
      phase_6: { name: 'Synthesis', icon: '✨', color: '#6befa8' },
      phase_7: { name: 'Validation', icon: '✓', color: '#a8ef6b' },
      phase_8: { name: 'Complete', icon: '✅', color: '#7fd288' }
    };
  }

  updateStage(event) {
    // Extract phase from stage name (e.g., "phase_3_planner" -> "phase_3")
    const phaseMatch = event.stage.match(/^(phase_\d)/);
    if (!phaseMatch) return;

    const phaseKey = phaseMatch[1];
    const stageEl = document.querySelector(`.thinking-stage[data-stage="${phaseKey}"]`);
    if (!stageEl) return;

    // Show the stage
    stageEl.style.display = 'flex';

    // Update status badge
    const badge = stageEl.querySelector('.stage-badge');
    badge.textContent = event.status;
    badge.className = `stage-badge ${event.status}`;

    // Update reasoning
    if (event.reasoning) {
      stageEl.querySelector('.stage-reasoning').textContent = event.reasoning;
    }

    // Update duration
    if (event.duration_ms) {
      stageEl.querySelector('.stage-duration').textContent = `${event.duration_ms}ms`;
    }

    // Update confidence bar
    if (event.confidence !== undefined) {
      const fill = stageEl.querySelector('.confidence-fill');
      fill.style.width = `${event.confidence * 100}%`;
    }

    // Handle tool calls for Phase 5
    if (phaseKey === 'phase_5' && event.details?.tool) {
      this.addToolCall(stageEl, event.details);
    }
  }

  addToolCall(stageEl, details) {
    const toolCallsContainer = stageEl.querySelector('.tool-calls');
    const toolEl = document.createElement('div');
    toolEl.className = 'tool-call-item';
    toolEl.innerHTML = `
      <span class="tool-name">${details.tool}</span>
      <span class="tool-status ${details.status || 'pending'}">${details.status || 'running'}</span>
      ${details.duration_ms ? `<span class="tool-duration">${details.duration_ms}ms</span>` : ''}
    `;
    toolCallsContainer.appendChild(toolEl);
  }

  reset() {
    document.querySelectorAll('.thinking-stage').forEach(el => {
      el.style.display = 'none';
      el.querySelector('.stage-badge').textContent = 'pending';
      el.querySelector('.stage-badge').className = 'stage-badge pending';
      el.querySelector('.stage-reasoning').textContent = '';
      el.querySelector('.stage-duration').textContent = '';
      const fill = el.querySelector('.confidence-fill');
      if (fill) fill.style.width = '0%';
      const toolCalls = el.querySelector('.tool-calls');
      if (toolCalls) toolCalls.innerHTML = '';
    });
  }
}
```

#### Task 2.3: Emit Phase Events from unified_flow.py

**File:** `libs/gateway/unified_flow.py` (MODIFY)

Add event emission at each phase boundary:

```python
from apps.services.gateway.services.thinking import emit_thinking_event, ThinkingEvent

# At start of each phase:
async def _emit_phase_event(
    self,
    trace_id: str,
    phase: int,
    status: str,
    reasoning: str = "",
    confidence: float = 0.0,
    details: Dict = None,
    duration_ms: int = 0
):
    """Emit a thinking event for UI visualization."""
    phase_names = {
        0: "query_analyzer",
        1: "reflection",
        2: "context_gatherer",
        3: "planner",
        4: "executor",
        5: "coordinator",
        6: "synthesis",
        7: "validation",
        8: "complete"
    }

    await emit_thinking_event(ThinkingEvent(
        trace_id=trace_id,
        stage=f"phase_{phase}_{phase_names.get(phase, 'unknown')}",
        status=status,
        confidence=confidence,
        duration_ms=duration_ms,
        details=details or {},
        reasoning=reasoning,
        timestamp=time.time()
    ))

# Usage in handle_request:
async def handle_request(self, ...):
    # Phase 0
    await self._emit_phase_event(trace_id, 0, "active", "Analyzing query intent")
    query_analysis = await query_analyzer.analyze(...)
    await self._emit_phase_event(trace_id, 0, "completed",
        f"Intent: {query_analysis.intent}",
        confidence=0.9,
        duration_ms=int((time.time() - phase_start) * 1000))

    # Phase 1
    await self._emit_phase_event(trace_id, 1, "active", "Checking if clarification needed")
    # ... reflection logic
    await self._emit_phase_event(trace_id, 1, "completed",
        f"Decision: {decision}",
        confidence=confidence)

    # ... etc for all phases
```

#### Task 2.4: Add Tool Call Events

When Coordinator executes tools, emit sub-events:

```python
# In _coordinator_execute_command or _execute_tool:
await self._emit_phase_event(trace_id, 5, "active",
    f"Executing: {tool_name}",
    details={"tool": tool_name, "args": tool_args, "status": "running"})

result = await self._execute_tool(tool_name, tool_args, ...)

await self._emit_phase_event(trace_id, 5, "active",
    f"Completed: {tool_name}",
    details={
        "tool": tool_name,
        "status": "success" if result.get("status") == "success" else "error",
        "duration_ms": result.get("duration_ms", 0)
    })
```

---

## Part 3: Compounding Context

### Current State

Documents are written once and rarely updated. New information creates new documents rather than enriching existing ones.

### Goal

Entity-centric documents that **accumulate** information as new data arrives:

```markdown
# Syrian Hamster

## Summary
Small rodent popular as pet. Price range: $25-100.

## Known Vendors
- [[vendor:Poppybee Hamstery]] - $75 (added turn 64)
- [[vendor:Hamster Haven]] - $50 (added turn 89)
- [[vendor:Petco]] - $25 (added turn 102)

## Mentions
- [[turn:64]] - User researched breeders
- [[turn:89]] - Compared prices
- [[turn:102]] - Found local option

## Properties
| Property | Value | Source | Updated |
|----------|-------|--------|---------|
| price_range | $25-100 | research | 2026-01-25 |
| lifespan | 2-3 years | wikipedia | 2026-01-20 |
| care_level | easy | multiple | 2026-01-25 |

## Related Topics
- [[Hamster Care]]
- [[Small Pets]]
- [[Rodent Breeders]]
```

### Implementation Tasks

#### Task 3.1: Create Entity Document Template

**File:** `libs/gateway/entity_document.py`

```python
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime

@dataclass
class EntityDocument:
    """
    Manages entity-centric documents that accumulate information.
    """
    entity_type: str
    canonical_name: str
    entity_id: int

    # Accumulated data
    summary: str = ""
    properties: Dict[str, Dict] = field(default_factory=dict)  # {name: {value, source, updated}}
    related_entities: List[Dict] = field(default_factory=list)  # [{id, type, name, relationship}]
    mentions: List[Dict] = field(default_factory=list)  # [{turn, context, date}]

    def add_property(self, name: str, value: str, source: str):
        """Add or update a property."""
        self.properties[name] = {
            "value": value,
            "source": source,
            "updated": datetime.now().isoformat()
        }

    def add_mention(self, turn_number: int, context: str):
        """Record a new mention of this entity."""
        self.mentions.append({
            "turn": turn_number,
            "context": context[:200],
            "date": datetime.now().isoformat()
        })

    def add_related_entity(self, entity_id: int, entity_type: str,
                          name: str, relationship: str):
        """Add a related entity."""
        # Avoid duplicates
        for rel in self.related_entities:
            if rel["id"] == entity_id and rel["relationship"] == relationship:
                return

        self.related_entities.append({
            "id": entity_id,
            "type": entity_type,
            "name": name,
            "relationship": relationship
        })

    def to_markdown(self) -> str:
        """Generate markdown document."""
        lines = [
            f"# {self.canonical_name}",
            "",
            f"**Type:** {self.entity_type}",
            f"**Entity ID:** {self.entity_id}",
            "",
        ]

        if self.summary:
            lines.extend(["## Summary", "", self.summary, ""])

        if self.properties:
            lines.extend(["## Properties", "", "| Property | Value | Source | Updated |", "|----------|-------|--------|---------|"])
            for name, data in self.properties.items():
                lines.append(f"| {name} | {data['value']} | {data['source']} | {data['updated'][:10]} |")
            lines.append("")

        if self.related_entities:
            # Group by relationship type
            by_rel = {}
            for rel in self.related_entities:
                by_rel.setdefault(rel["relationship"], []).append(rel)

            lines.append("## Relationships")
            lines.append("")
            for rel_type, entities in by_rel.items():
                lines.append(f"### {rel_type.replace('_', ' ').title()}")
                for ent in entities:
                    lines.append(f"- [[{ent['type']}:{ent['name']}]]")
                lines.append("")

        if self.mentions:
            lines.extend(["## Mentions", ""])
            for mention in self.mentions[-10:]:  # Last 10 mentions
                lines.append(f"- [[turn:{mention['turn']}]] ({mention['date'][:10]}): {mention['context'][:50]}...")
            lines.append("")

        return "\n".join(lines)

    def save(self, vault_path: Path):
        """Save to obsidian vault."""
        # Determine path based on entity type
        type_dirs = {
            "vendor": "Knowledge/Vendors",
            "product": "Knowledge/Products",
            "site": "Knowledge/Sites",
            "topic": "Knowledge/Topics",
            "person": "Knowledge/People"
        }

        dir_path = vault_path / type_dirs.get(self.entity_type, "Knowledge/Other")
        dir_path.mkdir(parents=True, exist_ok=True)

        # Sanitize filename
        filename = self.canonical_name.lower().replace(" ", "-").replace("/", "-")
        file_path = dir_path / f"{filename}.md"

        file_path.write_text(self.to_markdown())
        return file_path
```

#### Task 3.2: Auto-Update Entity Documents on New Research

**File:** `libs/gateway/entity_updater.py`

```python
class EntityUpdater:
    """
    Updates entity documents when new information is discovered.
    """

    def __init__(self, kg: KnowledgeGraphDB, vault_path: Path):
        self.kg = kg
        self.vault_path = vault_path

    def process_research_results(self, results: Dict, turn_number: int):
        """
        Process research results and update relevant entity documents.
        """
        # 1. Extract entities from results
        extractor = EntityExtractor()
        entities = extractor.extract_from_research(results)

        for entity in entities:
            # 2. Find or create entity in knowledge graph
            existing = self.kg.find_entity(entity.canonical_name, entity.entity_type)

            if existing:
                entity_id = existing.id
                # Load existing document
                doc = self._load_entity_document(existing)
            else:
                # Create new entity
                entity_id = self.kg.add_entity(
                    entity.entity_type,
                    entity.canonical_name,
                    turn_number=turn_number
                )
                doc = EntityDocument(
                    entity_type=entity.entity_type,
                    canonical_name=entity.canonical_name,
                    entity_id=entity_id
                )

            # 3. Update document with new information
            for prop_name, prop_value in entity.properties.items():
                doc.add_property(prop_name, prop_value, f"turn_{turn_number}")

            doc.add_mention(turn_number, entity.context)

            # 4. Save updated document
            doc.save(self.vault_path)

            # 5. Register backlinks
            self._update_backlinks(doc)

    def _load_entity_document(self, entity: Entity) -> EntityDocument:
        """Load existing entity document or create new one."""
        pass

    def _update_backlinks(self, doc: EntityDocument):
        """Scan document and update backlink index."""
        pass
```

#### Task 3.3: Integrate with Phase 7 (Save)

**File:** `libs/gateway/unified_flow.py` (MODIFY)

In Phase 7, after saving the turn, update entity documents:

```python
# In _phase7_save or equivalent:
async def _update_knowledge_graph(
    self,
    context_doc: ContextDocument,
    turn_number: int,
    tool_results: List[Dict]
):
    """Update knowledge graph with information from this turn."""
    from libs.gateway.entity_updater import EntityUpdater
    from libs.gateway.knowledge_graph_db import get_knowledge_graph_db

    kg = get_knowledge_graph_db()
    updater = EntityUpdater(kg, self.obsidian_vault_path)

    # Process research results
    for result in tool_results:
        if result.get("tool") == "internet.research":
            updater.process_research_results(result.get("result", {}), turn_number)

    # Rebuild backlink index for updated files
    kg.rebuild_backlink_index()
```

---

## Part 4: Coordinator Verification

### Current State (Already Good)

Based on the research, the Coordinator already implements proper tool-using agent patterns:

✅ **LLM-based tool selection** (not hardcoded)
✅ **Unified tool registry** (ToolCatalog with schema validation)
✅ **Proper reasoning loop** (Executor → Coordinator → Executor)
✅ **MCP abstraction** (all tools dispatch through `_execute_tool()`)
✅ **Mode enforcement** (chat vs code tools)
✅ **Claims extraction** (evidence chains)

### Minor Improvements

#### Task 4.1: Add Tool Execution Metrics

Track tool call success rates, durations, and errors:

```python
# In _execute_tool:
from libs.gateway.tool_metrics import record_tool_execution

start_time = time.time()
try:
    result = await self._execute_tool_impl(tool_name, tool_args, ...)
    record_tool_execution(
        tool_name=tool_name,
        status="success",
        duration_ms=int((time.time() - start_time) * 1000),
        turn_number=context_doc.turn_number
    )
except Exception as e:
    record_tool_execution(
        tool_name=tool_name,
        status="error",
        error=str(e),
        duration_ms=int((time.time() - start_time) * 1000),
        turn_number=context_doc.turn_number
    )
    raise
```

#### Task 4.2: Tool Registry Discovery Endpoint

Add API endpoint to list available tools:

```python
# In apps/services/gateway/routers/tools.py (NEW)
@router.get("/v1/tools")
async def list_tools(mode: str = "chat"):
    """List available tools for the current mode."""
    from apps.services.gateway.tool_catalog import get_tool_catalog

    catalog = get_tool_catalog()
    tools = catalog.get_tools_for_mode(mode)

    return {
        "mode": mode,
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "parameters": [p.to_dict() for p in t.schema],
                "keywords": t.keywords
            }
            for t in tools
        ]
    }
```

---

## Implementation Order

### Phase 1: Foundation (Week 1)

1. **Task 1.1** - Create `knowledge_graph_db.py` with schema
2. **Task 1.2** - Create `entity_extractor.py` with pattern matching
3. **Task 1.4** - Create `backlink_scanner.py`
4. **Task 2.3** - Add `_emit_phase_event` to unified_flow.py

### Phase 2: UI (Week 2)

5. **Task 2.1** - Update HTML with 9 phase cards
6. **Task 2.2** - Update ThinkingVisualizer JavaScript
7. **Task 2.4** - Add tool call events
8. Test phase visualization end-to-end

### Phase 3: Knowledge Graph Integration (Week 3)

9. **Task 1.3** - Integrate entity extraction into research flow
10. **Task 1.5** - Update obsidian memory writer
11. **Task 3.1** - Create entity document template
12. **Task 3.2** - Create entity updater

### Phase 4: Compounding Context (Week 4)

13. **Task 3.3** - Integrate with Phase 7
14. **Task 4.1** - Add tool execution metrics
15. **Task 4.2** - Add tool discovery endpoint
16. End-to-end testing with real queries

---

## File Summary

### New Files

| File | Purpose |
|------|---------|
| `libs/gateway/knowledge_graph_db.py` | Entity/relationship/backlink database |
| `libs/gateway/entity_extractor.py` | Extract entities from text/research |
| `libs/gateway/backlink_scanner.py` | Scan and index wiki links |
| `libs/gateway/entity_document.py` | Entity-centric document template |
| `libs/gateway/entity_updater.py` | Auto-update entity docs on new research |
| `libs/gateway/tool_metrics.py` | Tool execution tracking |
| `apps/services/gateway/routers/tools.py` | Tool discovery API |
| `panda_system_docs/knowledge_graph.db` | SQLite database |

### Modified Files

| File | Changes |
|------|---------|
| `static/index.html` | 9 phase cards instead of 6 |
| `static/app_v2.js` | Updated ThinkingVisualizer |
| `libs/gateway/unified_flow.py` | Phase event emission, entity extraction integration |
| `libs/gateway/obsidian_memory.py` | Backlink registration, entity ID frontmatter |

---

## Success Criteria

1. **Knowledge Graph**
   - [ ] Entities extracted from research results
   - [ ] Bidirectional backlinks indexed
   - [ ] Entity documents auto-update with new information
   - [ ] Can query "all vendors selling product X"

2. **Phase Visualization**
   - [ ] All 9 phases visible in UI
   - [ ] Real-time status updates via SSE
   - [ ] Tool calls shown under Coordinator phase
   - [ ] Duration and confidence displayed

3. **Compounding Context**
   - [ ] Entity documents grow over time
   - [ ] New mentions appended to existing docs
   - [ ] Properties updated with latest values
   - [ ] Relationship graph navigable

4. **Coordinator**
   - [ ] Tool metrics tracked
   - [ ] Tool discovery endpoint works
   - [ ] Existing functionality preserved

---

## Testing Plan

### Unit Tests

```python
# tests/test_knowledge_graph.py
def test_entity_creation():
    kg = KnowledgeGraphDB(":memory:")
    entity_id = kg.add_entity("vendor", "Poppybee Hamstery")
    assert entity_id > 0

def test_backlink_indexing():
    kg = KnowledgeGraphDB(":memory:")
    kg.add_backlink("a.md", "b.md", "[[b]]")
    backlinks = kg.get_backlinks_to("b.md")
    assert len(backlinks) == 1

def test_entity_extraction():
    extractor = EntityExtractor()
    entities = extractor.extract_from_text("Buy from Poppybee Hamstery for $75")
    assert any(e.entity_type == "vendor" for e in entities)
    assert any(e.properties.get("price") == "$75" for e in entities)
```

### Integration Tests

```python
# tests/test_phase_visualization.py
async def test_phase_events_emitted():
    # Run a query and verify all phase events received via SSE
    pass

# tests/test_compounding_context.py
async def test_entity_document_updates():
    # Run two queries about same topic, verify entity doc updated
    pass
```

### Manual Testing

1. Query: "find syrian hamsters for sale"
2. Verify: Entity docs created for vendors found
3. Query: "what about from petco?"
4. Verify: Petco added to existing hamster entity doc
5. Check: Backlinks from hamster doc to vendor docs

---

**End of Plan**
