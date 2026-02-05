"""Pandora research document management.

Architecture Reference:
    architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_ARCHITECTURE.md#4-researchmd-specification

Key Design:
    - Evergreen knowledge (facts that don't expire)
    - Time-sensitive data (prices, availability - 6 hour TTL)
    - JSON companion file for indexing in ResearchIndexDB
    - Linked from context.md §4 Tool Results

Purpose:
    Contains full research results from internet.research tool calls.
    Enables re-use of research across turns via ResearchIndexDB.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
import json


class ResearchManager:
    """Manages research.md documents.

    Research documents contain two types of knowledge:
    1. Evergreen: Facts that don't expire (specifications, features)
    2. Time-Sensitive: Data that expires (prices, availability)

    Time-sensitive data has a 6-hour TTL by default.
    """

    DEFAULT_TTL_HOURS = 6

    def __init__(self, turn_dir: Path):
        """
        Initialize research manager.

        Args:
            turn_dir: Turn directory
        """
        self.turn_dir = turn_dir
        self.research_path = turn_dir / "research.md"
        self.research_json_path = turn_dir / "research.json"

    def create(
        self,
        query: str,
        session_id: str,
        turn_number: int,
        topic: str,
        intent: str,
    ) -> None:
        """
        Create new research.md document.

        Args:
            query: Research query (original user query for context discipline)
            session_id: User session
            turn_number: Turn number
            topic: Inferred topic
            intent: Query intent
        """
        timestamp = datetime.now()
        expires = timestamp + timedelta(hours=self.DEFAULT_TTL_HOURS)

        content = f"""# Research Document
**ID:** research_{turn_number}_{timestamp.strftime('%Y%m%d%H%M%S')}
**Turn:** {turn_number}
**Session:** {session_id}
**Query:** {query}

## Metadata
- **Topic:** {topic}
- **Intent:** {intent}
- **Quality:** pending
- **Created:** {timestamp.isoformat()}
- **Expires:** {expires.isoformat()} (time-sensitive data)

## Evergreen Knowledge
*Facts that don't expire:*

(To be populated by research tool)

## Time-Sensitive Data
*Expires in {self.DEFAULT_TTL_HOURS} hours:*

(To be populated by research tool)

## Linked From
- [context.md](./context.md) §4 Tool Results

