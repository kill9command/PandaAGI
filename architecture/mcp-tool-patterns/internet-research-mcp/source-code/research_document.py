"""
Research Document: Schema and writer for research.md files.

Research documents store the results of internet.research tool calls in a
structured, searchable format. They contain:
- Metadata (topic, quality scores, confidence)
- Evergreen knowledge (facts that don't expire)
- Time-sensitive data (prices, availability with TTL)

This enables topic-based retrieval instead of exact query matching,
so related queries can benefit from prior research.
"""

import json
import math
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


# =============================================================================
# Decay Rates and Confidence Floors
# =============================================================================

DECAY_RATES = {
    'price': 0.10,           # Prices decay fast (50% confidence after ~7 days)
    'availability': 0.15,    # Stock status decays fastest
    'vendor_info': 0.02,     # Vendor reliability decays slowly
    'general_fact': 0.005,   # Evergreen facts barely decay
}

CONFIDENCE_FLOOR = {
    'price': 0.20,
    'availability': 0.10,
    'vendor_info': 0.60,
    'general_fact': 0.80,
}

DEFAULT_TTL_HOURS = {
    'price': 6,
    'availability': 2,
    'vendor_info': 168,      # 1 week
    'general_fact': 720,     # 30 days
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class TopicClassification:
    """Topic classification for a research document."""
    primary_topic: str                    # e.g., "pet.hamster.syrian_hamster"
    keywords: List[str] = field(default_factory=list)
    intent: str = "informational"         # transactional, informational
    content_types: List[str] = field(default_factory=list)  # What info types are present

    @property
    def depth(self) -> int:
        """Topic hierarchy depth."""
        return len(self.primary_topic.split('.'))

    @property
    def parent_topic(self) -> Optional[str]:
        """Parent topic path."""
        parts = self.primary_topic.split('.')
        if len(parts) > 1:
            return '.'.join(parts[:-1])
        return None


# =============================================================================
# Content Type Constants
# =============================================================================

# What types of information can research contain?
CONTENT_TYPES = {
    # Purchase-related
    "purchase_info": ["buy", "price", "cost", "sale", "shop", "purchase", "order", "store", "retailer"],
    "vendor_info": ["breeder", "seller", "store", "shop", "retailer", "vendor", "source"],
    "availability_info": ["stock", "available", "in stock", "shipping", "delivery"],

    # Care-related
    "care_info": ["care", "caring", "take care", "look after", "maintain", "keeping"],
    "feeding_info": ["feed", "food", "diet", "eat", "nutrition", "meal"],
    "housing_info": ["cage", "enclosure", "habitat", "bedding", "housing", "tank", "terrarium"],
    "health_info": ["health", "vet", "veterinary", "sick", "disease", "symptom", "treatment"],

    # Behavioral
    "behavior_info": ["behavior", "behaviour", "temperament", "personality", "handling"],
    "lifespan_info": ["lifespan", "life span", "live", "age", "years old"],

    # Comparison
    "comparison_info": ["compare", "comparison", "versus", "vs", "difference", "better"],
    "review_info": ["review", "rating", "recommendation", "best", "top"],
}


def classify_query_content_needs(query: str) -> List[str]:
    """
    Classify what content types a query needs.

    Example:
        "Syrian hamsters for sale" → ["purchase_info", "vendor_info", "availability_info"]
        "how to care for Syrian hamster" → ["care_info"]
        "what do hamsters eat" → ["feeding_info", "care_info"]
    """
    query_lower = query.lower()
    needs = []

    for content_type, keywords in CONTENT_TYPES.items():
        if any(kw in query_lower for kw in keywords):
            needs.append(content_type)

    # Default: if nothing matched, it's probably informational
    if not needs:
        # Guess based on common patterns
        if any(w in query_lower for w in ["what", "how", "why", "when", "where"]):
            needs = ["care_info"]  # General informational
        else:
            needs = ["purchase_info"]  # Default for product queries

    return needs


def classify_content_types_from_findings(findings: List[Dict]) -> List[str]:
    """
    Classify what content types are present in research findings.

    Examines the actual content to determine what information was gathered.
    """
    content_types = set()

    for finding in findings:
        text = " ".join([
            str(finding.get("name", "")),
            str(finding.get("description", "")),
            str(finding.get("content", "")),
            " ".join(finding.get("strengths", [])),
            " ".join(finding.get("weaknesses", []))
        ]).lower()

        # Check what types of content are present
        for content_type, keywords in CONTENT_TYPES.items():
            if any(kw in text for kw in keywords):
                content_types.add(content_type)

        # Price indicates purchase_info
        if finding.get("price"):
            content_types.add("purchase_info")
            content_types.add("availability_info")

        # Vendor indicates vendor_info
        if finding.get("vendor"):
            content_types.add("vendor_info")

    return list(content_types)


@dataclass
class QualityScores:
    """Quality metrics for research."""
    completeness: float = 0.0      # How complete is the research (0-1)
    source_quality: float = 0.0    # Quality of sources consulted (0-1)
    extraction_success: float = 0.0  # Success rate of data extraction (0-1)

    @property
    def overall(self) -> float:
        """Weighted overall quality score."""
        return (
            self.completeness * 0.4 +
            self.source_quality * 0.35 +
            self.extraction_success * 0.25
        )


@dataclass
class ConfidenceInfo:
    """Confidence tracking with decay."""
    initial: float = 0.85
    current: float = 0.85
    decay_rate: float = 0.02      # Per day
    content_type: str = "general_fact"

    def calculate_current(self, created_at: datetime) -> float:
        """Calculate decayed confidence."""
        now = datetime.now(timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        days_old = (now - created_at).total_seconds() / 86400

        decay_rate = DECAY_RATES.get(self.content_type, self.decay_rate)
        floor = CONFIDENCE_FLOOR.get(self.content_type, 0.50)

        # Exponential decay with floor
        decayed = floor + (self.initial - floor) * math.exp(-decay_rate * days_old)
        return max(floor, decayed)


@dataclass
class VendorInfo:
    """Information about a vendor/source."""
    name: str
    url: str
    source_type: str = "unknown"   # breeder, retailer, marketplace
    reliability: float = 0.5
    notes: str = ""


@dataclass
class ExtractedLink:
    """A link extracted from a page for navigation."""
    title: str
    url: str


@dataclass
class ProductListing:
    """A time-sensitive product listing."""
    name: str
    price: str
    vendor: str
    url: str
    in_stock: bool = True
    confidence: float = 0.7
    description: str = ""
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)


@dataclass
class RejectedListing:
    """A product that was considered but rejected during viability check."""
    name: str
    vendor: str
    url: str
    rejection_reason: str          # e.g., "Product is a toy/squeeze toy, not a live animal"
    rejection_type: str = "unknown"  # category_mismatch, spec_mismatch, price, availability
    price: str = ""

    @staticmethod
    def classify_rejection_type(reason: str) -> str:
        """Classify the rejection reason into a type for filtering."""
        reason_lower = reason.lower()
        if any(w in reason_lower for w in ["toy", "not a live", "accessory", "food", "treat", "cage", "habitat", "bedding"]):
            return "category_mismatch"
        elif any(w in reason_lower for w in ["price", "expensive", "budget", "cost"]):
            return "price"
        elif any(w in reason_lower for w in ["stock", "unavailable", "sold out"]):
            return "availability"
        elif any(w in reason_lower for w in ["spec", "requirement", "missing"]):
            return "spec_mismatch"
        return "other"


@dataclass
class ResearchDocument:
    """
    Complete research document with all metadata and content.

    This is the in-memory representation that gets serialized to research.md
    and indexed in SQLite.
    """
    # Identity
    id: str                                # research_759_a1b2c3d4
    turn_number: int
    session_id: str
    query: str                             # Original query

    # Classification
    topic: TopicClassification

    # Quality
    quality: QualityScores
    confidence: ConfidenceInfo

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    last_verified_at: Optional[datetime] = None

    # Scope & lineage
    scope: str = "new"                     # new, user, global (per MEMORY_ARCHITECTURE.md)
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    status: str = "active"                 # active, superseded, expired
    usage_count: int = 1

    # Content - Evergreen
    vendors: List[VendorInfo] = field(default_factory=list)
    general_facts: List[str] = field(default_factory=list)
    community_tips: List[str] = field(default_factory=list)

    # Content - Time-sensitive
    listings: List[ProductListing] = field(default_factory=list)
    ttl_hours: int = 6

    # Content - Rejected (for context awareness and validation)
    rejected_listings: List[RejectedListing] = field(default_factory=list)

    # Extracted links (for forum threads, article lists, navigation)
    extracted_links: List[ExtractedLink] = field(default_factory=list)

    # Source references
    source_urls: List[str] = field(default_factory=list)

    @staticmethod
    def generate_id(turn_number: int, query: str) -> str:
        """Generate unique research ID."""
        hash_input = f"{turn_number}:{query}:{datetime.now().isoformat()}"
        short_hash = hashlib.md5(hash_input.encode()).hexdigest()[:8]
        return f"research_{turn_number}_{short_hash}"

    def to_markdown(self) -> str:
        """Serialize to markdown format."""
        lines = []

        # Header
        lines.append("# Research Document")
        lines.append(f"**ID:** {self.id}")
        lines.append(f"**Turn:** {self.turn_number}")
        lines.append(f"**Session:** {self.session_id}")
        lines.append(f"**Created:** {self.created_at.isoformat()}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Metadata section
        lines.append("## Metadata")
        lines.append("")

        # Topic Classification
        lines.append("### Topic Classification")
        lines.append(f"- **Primary Topic:** {self.topic.primary_topic}")
        lines.append(f"- **Keywords:** {', '.join(self.topic.keywords)}")
        lines.append(f"- **Intent:** {self.topic.intent}")
        lines.append(f"- **Content Types:** {', '.join(self.topic.content_types) if self.topic.content_types else 'unclassified'}")
        lines.append("")

        # Quality Scores
        lines.append("### Quality Scores")
        lines.append(f"- **Completeness:** {self.quality.completeness:.2f}")
        lines.append(f"- **Source Quality:** {self.quality.source_quality:.2f}")
        lines.append(f"- **Extraction Success:** {self.quality.extraction_success:.2f}")
        lines.append(f"- **Overall Quality:** {self.quality.overall:.2f}")
        lines.append("")

        # Confidence
        current_confidence = self.confidence.calculate_current(self.created_at)
        lines.append("### Freshness & Confidence")
        lines.append(f"- **Initial Confidence:** {self.confidence.initial:.2f}")
        lines.append(f"- **Current Confidence:** {current_confidence:.2f}")
        lines.append(f"- **Decay Rate:** {self.confidence.decay_rate}/day")
        lines.append(f"- **Verified:** {self.last_verified_at is not None}")
        if self.last_verified_at:
            lines.append(f"- **Last Verified:** {self.last_verified_at.isoformat()}")
        lines.append("")

        # Scope
        lines.append("### Scope & Lineage")
        lines.append(f"- **Scope:** {self.scope}")
        lines.append(f"- **Status:** {self.status}")
        lines.append(f"- **Usage Count:** {self.usage_count}")
        if self.supersedes:
            lines.append(f"- **Supersedes:** {self.supersedes}")
        if self.superseded_by:
            lines.append(f"- **Superseded By:** {self.superseded_by}")
        lines.append("")

        lines.append("---")
        lines.append("")

        # Evergreen Knowledge
        lines.append("## Evergreen Knowledge")
        lines.append("")
        lines.append("*Facts that don't expire - general knowledge about the topic*")
        lines.append("")

        # Vendors
        if self.vendors:
            lines.append("### Reputable Sources")
            lines.append("| Source | Type | Reliability | Notes |")
            lines.append("|--------|------|-------------|-------|")
            for v in self.vendors:
                notes = v.notes[:50] if v.notes else ""
                lines.append(f"| {v.name} | {v.source_type} | {v.reliability:.2f} | {notes} |")
            lines.append("")

        # General Facts
        if self.general_facts:
            lines.append("### General Facts")
            for fact in self.general_facts:
                lines.append(f"- {fact}")
            lines.append("")

        # Community Tips
        if self.community_tips:
            lines.append("### Community Tips")
            for tip in self.community_tips:
                lines.append(f"- {tip}")
            lines.append("")

        lines.append("---")
        lines.append("")

        # Time-Sensitive Data
        lines.append("## Time-Sensitive Data")
        lines.append("")
        lines.append(f"*Data that expires - prices, availability, specific listings*")
        lines.append("")
        lines.append(f"**TTL:** {self.ttl_hours} hours")
        if self.expires_at:
            lines.append(f"**Expires:** {self.expires_at.isoformat()}")
        lines.append("")

        # Listings
        if self.listings:
            lines.append("### Current Listings")
            lines.append("")
            lines.append("| Product | Price | Vendor | In Stock | Confidence |")
            lines.append("|---------|-------|--------|----------|------------|")
            for listing in self.listings:
                stock = "Yes" if listing.in_stock else "No"
                lines.append(f"| {listing.name} | {listing.price} | {listing.vendor} | {stock} | {listing.confidence:.2f} |")
            lines.append("")

            # Detailed listings
            lines.append("### Listing Details")
            lines.append("")
            for i, listing in enumerate(self.listings, 1):
                lines.append(f"#### {i}. {listing.name}")
                lines.append(f"- **Price:** {listing.price}")
                lines.append(f"- **Vendor:** {listing.vendor}")
                lines.append(f"- **URL:** {listing.url}")
                if listing.description:
                    lines.append(f"- **Description:** {listing.description}")
                if listing.strengths:
                    lines.append(f"- **Strengths:** {', '.join(listing.strengths)}")
                if listing.weaknesses:
                    lines.append(f"- **Weaknesses:** {', '.join(listing.weaknesses)}")
                lines.append("")
        else:
            lines.append("*No current listings found.*")
            lines.append("")

        # Rejected Listings (for context awareness)
        if self.rejected_listings:
            lines.append("### Rejected Products")
            lines.append("")
            lines.append("*Products considered but excluded from results*")
            lines.append("")
            lines.append("| Product | Vendor | Rejection Reason | Type |")
            lines.append("|---------|--------|------------------|------|")
            for rej in self.rejected_listings:
                reason_short = rej.rejection_reason[:60] + "..." if len(rej.rejection_reason) > 60 else rej.rejection_reason
                lines.append(f"| {rej.name[:40]} | {rej.vendor} | {reason_short} | {rej.rejection_type} |")
            lines.append("")

        # Extracted Links (for forum threads, article lists, etc.)
        if self.extracted_links:
            lines.append("### Extracted Links")
            lines.append("")
            lines.append("*Navigable links from this source for follow-up queries*")
            lines.append("")
            lines.append("| Title | URL |")
            lines.append("|-------|-----|")
            for link in self.extracted_links[:30]:  # Limit to 30 links
                # Escape pipe characters in title
                safe_title = link.title.replace("|", "\\|")[:80]
                lines.append(f"| {safe_title} | {link.url} |")
            lines.append("")

        lines.append("---")
        lines.append("")

        # Source References
        lines.append("## Source References")
        lines.append("")
        for i, url in enumerate(self.source_urls, 1):
            lines.append(f"- [{i}] {url}")
        lines.append("")

        return "\n".join(lines)

    def get_evergreen_summary(self, max_tokens: int = 500) -> str:
        """Get a condensed version of evergreen knowledge for context."""
        lines = []

        lines.append(f"### Research: {self.topic.primary_topic}")
        lines.append(f"*Quality: {self.quality.overall:.2f}, Confidence: {self.confidence.calculate_current(self.created_at):.2f}*")
        lines.append("")

        # Top vendors
        if self.vendors:
            lines.append("**Known Sources:**")
            for v in self.vendors[:3]:
                lines.append(f"- {v.name} ({v.source_type}, reliability: {v.reliability:.2f})")
            lines.append("")

        # Key facts
        if self.general_facts:
            lines.append("**Key Facts:**")
            for fact in self.general_facts[:5]:
                lines.append(f"- {fact}")
            lines.append("")

        # Price range from listings
        if self.listings:
            prices = []
            for listing in self.listings:
                # Try to extract numeric price
                price_str = listing.price.replace('$', '').replace(',', '')
                if '-' in price_str:
                    # Range like "$25-$35"
                    parts = price_str.split('-')
                    try:
                        prices.extend([float(p.strip()) for p in parts])
                    except ValueError:
                        pass
                else:
                    try:
                        prices.append(float(price_str))
                    except ValueError:
                        pass

            if prices:
                lines.append(f"**Price Range:** ${min(prices):.0f} - ${max(prices):.0f}")
                lines.append("")

        return "\n".join(lines)


# =============================================================================
# Research Document Writer
# =============================================================================

class ResearchDocumentWriter:
    """
    Creates ResearchDocument from tool results and writes to disk.
    """

    def __init__(self, turns_dir: Path = None):
        self.turns_dir = turns_dir or Path("panda_system_docs/turns")

    def create_from_tool_results(
        self,
        turn_number: int,
        session_id: str,
        query: str,
        tool_results: Dict[str, Any],
        topic: Optional[str] = None,
        intent: str = "transactional"
    ) -> ResearchDocument:
        """
        Create a ResearchDocument from internet.research tool results.

        Args:
            turn_number: Current turn number
            session_id: User session ID
            query: Original user query
            tool_results: Raw results from internet.research tool
            topic: Optional topic classification (will be inferred if not provided)
            intent: Query intent (transactional or informational)

        Returns:
            ResearchDocument ready to be saved
        """
        # Generate ID
        doc_id = ResearchDocument.generate_id(turn_number, query)

        # Extract findings from tool results
        findings = tool_results.get("findings", [])
        stats = tool_results.get("stats", {})

        # Infer topic from query if not provided
        if not topic:
            topic = self._infer_topic(query, findings)

        # Extract keywords from query and findings
        keywords = self._extract_keywords(query, findings)

        # Classify what content types are present in the research
        content_types = classify_content_types_from_findings(findings)

        # Create topic classification with content types
        topic_class = TopicClassification(
            primary_topic=topic,
            keywords=keywords,
            intent=intent,
            content_types=content_types
        )

        # Calculate quality scores
        sources_visited = stats.get("sources_visited", 0)
        sources_extracted = stats.get("sources_extracted", 0)
        findings_count = len(findings)

        quality = QualityScores(
            completeness=min(1.0, findings_count / 5),  # 5 findings = complete
            source_quality=0.8 if sources_visited > 0 else 0.0,
            extraction_success=sources_extracted / max(1, sources_visited)
        )

        # Create confidence info
        avg_confidence = sum(f.get("confidence", 0.7) for f in findings) / max(1, len(findings))
        confidence = ConfidenceInfo(
            initial=avg_confidence,
            current=avg_confidence,
            content_type="price" if intent == "transactional" else "general_fact"
        )

        # Extract vendors
        vendors = self._extract_vendors(findings)

        # Extract general facts
        general_facts = self._extract_general_facts(findings)

        # Extract community tips from weaknesses/notes
        community_tips = self._extract_community_tips(findings)

        # Extract listings
        listings = self._extract_listings(findings)

        # Extract rejected listings (for context awareness)
        rejected = tool_results.get("rejected", [])
        rejected_listings = self._extract_rejected_listings(rejected)

        # Extract links from findings (for forum threads, article lists, etc.)
        extracted_links = self._extract_links(findings)

        # Collect source URLs
        source_urls = list(set(f.get("url", "") for f in findings if f.get("url")))

        # Calculate expiry
        ttl_hours = 6 if intent == "transactional" else 24
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

        # Create document
        doc = ResearchDocument(
            id=doc_id,
            turn_number=turn_number,
            session_id=session_id,
            query=query,
            topic=topic_class,
            quality=quality,
            confidence=confidence,
            expires_at=expires_at,
            vendors=vendors,
            general_facts=general_facts,
            community_tips=community_tips,
            listings=listings,
            rejected_listings=rejected_listings,
            extracted_links=extracted_links,
            ttl_hours=ttl_hours,
            source_urls=source_urls
        )

        return doc

    def write(self, doc: ResearchDocument, turn_dir: Path = None) -> Path:
        """
        Write research document to disk.

        Args:
            doc: ResearchDocument to write
            turn_dir: Optional turn directory (defaults to turns_dir/turn_XXXXXX)

        Returns:
            Path to written research.md file
        """
        if turn_dir is None:
            turn_dir = self.turns_dir / f"turn_{doc.turn_number:06d}"

        turn_dir.mkdir(parents=True, exist_ok=True)

        # Write markdown
        md_path = turn_dir / "research.md"
        md_content = doc.to_markdown()
        md_path.write_text(md_content)

        # Also write JSON for easier parsing
        json_path = turn_dir / "research.json"
        json_data = {
            "id": doc.id,
            "turn_number": doc.turn_number,
            "session_id": doc.session_id,
            "query": doc.query,
            "topic": {
                "primary_topic": doc.topic.primary_topic,
                "keywords": doc.topic.keywords,
                "intent": doc.topic.intent,
                "content_types": doc.topic.content_types
            },
            "quality": {
                "completeness": doc.quality.completeness,
                "source_quality": doc.quality.source_quality,
                "extraction_success": doc.quality.extraction_success,
                "overall": doc.quality.overall
            },
            "confidence": {
                "initial": doc.confidence.initial,
                "current": doc.confidence.current,
                "decay_rate": doc.confidence.decay_rate,
                "content_type": doc.confidence.content_type
            },
            "created_at": doc.created_at.isoformat(),
            "expires_at": doc.expires_at.isoformat() if doc.expires_at else None,
            "scope": doc.scope,
            "status": doc.status,
            "ttl_hours": doc.ttl_hours,
            "vendors": [asdict(v) for v in doc.vendors],
            "general_facts": doc.general_facts,
            "community_tips": doc.community_tips,
            "listings": [asdict(l) for l in doc.listings],
            "rejected_listings": [asdict(r) for r in doc.rejected_listings],
            "extracted_links": [asdict(l) for l in doc.extracted_links],
            "source_urls": doc.source_urls
        }
        json_path.write_text(json.dumps(json_data, indent=2))

        logger.info(
            f"[ResearchDoc] Wrote research.md for turn {doc.turn_number} "
            f"(topic={doc.topic.primary_topic}, quality={doc.quality.overall:.2f}, "
            f"{len(doc.listings)} listings, {len(doc.rejected_listings)} rejected, {len(doc.general_facts)} facts)"
        )

        return md_path

    def _infer_topic(self, query: str, findings: List[Dict]) -> str:
        """
        Infer topic from query and findings.

        DESIGN PRINCIPLE: This method extracts a simple topic hierarchy from the query
        without hardcoded product-specific patterns. Complex topic classification
        should be handled by LLM prompts in upstream components (Context Gatherer, Planner).

        The topic format is: category.subcategory.specific
        e.g., "commerce.product.laptop", "pets.hamster", "research.general"
        """
        query_lower = query.lower()

        # Stop words to filter out
        stop_words = {
            "find", "me", "some", "for", "sale", "online", "please", "can", "you",
            "the", "a", "an", "where", "what", "how", "to", "buy", "get", "show",
            "best", "cheapest", "under", "around", "near", "good", "any", "i", "want"
        }

        # Extract meaningful words from query
        words = [w.strip("?,.'\"!") for w in query_lower.split()]
        meaningful_words = [w for w in words if len(w) > 2 and w not in stop_words]

        if not meaningful_words:
            return "general.unknown"

        # Use first meaningful word as topic, additional words as subtopic
        primary = meaningful_words[0]
        if len(meaningful_words) > 1:
            secondary = meaningful_words[1]
            return f"general.{primary}.{secondary}"

        return f"general.{primary}"

    def _extract_keywords(self, query: str, findings: List[Dict]) -> List[str]:
        """Extract keywords from query and findings."""
        keywords = set()

        # From query
        stop_words = {"find", "me", "some", "for", "sale", "online", "please", "can", "you", "the", "a", "an"}
        for word in query.lower().split():
            word = word.strip("?,.")
            if len(word) > 2 and word not in stop_words:
                keywords.add(word)

        # From findings
        for finding in findings:
            name = finding.get("name", "").lower()
            for word in name.split():
                if len(word) > 3:
                    keywords.add(word)

        return list(keywords)[:10]  # Limit to 10 keywords

    def _extract_vendors(self, findings: List[Dict]) -> List[VendorInfo]:
        """Extract vendor information from findings."""
        vendors_seen = {}

        for finding in findings:
            vendor_name = finding.get("vendor", "")
            if not vendor_name:
                continue

            if vendor_name not in vendors_seen:
                url = finding.get("url", "")
                confidence = finding.get("confidence", 0.7)

                # Infer source type
                source_type = "unknown"
                name_lower = vendor_name.lower()
                if "hamstery" in name_lower or "breeder" in name_lower or "critter" in name_lower:
                    source_type = "breeder"
                elif any(r in name_lower for r in ["amazon", "ebay", "walmart", "petco", "petsmart"]):
                    source_type = "retailer"
                elif "forum" in name_lower or "reddit" in name_lower:
                    source_type = "community"

                vendors_seen[vendor_name] = VendorInfo(
                    name=vendor_name,
                    url=url,
                    source_type=source_type,
                    reliability=confidence,
                    notes=finding.get("description", "")[:100]
                )

        return list(vendors_seen.values())

    def _extract_general_facts(self, findings: List[Dict]) -> List[str]:
        """Extract general/evergreen facts from findings."""
        facts = []

        for finding in findings:
            description = finding.get("description", "")
            if description:
                # Extract factual statements (simple heuristic)
                sentences = description.split(".")
                for sentence in sentences:
                    sentence = sentence.strip()
                    if len(sentence) > 20 and not any(
                        w in sentence.lower() for w in ["price", "cost", "$", "available now"]
                    ):
                        facts.append(sentence)

        return list(set(facts))[:10]  # Dedupe and limit

    def _extract_community_tips(self, findings: List[Dict]) -> List[str]:
        """Extract community tips and warnings from findings."""
        tips = []

        for finding in findings:
            # From weaknesses
            for weakness in finding.get("weaknesses", []):
                if len(weakness) > 10:
                    tips.append(f"Note: {weakness}")

            # From strengths (as positive tips)
            for strength in finding.get("strengths", []):
                if "recommend" in strength.lower() or "ideal" in strength.lower():
                    tips.append(strength)

        return list(set(tips))[:5]

    def _extract_listings(self, findings: List[Dict]) -> List[ProductListing]:
        """Extract product listings from findings."""
        listings = []

        for finding in findings:
            name = finding.get("name", "")
            price = finding.get("price", "")
            vendor = finding.get("vendor", "")
            url = finding.get("url", "")

            if name and (price or vendor):
                listings.append(ProductListing(
                    name=name,
                    price=price or "Not specified",
                    vendor=vendor,
                    url=url,
                    confidence=finding.get("confidence", 0.7),
                    description=finding.get("description", ""),
                    strengths=finding.get("strengths", []),
                    weaknesses=finding.get("weaknesses", [])
                ))

        return listings

    def _extract_rejected_listings(self, rejected: List[Dict]) -> List[RejectedListing]:
        """Extract rejected listings with their rejection reasons."""
        rejected_listings = []

        for item in rejected:
            name = item.get("name", "")
            vendor = item.get("vendor", "")
            url = item.get("url", "")
            rejection_reason = item.get("rejection_reason", "Unknown reason")
            price = item.get("price", "")

            if name:
                # Classify the rejection type
                rejection_type = RejectedListing.classify_rejection_type(rejection_reason)

                rejected_listings.append(RejectedListing(
                    name=name,
                    vendor=vendor,
                    url=url,
                    rejection_reason=rejection_reason,
                    rejection_type=rejection_type,
                    price=price
                ))

        return rejected_listings

    def _extract_links(self, findings: List[Dict]) -> List[ExtractedLink]:
        """Extract navigable links from findings (for forum threads, article lists, etc.)."""
        extracted_links = []
        seen_urls = set()

        for finding in findings:
            # Check if finding has extracted_links from PageIntelligence
            links = finding.get("extracted_links", [])
            for link in links:
                url = link.get("url", "")
                title = link.get("title", "")

                if url and title and url not in seen_urls:
                    seen_urls.add(url)
                    extracted_links.append(ExtractedLink(
                        title=title[:200],  # Limit title length
                        url=url
                    ))

        return extracted_links


# =============================================================================
# Convenience Functions
# =============================================================================

def create_research_document(
    turn_number: int,
    session_id: str,
    query: str,
    tool_results: Dict[str, Any],
    topic: Optional[str] = None,
    intent: str = "transactional"
) -> ResearchDocument:
    """
    Convenience function to create a research document from tool results.
    """
    writer = ResearchDocumentWriter()
    return writer.create_from_tool_results(
        turn_number=turn_number,
        session_id=session_id,
        query=query,
        tool_results=tool_results,
        topic=topic,
        intent=intent
    )


def write_research_document(doc: ResearchDocument, turn_dir: Path = None) -> Path:
    """
    Convenience function to write a research document to disk.
    """
    writer = ResearchDocumentWriter()
    return writer.write(doc, turn_dir)
