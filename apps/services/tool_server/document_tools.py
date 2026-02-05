"""
Document Management Tools for Session-Focused Architecture

Provides unified API for creating and managing:
- Research Briefs
- Source Snapshots
- Task Briefs
"""

import json
import logging
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class DocumentManager:
    """
    Manages session-scoped documents with snapshot compression.
    """

    def __init__(self, workspace_dir: str = "panda_system_docs/sessions"):
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def create_research_brief(
        self,
        session_id: str,
        query: str,
        research_goal: str,
        token_budget: int = 9600
    ) -> str:
        """
        Create a new research brief document.

        Returns:
            Research ID (e.g., "R1")
        """
        session_dir = self.workspace_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # Find next research ID
        existing_research = list(session_dir.glob("Research_R*.md"))
        research_num = len(existing_research) + 1
        research_id = f"R{research_num}"

        # Create research brief
        brief_path = session_dir / f"Research_{research_id}.md"

        content = f"""# Research Brief: {research_id}

**Query**: {query}
**Goal**: {research_goal}
**Created**: {datetime.utcnow().isoformat()}
**Token Budget**: {token_budget}

## Strategy

DuckDuckGo search → Visit top candidates → Extract relevant information

## Progress

| Page | URL | Status | Relevance | Tokens |
|------|-----|--------|-----------|--------|

**Sources Processed**: 0
**Sources Accepted**: 0
**Tokens Used**: 0 / {token_budget}

## Synthesis

(Pending - will be generated after source extraction)
"""

        brief_path.write_text(content)

        logger.info(f"Created research brief: {research_id} in session {session_id}")

        return research_id

    def save_source_snapshot(
        self,
        session_id: str,
        research_id: str,
        url: str,
        extracted_info: Dict[str, Any],
        summary: str,
        relevance_score: float,
        tokens_used: int
    ) -> str:
        """
        Save source snapshot with compression.

        Saves full extraction to disk, keeps only summary in memory.

        Returns:
            Snapshot ID
        """
        session_dir = self.workspace_dir / session_id
        research_dir = session_dir / f"research_{research_id.lower()}"
        research_dir.mkdir(parents=True, exist_ok=True)

        # Generate snapshot ID from URL
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        domain = url.split("//")[1].split("/")[0] if "//" in url else "unknown"
        snapshot_id = f"{domain}_{url_hash}"

        # Save full extraction
        snapshot_path = research_dir / f"{snapshot_id}_full.json"
        snapshot_data = {
            "url": url,
            "extracted_info": extracted_info,
            "summary": summary,
            "relevance_score": relevance_score,
            "tokens_used": tokens_used,
            "captured_at": datetime.utcnow().isoformat()
        }
        snapshot_path.write_text(json.dumps(snapshot_data, indent=2))

        # Save compressed summary
        summary_path = research_dir / f"{snapshot_id}_summary.md"
        summary_content = f"""# {domain}

**URL**: {url}
**Relevance**: {relevance_score:.2f}
**Captured**: {datetime.utcnow().isoformat()}

## Summary

{summary}
"""
        summary_path.write_text(summary_content)

        # Update research brief progress table
        self._update_research_progress(
            session_id,
            research_id,
            url,
            relevance_score,
            tokens_used
        )

        logger.info(
            f"Saved snapshot: {snapshot_id} for {research_id} "
            f"(relevance: {relevance_score:.2f})"
        )

        return snapshot_id

    def load_source_summaries(
        self,
        session_id: str,
        research_id: str
    ) -> List[Dict[str, Any]]:
        """
        Load ONLY summaries for synthesis (not full extractions).

        This enables processing 10-12 pages while using only ~500 tokens
        instead of 10,000+ tokens.
        """
        session_dir = self.workspace_dir / session_id
        research_dir = session_dir / f"research_{research_id.lower()}"

        if not research_dir.exists():
            logger.warning(f"Research directory not found: {research_dir}")
            return []

        summaries = []
        for summary_path in research_dir.glob("*_summary.md"):
            # Load corresponding full data for metadata
            snapshot_id = summary_path.stem.replace("_summary", "")
            full_path = research_dir / f"{snapshot_id}_full.json"

            if full_path.exists():
                full_data = json.loads(full_path.read_text())
                summaries.append({
                    "url": full_data["url"],
                    "summary": full_data["summary"],
                    "relevance_score": full_data["relevance_score"],
                    "snapshot_id": snapshot_id
                })

        logger.info(
            f"Loaded {len(summaries)} source summaries for {research_id} "
            f"(~{len(summaries) * 100} tokens vs ~{len(summaries) * 1500} for full)"
        )

        return summaries

    def save_synthesis(
        self,
        session_id: str,
        research_id: str,
        synthesis: Dict[str, Any]
    ):
        """Save research synthesis to brief."""
        brief_path = self.workspace_dir / session_id / f"Research_{research_id}.md"

        if not brief_path.exists():
            logger.warning(f"Research brief not found: {brief_path}")
            return

        # Read current brief
        content = brief_path.read_text()

        # Replace synthesis section
        synthesis_md = f"""## Synthesis

**Answer**: {synthesis.get('answer', 'N/A')}

**Confidence**: {synthesis.get('confidence', 0):.2f}

**Key Findings**:
{synthesis.get('key_findings', '')}

**Generated**: {datetime.utcnow().isoformat()}
"""

        # Find and replace synthesis section
        if "## Synthesis" in content:
            parts = content.split("## Synthesis")
            content = parts[0] + synthesis_md
        else:
            content += "\n" + synthesis_md

        brief_path.write_text(content)

        logger.info(f"Saved synthesis to {research_id}")

    def _update_research_progress(
        self,
        session_id: str,
        research_id: str,
        url: str,
        relevance_score: float,
        tokens_used: int
    ):
        """Update progress table in research brief."""
        brief_path = self.workspace_dir / session_id / f"Research_{research_id}.md"

        if not brief_path.exists():
            return

        content = brief_path.read_text()

        # Extract domain from URL
        domain = url.split("//")[1].split("/")[0] if "//" in url else url[:30]

        # Find progress table and add row
        new_row = f"| {len(content.splitlines())} | {domain} | ✅ | {relevance_score:.2f} | {tokens_used} |"

        # Insert before "**Sources Processed**" line
        if "**Sources Processed**:" in content:
            lines = content.splitlines()
            new_lines = []
            for line in lines:
                if line.startswith("**Sources Processed**:"):
                    # Update counts
                    current = int(line.split(":")[1].strip())
                    new_lines.append(f"**Sources Processed**: {current + 1}")
                elif line.startswith("**Sources Accepted**:"):
                    current = int(line.split(":")[1].strip())
                    new_lines.append(f"**Sources Accepted**: {current + 1}")
                elif line.startswith("**Tokens Used**:"):
                    parts = line.split(":")
                    budget_part = parts[1].strip().split("/")
                    current_tokens = int(budget_part[0].strip())
                    budget = budget_part[1].strip()
                    new_lines.append(f"**Tokens Used**: {current_tokens + tokens_used} / {budget}")
                elif line.startswith("|------|"):
                    # Add new row after header separator
                    new_lines.append(line)
                    new_lines.append(new_row)
                else:
                    new_lines.append(line)

            content = "\n".join(new_lines)
            brief_path.write_text(content)

    def get_research_stats(
        self,
        session_id: str,
        research_id: str
    ) -> Dict[str, Any]:
        """Get research statistics."""
        research_dir = self.workspace_dir / session_id / f"research_{research_id.lower()}"

        if not research_dir.exists():
            return {
                "sources_processed": 0,
                "sources_accepted": 0,
                "tokens_used": 0
            }

        # Count snapshots
        snapshots = list(research_dir.glob("*_full.json"))

        total_tokens = 0
        for snapshot_path in snapshots:
            data = json.loads(snapshot_path.read_text())
            total_tokens += data.get("tokens_used", 0)

        return {
            "sources_processed": len(snapshots),
            "sources_accepted": len(snapshots),
            "tokens_used": total_tokens
        }


# Global document manager instance
_document_manager: Optional[DocumentManager] = None


def get_document_manager() -> DocumentManager:
    """Get global document manager instance."""
    global _document_manager
    if _document_manager is None:
        _document_manager = DocumentManager()
    return _document_manager