"""
        self.turn_dir.mkdir(parents=True, exist_ok=True)
        self.research_path.write_text(content)

        # Create JSON for indexing
        self._save_json({
            "id": f"research_{turn_number}_{timestamp.strftime('%Y%m%d%H%M%S')}",
            "turn_number": turn_number,
            "session_id": session_id,
            "query": query,
            "topic": topic,
            "intent": intent,
            "created_at": timestamp.isoformat(),
            "expires_at": expires.isoformat(),
            "quality": None,
            "findings_count": 0,
            "sources": [],
        })

    def exists(self) -> bool:
        """Check if research.md exists."""
        return self.research_path.exists()

    def append_evergreen(self, content: str) -> None:
        """
        Append evergreen knowledge.

        Evergreen knowledge includes facts that don't expire:
        - Product specifications
        - Technical details
        - Features and capabilities
        - General knowledge

        Args:
            content: Content to append
        """
        self._append_to_section("Evergreen Knowledge", content)

    def append_time_sensitive(self, content: str) -> None:
        """
        Append time-sensitive data.

        Time-sensitive data expires after 6 hours:
        - Prices
        - Availability
        - Stock status
        - Promotions

        Args:
            content: Content to append
        """
        self._append_to_section("Time-Sensitive Data", content)

    def set_quality(self, quality: float) -> None:
        """
        Update quality score.

        Args:
            quality: Quality score (0.0 to 1.0)
        """
        data = self._load_json()
        data["quality"] = quality
        self._save_json(data)

        # Also update in markdown
        content = self.research_path.read_text()
        content = content.replace("**Quality:** pending", f"**Quality:** {quality:.2f}")
        self.research_path.write_text(content)

    def add_findings(self, findings: list[dict]) -> None:
        """
        Add product/content findings.

        Args:
            findings: List of finding dicts with name, price, vendor, url, etc.
        """
        content = "\n### Current Listings\n"
        content += "| Product | Price | Vendor | URL |\n"
        content += "|---------|-------|--------|-----|\n"

        for finding in findings:
            name = finding.get("name", "Unknown")
            price = finding.get("price", "N/A")
            vendor = finding.get("vendor", "Unknown")
            url = finding.get("url", "#")
            content += f"| {name} | {price} | {vendor} | [link]({url}) |\n"

        content += "\n"
        self.append_time_sensitive(content)

        # Update JSON
        data = self._load_json()
        data["findings_count"] = data.get("findings_count", 0) + len(findings)
        self._save_json(data)

    def add_source(self, url: str, title: str, vendor: Optional[str] = None) -> None:
        """
        Add a source URL to the research.

        Args:
            url: Source URL
            title: Page title
            vendor: Optional vendor name
        """
        data = self._load_json()
        sources = data.get("sources", [])
        sources.append({
            "url": url,
            "title": title,
            "vendor": vendor,
            "visited_at": datetime.now().isoformat(),
        })
        data["sources"] = sources
        self._save_json(data)

    def add_claim(
        self,
        claim: str,
        confidence: float,
        source: str,
        is_evergreen: bool = True,
        ttl_hours: Optional[int] = None,
    ) -> None:
        """
        Add a claim with evidence.

        Args:
            claim: The claim text
            confidence: Confidence score (0.0 to 1.0)
            source: Source of the claim
            is_evergreen: True for evergreen, False for time-sensitive
            ttl_hours: TTL in hours (for time-sensitive claims)
        """
        if ttl_hours is None:
            ttl_hours = self.DEFAULT_TTL_HOURS if not is_evergreen else None

        claim_md = f"- **{claim}** (confidence: {confidence:.2f}, source: {source})"
        if ttl_hours:
            claim_md += f" [expires in {ttl_hours}h]"
        claim_md += "\n"

        if is_evergreen:
            self.append_evergreen(claim_md)
        else:
            self.append_time_sensitive(claim_md)

    def get_metadata(self) -> dict:
        """
        Get research metadata from JSON.

        Returns:
            Research metadata dict
        """
        return self._load_json()

    def is_expired(self) -> bool:
        """
        Check if time-sensitive data has expired.

        Returns:
            True if expired, False otherwise
        """
        data = self._load_json()
        expires_at = data.get("expires_at")
        if not expires_at:
            return False

        try:
            expires = datetime.fromisoformat(expires_at)
            return datetime.now() > expires
        except ValueError:
            return False

    def get_age_hours(self) -> float:
        """
        Get age of research in hours.

        Returns:
            Age in hours
        """
        data = self._load_json()
        created_at = data.get("created_at")
        if not created_at:
            return 0.0

        try:
            created = datetime.fromisoformat(created_at)
            delta = datetime.now() - created
            return delta.total_seconds() / 3600
        except ValueError:
            return 0.0

    def get_summary(self) -> dict:
        """
        Get a summary of the research document.

        Returns:
            Summary dict with key information
        """
        data = self._load_json()
        return {
            "id": data.get("id"),
            "topic": data.get("topic"),
            "intent": data.get("intent"),
            "quality": data.get("quality"),
            "age_hours": self.get_age_hours(),
            "expired": self.is_expired(),
            "findings_count": data.get("findings_count", 0),
            "sources_count": len(data.get("sources", [])),
        }

    def _append_to_section(self, section_name: str, content: str) -> None:
        """Append content to a named section."""
        if not self.research_path.exists():
            return

        current = self.research_path.read_text()

        # Find section
        section_marker = f"## {section_name}"
        idx = current.find(section_marker)
        if idx == -1:
            return

        # Find next section or end
        next_section_idx = current.find("\n## ", idx + len(section_marker))
        if next_section_idx == -1:
            # Append at end
            self.research_path.write_text(current + "\n" + content)
        else:
            # Insert before next section
            updated = current[:next_section_idx] + "\n" + content + current[next_section_idx:]
            self.research_path.write_text(updated)

    def _save_json(self, data: dict) -> None:
        """Save research metadata JSON."""
        self.turn_dir.mkdir(parents=True, exist_ok=True)
        with open(self.research_json_path, "w") as f:
            json.dump(data, f, indent=2)

    def _load_json(self) -> dict:
        """Load research metadata JSON."""
        if not self.research_json_path.exists():
            return {}
        with open(self.research_json_path) as f:
            return json.load(f)
