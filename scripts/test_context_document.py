#!/usr/bin/env python3
"""
Test the ContextDocument accumulation pattern.
Simulates how context.md builds up through the 6 phases.
"""

from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Optional
import json
from datetime import datetime


class ContextDocument:
    """Manages the accumulating context.md document."""

    def __init__(self, turn_number: int, session_id: str, query: str):
        self.turn_number = turn_number
        self.session_id = session_id
        self.query = query  # Stored as §0, immutable
        self.sections: Dict[int, dict] = {}  # §1-4, §6-7 appended by each phase

    def append_section(self, section_num: int, title: str, content: str):
        """Append a new section to the document (§1-4, §6-7)."""
        if section_num < 1 or section_num > 7 or section_num == 5:
            raise ValueError("Sections must be 1-4 or 6-7 (§0 is query, §5 unused)")
        self.sections[section_num] = {"title": title, "content": content}

    def get_markdown(self) -> str:
        """Return complete markdown document with §0-§7."""
        md = f"# Context Document\n**Turn:** {self.turn_number}\n**Session:** {self.session_id}\n\n"
        md += "---\n\n## 0. User Query\n\n"
        md += f"{self.query}\n\n"
        for i in [1, 2, 3, 4, 6, 7]:
            if i in self.sections:
                md += f"---\n\n## {i}. {self.sections[i]['title']}\n\n"
                md += f"{self.sections[i]['content']}\n\n"
        return md.rstrip() + "\n"

    def save(self, turn_dir: Path):
        """Save to turn directory."""
        turn_dir.mkdir(parents=True, exist_ok=True)
        (turn_dir / "context.md").write_text(self.get_markdown())


def simulate_phase_2_context_gatherer(doc: ContextDocument):
    """Simulate Context Gatherer appending §2."""
    content = """### Session Preferences
- **budget:** online search for sale items
- **location:** online
- **favorite_hamster:** Syrian

### Relevant Memories
User previously expressed preference for Syrian hamsters (turn 620).

### Prior Turn Summary
Last turn discussed laptop shopping for NVIDIA GPUs.

### Retrieved Documents
| Source | Relevance | Summary |
|--------|-----------|---------|
| turns/turn_000620/context.md | 0.92 | User stated favorite hamster is Syrian |
| sessions/default/preferences.md | 0.88 | User preferences including favorite_hamster |

**Source References:**
- [1] turns/turn_000620/context.md - "User's favorite hamster preference"
- [2] sessions/default/preferences.md - "Stored user preferences\""""

    doc.append_section(2, "Gathered Context", content)


def simulate_phase_1_reflection(doc: ContextDocument):
    """Simulate Reflection appending §1."""
    content = """**Decision:** PROCEED
**Reasoning:** User is stating a preference, which can be acknowledged and saved directly.
**Route:** synthesis"""

    doc.append_section(1, "Reflection Decision", content)


def simulate_phase_3_planner(doc: ContextDocument):
    """Simulate Planner appending §3."""
    content = """**Goal:** Acknowledge user's hamster preference and confirm it will be remembered
**Intent:** preference
**Subtasks:**
1. Acknowledge the preference statement
2. Confirm the preference is saved

**Tools Required:** none
**Route To:** synthesis"""

    doc.append_section(3, "Task Plan", content)


def simulate_phase_4_coordinator(doc: ContextDocument):
    """Simulate Coordinator appending §4 (skipped for preference intent)."""
    # This phase is skipped when route_to = synthesis
    pass


def simulate_phase_6_synthesis(doc: ContextDocument):
    """Simulate Synthesis appending §6."""
    content = """**Response Preview:**
I've noted that your favorite hamster is the Syrian hamster. This preference has been saved and I'll remember it for future conversations.

**Validation Checklist:**
- [x] Claims match evidence (preference from §0)
- [x] Intent satisfied (preference acknowledged)
- [x] No hallucinations from prior context
- [x] Appropriate format (simple acknowledgment)"""

    doc.append_section(6, "Synthesis", content)


def main():
    print("=" * 60)
    print("Testing ContextDocument Accumulation Pattern")
    print("=" * 60)

    # Create document with user query as §0
    doc = ContextDocument(
        turn_number=743,
        session_id="default",
        query="my favorite hamster is the syrian hamster"
    )

    print("\n[Turn Start] Created context.md with §0 (query)")
    print("-" * 40)
    print(doc.get_markdown())

    # Phase 1: Reflection
    print("\n[Phase 1] Reflection appends §1")
    simulate_phase_1_reflection(doc)

    # Phase 2: Context Gatherer
    print("[Phase 2] Context Gatherer appends §2")
    simulate_phase_2_context_gatherer(doc)

    # Phase 3: Planner
    print("[Phase 3] Planner appends §3")
    simulate_phase_3_planner(doc)

    # Phase 4: Coordinator (skipped)
    print("[Phase 4] Coordinator skipped (no tools needed)")
    simulate_phase_4_coordinator(doc)

    # Phase 6: Synthesis
    print("[Phase 6] Synthesis appends §6")
    simulate_phase_6_synthesis(doc)

    print("\n" + "=" * 60)
    print("FINAL context.md")
    print("=" * 60)
    print(doc.get_markdown())

    # Save to test directory
    test_dir = Path("panda_system_docs/turns/turn_000743_test")
    doc.save(test_dir)
    print(f"\nSaved to: {test_dir}/context.md")

    # Also save a sample response.md
    response = "I've noted that your favorite hamster is the Syrian hamster. This preference has been saved and I'll remember it for future conversations."
    (test_dir / "response.md").write_text(response)
    print(f"Saved to: {test_dir}/response.md")

    # Save metadata
    metadata = {
        "turn_number": 743,
        "session_id": "default",
        "timestamp": datetime.now().timestamp(),
        "topic": "hamster preference",
        "intent": "preference",
        "tools_used": [],
        "claims_count": 0,
        "response_quality": 0.95,
        "keywords": ["hamster", "syrian", "favorite", "preference"]
    }
    (test_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    print(f"Saved to: {test_dir}/metadata.json")

    print("\n" + "=" * 60)
    print("Test complete! Check the files in:")
    print(f"  {test_dir}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
