"""
Entity Extractor - Extract structured entities from text and research results.

Supports extraction of:
- Vendors: Identified by patterns like "from X", "at X", "via X", "X sells"
- Prices: $XX.XX format, XX dollars
- Sites: domain.com, full URLs
- Products: Items after "buy", "find", "looking for"
- Threads: Forum thread titles from research results
- Topics: General discussion topics

Part of the Knowledge Graph system for bidirectional linking and entity tracking.

See: architecture/Implementation/KNOWLEDGE_GRAPH_AND_UI_PLAN.md
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ExtractedEntity:
    """
    A single extracted entity with metadata.

    Attributes:
        text: Original text as found in source (e.g., "Example Pet Store")
        entity_type: Type of entity (vendor, product, site, topic, thread, person)
        canonical_name: Normalized name for deduplication (e.g., "Example Pet Store")
        confidence: Extraction confidence score (0.0 to 1.0)
        properties: Additional properties (url, price, location, etc.)
        context: Surrounding text snippet for verification (up to 200 chars)
    """
    text: str
    entity_type: str
    canonical_name: str
    confidence: float = 0.5
    properties: Dict[str, Any] = field(default_factory=dict)
    context: str = ""

    def __post_init__(self):
        """Ensure properties dict is initialized."""
        if self.properties is None:
            self.properties = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "text": self.text,
            "entity_type": self.entity_type,
            "canonical_name": self.canonical_name,
            "confidence": self.confidence,
            "properties": self.properties,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExtractedEntity":
        """Create from dictionary."""
        return cls(
            text=data.get("text", ""),
            entity_type=data.get("entity_type", "unknown"),
            canonical_name=data.get("canonical_name", data.get("text", "")),
            confidence=data.get("confidence", 0.5),
            properties=data.get("properties", {}),
            context=data.get("context", ""),
        )


# =============================================================================
# Entity Type Constants
# =============================================================================

ENTITY_TYPES = {
    "vendor",    # Sellers, stores, breeders
    "product",   # Items for sale
    "person",    # Named individuals
    "site",      # Websites, domains
    "topic",     # Discussion topics
    "thread",    # Forum threads, articles
}


# =============================================================================
# Entity Extractor
# =============================================================================

class EntityExtractor:
    """
    Extracts entities from text and research results using pattern matching.

    Uses regex patterns for high-precision extraction of:
    - Vendors: Business names in vendor contexts
    - Prices: Dollar amounts
    - Sites: Domain names and URLs
    - Products: Items being searched for or purchased

    Example:
        extractor = EntityExtractor()
        entities = extractor.extract_from_text("Buy from Example Pet Store for $75")
        # Returns: [
        #   ExtractedEntity(text="Example Pet Store", entity_type="vendor", ...),
        #   ExtractedEntity(text="$75", entity_type="price", properties={"amount": 75.0}, ...)
        # ]
    """

    # =========================================================================
    # Pattern Definitions
    # =========================================================================

    # Vendor patterns - names that appear in vendor contexts
    # Matches: "from Example Pet Store", "at Petco", "via Amazon"
    # All patterns capture ONLY the vendor name, not the context words
    # Note: Patterns are compiled with re.IGNORECASE, so use word boundaries carefully
    VENDOR_PATTERNS = [
        # Common vendor indicators: "X Hamstery", "X Pet Shop", "X Breeders" (highest priority)
        # Use negative lookbehind to avoid matching action words like "Buy", "Check", "Also"
        (r"(?<![a-zA-Z])(?!(?:Buy|Check|Also|Found|Great|Info|See|Visit)\s)([A-Z][a-zA-Z\']+(?:\s+[A-Z][a-zA-Z\']+)*\s+(?:Hamstery|Pet\s*Shop|Breeders?|Store|Market|Shop|LLC|Inc))", 0.9),
        # "from/at/via/by X" where X is 1-4 Title Case words (exclude context words)
        (r"(?:from|at|via|by|through)\s+([A-Z][a-zA-Z\']+(?:\s+[A-Z][a-zA-Z\']+){0,3})(?=\s+(?:for|is|are|was|were|has|have|sells|offers|\.|,|\$)|\s*\.|$)", 0.8),
        # "X sells/offers/has/is highly recommended" where X is Title Case
        (r"(?<![a-zA-Z])([A-Z][a-zA-Z\']+(?:\s+[A-Z][a-zA-Z\']+){0,2})\s+(?:sells|offers|has|carries|stocks|is\s+highly|is\s+recommended)", 0.75),
        # "sold by X"
        (r"sold\s+by\s+([A-Z][a-zA-Z\']+(?:\s+[A-Z][a-zA-Z\']+){0,2})(?=\s*[.,]|\s+for|\s*$)", 0.8),
        # "available at X"
        (r"available\s+(?:at|from)\s+([A-Z][a-zA-Z\']+(?:\s+[A-Z][a-zA-Z\']+){0,2})(?=\s*[.,]|\s+for|\s*$)", 0.75),
        # "buy/order from X" patterns
        (r"(?:buy|order|purchase)\s+(?:from|at)\s+([A-Z][a-zA-Z\']+(?:\s+[A-Z][a-zA-Z\']+){0,2})(?=\s*[.,]|\s+for|\s*$)", 0.8),
    ]

    # Price patterns
    PRICE_PATTERNS = [
        # $XX or $XX.XX
        (r"\$(\d+(?:\.\d{2})?)", 0.95),
        # XX dollars
        (r"(\d+(?:\.\d{2})?)\s*(?:dollars?|USD)", 0.9),
        # Price range: $XX-$YY or $XX to $YY
        (r"\$(\d+(?:\.\d{2})?)\s*[-to]+\s*\$(\d+(?:\.\d{2})?)", 0.9),
    ]

    # Site/URL patterns
    SITE_PATTERNS = [
        # Full URLs (highest priority)
        (r"(https?://[^\s<>\"\']+)", 0.95),
        # Domain names in explicit context
        (r"(?:on|at|from|visit|check)\s+([\w-]+\.(?:com|org|net|io|co|edu)(?:/\S*)?)", 0.85),
        # Standalone domains with common TLDs (must be at least 4 chars before TLD)
        (r"\b([\w][\w-]{2,}\.(?:com|org|net|io))\b", 0.6),
    ]

    # Product patterns - things being searched for or purchased
    PRODUCT_PATTERNS = [
        # "buy/find/looking for [a] X" - limit to 1-5 words
        (r"(?:buy|find|looking\s+for|searching\s+for|want\s+to\s+buy)\s+(?:a\s+|an\s+)?([a-zA-Z][a-zA-Z\s]{2,40}?)(?:\s+(?:for|from|at|online|cheap|under)|\.|,|$)", 0.7),
        # "X for sale" - limit to 1-4 words
        (r"([a-zA-Z][a-zA-Z\s]{2,30}?)\s+for\s+sale", 0.75),
        # "best/cheapest X" - more restrictive, 1-3 words
        (r"(?:best|cheapest|top)\s+([a-zA-Z][a-zA-Z\s]{2,25}?)(?:\s+(?:for|from|at|online|under|in|breeders?)|\.|,|$)", 0.65),
    ]

    # Thread/article title patterns (typically in quotes or specific formats)
    THREAD_PATTERNS = [
        # Quoted titles
        (r'"([^"]{10,150})"', 0.8),
        # Title with thread indicators
        (r"(?:thread|post|article|discussion)(?:\s+titled?)?\s*[:\-]?\s*\"?([^\".\n]{10,100})\"?", 0.75),
    ]

    def __init__(self):
        """Initialize the entity extractor."""
        # Compile patterns for efficiency
        self._compiled_vendor = [(re.compile(p, re.IGNORECASE), c) for p, c in self.VENDOR_PATTERNS]
        self._compiled_price = [(re.compile(p, re.IGNORECASE), c) for p, c in self.PRICE_PATTERNS]
        self._compiled_site = [(re.compile(p, re.IGNORECASE), c) for p, c in self.SITE_PATTERNS]
        self._compiled_product = [(re.compile(p, re.IGNORECASE), c) for p, c in self.PRODUCT_PATTERNS]
        self._compiled_thread = [(re.compile(p, re.IGNORECASE), c) for p, c in self.THREAD_PATTERNS]

    # =========================================================================
    # Main Extraction Methods
    # =========================================================================

    def extract_from_text(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None
    ) -> List[ExtractedEntity]:
        """
        Extract all entities from a text string.

        Args:
            text: Text to extract entities from
            context: Optional context dict with hints (e.g., {"intent": "commerce"})

        Returns:
            List of ExtractedEntity objects
        """
        if not text or not text.strip():
            return []

        entities: List[ExtractedEntity] = []
        context = context or {}

        # Extract each entity type
        entities.extend(self._extract_vendors(text))
        entities.extend(self._extract_prices(text))
        entities.extend(self._extract_sites(text))
        entities.extend(self._extract_products(text))
        entities.extend(self._extract_threads(text))

        # Normalize all entities
        entities = [self.normalize_entity(e) for e in entities]

        # Deduplicate
        entities = self.deduplicate(entities)

        logger.debug(f"[EntityExtractor] Extracted {len(entities)} entities from text ({len(text)} chars)")
        return entities

    def extract_from_research(
        self,
        research_result: Dict[str, Any]
    ) -> List[ExtractedEntity]:
        """
        Extract entities from internet.research tool results.

        Processes:
        - findings[].content - main text content
        - findings[].source - site entities
        - findings[].title - thread/article titles
        - synthesis.products[] - product entities if present

        Args:
            research_result: Result dict from internet.research tool

        Returns:
            List of ExtractedEntity objects
        """
        if not research_result:
            return []

        entities: List[ExtractedEntity] = []

        # Extract from findings
        findings = research_result.get("findings", [])
        for finding in findings:
            # Extract from content
            content = finding.get("content", "")
            if content:
                content_entities = self.extract_from_text(content)
                entities.extend(content_entities)

            # Extract site entity from source
            source = finding.get("source", "")
            if source:
                site_entity = self._create_site_entity(source, finding)
                if site_entity:
                    entities.append(site_entity)

            # Extract thread entity from title
            title = finding.get("title", "")
            if title and len(title) >= 10:
                thread_entity = ExtractedEntity(
                    text=title,
                    entity_type="thread",
                    canonical_name=self._normalize_title(title),
                    confidence=0.85,
                    properties={
                        "url": finding.get("url", ""),
                        "source": source,
                    },
                    context=content[:200] if content else "",
                )
                entities.append(thread_entity)

        # Extract from synthesis if present
        synthesis = research_result.get("synthesis", {})
        if isinstance(synthesis, dict):
            # Products from synthesis
            products = synthesis.get("products", [])
            for product in products:
                if isinstance(product, dict):
                    product_entity = self._create_product_entity_from_synthesis(product)
                    if product_entity:
                        entities.append(product_entity)
                elif isinstance(product, str):
                    entities.append(ExtractedEntity(
                        text=product,
                        entity_type="product",
                        canonical_name=self._normalize_name(product),
                        confidence=0.8,
                    ))

            # Vendors from synthesis
            vendors = synthesis.get("vendors", synthesis.get("sources", []))
            for vendor in vendors:
                if isinstance(vendor, dict):
                    vendor_entity = self._create_vendor_entity_from_synthesis(vendor)
                    if vendor_entity:
                        entities.append(vendor_entity)
                elif isinstance(vendor, str):
                    entities.append(ExtractedEntity(
                        text=vendor,
                        entity_type="vendor",
                        canonical_name=self._normalize_name(vendor),
                        confidence=0.75,
                    ))

        # Normalize and deduplicate
        entities = [self.normalize_entity(e) for e in entities]
        entities = self.deduplicate(entities)

        logger.info(f"[EntityExtractor] Extracted {len(entities)} entities from research result")
        return entities

    # =========================================================================
    # Type-Specific Extraction
    # =========================================================================

    def _extract_vendors(self, text: str) -> List[ExtractedEntity]:
        """Extract vendor entities from text."""
        entities = []
        seen_texts: Set[str] = set()

        for pattern, base_confidence in self._compiled_vendor:
            for match in pattern.finditer(text):
                vendor_name = match.group(1).strip()

                # Skip if too short or already seen
                if len(vendor_name) < 3 or vendor_name.lower() in seen_texts:
                    continue

                # Skip common false positives
                if self._is_vendor_false_positive(vendor_name):
                    continue

                seen_texts.add(vendor_name.lower())

                # Get surrounding context
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                context = text[start:end]

                entities.append(ExtractedEntity(
                    text=vendor_name,
                    entity_type="vendor",
                    canonical_name=vendor_name,
                    confidence=base_confidence,
                    context=context,
                ))

        return entities

    def _extract_prices(self, text: str) -> List[ExtractedEntity]:
        """Extract price entities from text."""
        entities = []

        for pattern, base_confidence in self._compiled_price:
            for match in pattern.finditer(text):
                groups = match.groups()

                # Handle single price or price range
                if len(groups) == 1:
                    price_text = f"${groups[0]}"
                    amount = float(groups[0])
                    properties = {"amount": amount}
                else:
                    # Price range
                    price_text = f"${groups[0]}-${groups[1]}"
                    properties = {
                        "amount_low": float(groups[0]),
                        "amount_high": float(groups[1]),
                        "is_range": True,
                    }

                # Get context
                start = max(0, match.start() - 30)
                end = min(len(text), match.end() + 30)
                context = text[start:end]

                entities.append(ExtractedEntity(
                    text=price_text,
                    entity_type="price",
                    canonical_name=price_text,
                    confidence=base_confidence,
                    properties=properties,
                    context=context,
                ))

        return entities

    def _extract_sites(self, text: str) -> List[ExtractedEntity]:
        """Extract site/URL entities from text."""
        entities = []
        seen_domains: Set[str] = set()

        for pattern, base_confidence in self._compiled_site:
            for match in pattern.finditer(text):
                url_or_domain = match.group(1).strip()

                # Parse to get domain
                if url_or_domain.startswith("http"):
                    parsed = urlparse(url_or_domain)
                    domain = parsed.netloc
                    full_url = url_or_domain
                else:
                    domain = url_or_domain.split("/")[0]
                    full_url = f"https://{url_or_domain}"

                # Skip if already seen this domain
                if domain.lower() in seen_domains:
                    continue
                seen_domains.add(domain.lower())

                # Get context
                start = max(0, match.start() - 30)
                end = min(len(text), match.end() + 30)
                context = text[start:end]

                entities.append(ExtractedEntity(
                    text=url_or_domain,
                    entity_type="site",
                    canonical_name=domain.lower(),
                    confidence=base_confidence,
                    properties={
                        "url": full_url,
                        "domain": domain,
                    },
                    context=context,
                ))

        return entities

    def _extract_products(self, text: str) -> List[ExtractedEntity]:
        """Extract product entities from text."""
        entities = []
        seen_products: Set[str] = set()

        for pattern, base_confidence in self._compiled_product:
            for match in pattern.finditer(text):
                product_name = match.group(1).strip()

                # Clean up product name
                product_name = re.sub(r"\s+", " ", product_name).strip()

                # Skip if too short, too long, or already seen
                if len(product_name) < 3 or len(product_name) > 100:
                    continue
                if product_name.lower() in seen_products:
                    continue

                # Skip common false positives
                if self._is_product_false_positive(product_name):
                    continue

                seen_products.add(product_name.lower())

                # Get context
                start = max(0, match.start() - 30)
                end = min(len(text), match.end() + 50)
                context = text[start:end]

                entities.append(ExtractedEntity(
                    text=product_name,
                    entity_type="product",
                    canonical_name=product_name,
                    confidence=base_confidence,
                    context=context,
                ))

        return entities

    def _extract_threads(self, text: str) -> List[ExtractedEntity]:
        """Extract thread/article title entities from text."""
        entities = []
        seen_titles: Set[str] = set()

        for pattern, base_confidence in self._compiled_thread:
            for match in pattern.finditer(text):
                title = match.group(1).strip()

                # Skip if too short or already seen
                if len(title) < 10 or title.lower() in seen_titles:
                    continue

                seen_titles.add(title.lower())

                # Get context
                start = max(0, match.start() - 20)
                end = min(len(text), match.end() + 20)
                context = text[start:end]

                entities.append(ExtractedEntity(
                    text=title,
                    entity_type="thread",
                    canonical_name=self._normalize_title(title),
                    confidence=base_confidence,
                    context=context,
                ))

        return entities

    # =========================================================================
    # Normalization and Deduplication
    # =========================================================================

    def normalize_entity(self, entity: ExtractedEntity) -> ExtractedEntity:
        """
        Normalize an entity's name and properties.

        - Strips whitespace
        - Applies title case for vendors and products
        - Lowercases domains for sites
        - Truncates context to 200 chars

        Args:
            entity: Entity to normalize

        Returns:
            Normalized entity (new instance)
        """
        # Create normalized canonical name based on type
        if entity.entity_type in ("vendor", "product", "person"):
            canonical = self._normalize_name(entity.canonical_name)
        elif entity.entity_type == "site":
            canonical = entity.canonical_name.lower().strip()
        elif entity.entity_type == "thread":
            canonical = self._normalize_title(entity.canonical_name)
        else:
            canonical = entity.canonical_name.strip()

        # Truncate context
        context = entity.context[:200] if entity.context else ""

        return ExtractedEntity(
            text=entity.text.strip(),
            entity_type=entity.entity_type,
            canonical_name=canonical,
            confidence=entity.confidence,
            properties=entity.properties.copy() if entity.properties else {},
            context=context,
        )

    def deduplicate(self, entities: List[ExtractedEntity]) -> List[ExtractedEntity]:
        """
        Merge duplicate entities, keeping the highest confidence version.

        Duplicates are identified by (entity_type, canonical_name) pairs.
        Properties from duplicates are merged.

        Args:
            entities: List of entities to deduplicate

        Returns:
            Deduplicated list of entities
        """
        if not entities:
            return []

        # Group by (type, canonical_name)
        groups: Dict[Tuple[str, str], List[ExtractedEntity]] = {}
        for entity in entities:
            key = (entity.entity_type, entity.canonical_name.lower())
            if key not in groups:
                groups[key] = []
            groups[key].append(entity)

        # Merge each group
        deduplicated = []
        for group in groups.values():
            merged = self._merge_entity_group(group)
            deduplicated.append(merged)

        return deduplicated

    def _merge_entity_group(self, group: List[ExtractedEntity]) -> ExtractedEntity:
        """Merge a group of duplicate entities into one."""
        if len(group) == 1:
            return group[0]

        # Sort by confidence (highest first)
        group.sort(key=lambda e: e.confidence, reverse=True)
        best = group[0]

        # Merge properties from all entities
        merged_props = {}
        for entity in group:
            for key, value in entity.properties.items():
                if key not in merged_props or not merged_props[key]:
                    merged_props[key] = value

        # Use the best entity but with merged properties
        return ExtractedEntity(
            text=best.text,
            entity_type=best.entity_type,
            canonical_name=best.canonical_name,
            confidence=best.confidence,
            properties=merged_props,
            context=best.context,
        )

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _normalize_name(self, name: str) -> str:
        """Normalize a name to title case with cleaned whitespace."""
        if not name:
            return ""
        # Strip and collapse whitespace
        name = re.sub(r"\s+", " ", name.strip())
        # Title case, but preserve all-caps words like "LLC"
        words = name.split()
        normalized = []
        for word in words:
            if word.isupper() and len(word) <= 4:
                normalized.append(word)  # Keep LLC, INC, etc.
            else:
                normalized.append(word.title())
        return " ".join(normalized)

    def _normalize_title(self, title: str) -> str:
        """Normalize a thread/article title."""
        if not title:
            return ""
        # Strip and collapse whitespace
        title = re.sub(r"\s+", " ", title.strip())
        # Remove leading/trailing quotes
        title = title.strip("\"'")
        return title

    def _is_vendor_false_positive(self, name: str) -> bool:
        """Check if a vendor name is a common false positive."""
        name_lower = name.lower().strip()

        # Single word false positives
        false_positives = {
            # Common words that match vendor patterns
            "the", "a", "an", "this", "that", "these", "those",
            "i", "you", "he", "she", "it", "we", "they",
            "my", "your", "their", "our",
            "best", "good", "great", "top", "cheap", "cheapest",
            "info", "great", "found", "also", "check",
            # Common nouns that aren't vendors
            "prices", "supplies", "selection", "deals", "options",
            "popular", "local", "online",
        }
        if name_lower in false_positives:
            return True

        # Multi-word phrases that look like vendor names but aren't
        false_multi_word = {
            "popular pet store", "local pet store", "online store",
            "pet store", "pet shop",  # Generic, not specific names
        }
        if name_lower in false_multi_word:
            return True

        # Multi-word false positive patterns
        false_patterns = [
            r"^the\s+",  # Starts with "the"
            r"^info\s+on\s+",  # "info on X"
            r"^from\s+",  # Starts with "from"
            r"^buy\s+",  # Starts with "buy"
            r"^check\s+",  # Starts with "check"
            r"^also\s+",  # Starts with "also"
            r"^found\s+",  # Starts with "found"
            r"^visit\s+",  # Starts with "visit"
            r"\s+for$",  # Ends with "for"
            r"\s+or\s+",  # Contains "or"
            r"\s+and\s+",  # Contains "and" (likely listing, not name)
        ]
        for pattern in false_patterns:
            if re.search(pattern, name_lower):
                return True

        return False

    def _is_product_false_positive(self, name: str) -> bool:
        """Check if a product name is a common false positive."""
        name_lower = name.lower().strip()

        # Single word false positives
        false_positives = {
            # Common words
            "it", "them", "one", "some", "any",
            "something", "anything", "nothing",
            "things", "stuff", "info", "supplies",
            # Articles and prepositions
            "the", "a", "an", "for", "to", "from",
            # Generic terms
            "selection", "options", "deals", "prices",
        }
        if name_lower in false_positives:
            return True

        # Multi-word false positive patterns
        false_patterns = [
            r"^from\s+",  # Starts with "from"
            r"\s+or\s+",  # Contains "or" (likely listing)
            r"\s+for\s+the\s+best",  # "X for the best" phrase
        ]
        for pattern in false_patterns:
            if re.search(pattern, name_lower):
                return True

        return False

    def _create_site_entity(
        self,
        source: str,
        finding: Dict[str, Any]
    ) -> Optional[ExtractedEntity]:
        """Create a site entity from a finding's source."""
        if not source:
            return None

        # Extract domain from source (could be domain or full URL)
        if source.startswith("http"):
            parsed = urlparse(source)
            domain = parsed.netloc
        else:
            domain = source.split("/")[0]

        if not domain or len(domain) < 4:
            return None

        return ExtractedEntity(
            text=source,
            entity_type="site",
            canonical_name=domain.lower(),
            confidence=0.9,
            properties={
                "domain": domain,
                "url": finding.get("url", ""),
            },
            context=finding.get("title", "")[:100],
        )

    def _create_product_entity_from_synthesis(
        self,
        product: Dict[str, Any]
    ) -> Optional[ExtractedEntity]:
        """Create a product entity from synthesis data."""
        name = product.get("name") or product.get("title") or product.get("product")
        if not name:
            return None

        properties = {}
        if product.get("price"):
            properties["price"] = product["price"]
        if product.get("url"):
            properties["url"] = product["url"]
        if product.get("vendor"):
            properties["vendor"] = product["vendor"]

        return ExtractedEntity(
            text=name,
            entity_type="product",
            canonical_name=self._normalize_name(name),
            confidence=0.85,
            properties=properties,
        )

    def _create_vendor_entity_from_synthesis(
        self,
        vendor: Dict[str, Any]
    ) -> Optional[ExtractedEntity]:
        """Create a vendor entity from synthesis data."""
        name = vendor.get("name") or vendor.get("vendor") or vendor.get("source")
        if not name:
            return None

        properties = {}
        if vendor.get("url"):
            properties["url"] = vendor["url"]
        if vendor.get("location"):
            properties["location"] = vendor["location"]
        if vendor.get("rating"):
            properties["rating"] = vendor["rating"]

        return ExtractedEntity(
            text=name,
            entity_type="vendor",
            canonical_name=self._normalize_name(name),
            confidence=0.8,
            properties=properties,
        )


# =============================================================================
# Convenience Functions
# =============================================================================

def extract_entities(
    text: str,
    context: Optional[Dict[str, Any]] = None
) -> List[ExtractedEntity]:
    """
    Convenience function to extract entities from text.

    Args:
        text: Text to extract from
        context: Optional context hints

    Returns:
        List of ExtractedEntity objects
    """
    extractor = EntityExtractor()
    return extractor.extract_from_text(text, context)


def extract_from_research(
    research_result: Dict[str, Any]
) -> List[ExtractedEntity]:
    """
    Convenience function to extract entities from research results.

    Args:
        research_result: Result from internet.research tool

    Returns:
        List of ExtractedEntity objects
    """
    extractor = EntityExtractor()
    return extractor.extract_from_research(research_result)
