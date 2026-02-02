"""
Visit Record: Captures and persists page visit data for Context Gatherer retrieval.

Visit records enable the "fast path" in Context Gatherer - answering questions
from cached page data without re-navigation.

When a page is visited during research, a visit_record is created containing:
- manifest.json: Summary of page content and answerable questions
- page_content.md: Cleaned text content
- extracted_data.json: Structured data extracted from page
- screenshot.png: Visual capture (if available)

See: panda_system_docs/architecture/DOCUMENT-IO-SYSTEM/DOCUMENT_IO_DESIGN.md
"""

import json
import hashlib
import logging
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class VisitRecordManifest:
    """Manifest for a visit record - summarizes what the page contains."""

    # Identity
    title: str                              # Page title
    source_url: str                         # URL visited
    domain: str                             # Extracted domain
    content_type: str                       # "forum_thread", "product_page", "article", etc.

    # Content summary
    content_summary: str                    # Brief summary of page content
    page_info: Optional[str] = None         # e.g., "Page 1 of 3", "45 comments"

    # What questions can this page answer?
    answerable_questions: List[str] = field(default_factory=list)

    # Extracted entities (for matching)
    key_entities: List[str] = field(default_factory=list)

    # Timestamps
    captured_at: str = ""                   # ISO timestamp

    # File references (relative to visit_record directory)
    has_page_content: bool = False
    has_extracted_data: bool = False
    has_screenshot: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisitRecordManifest":
        """Create from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class VisitRecordWriter:
    """
    Creates visit records when pages are visited during research.

    Visit records are stored at:
        panda_system_docs/turns/turn_XXXXXX/visit_records/{slug}/

    Each visit_record contains:
        - manifest.json: Summary and answerable questions
        - page_content.md: Cleaned page text
        - extracted_data.json: Structured data (products, links, etc.)
        - screenshot.png: Visual capture (optional)
    """

    def __init__(self, turns_dir: Path = None):
        self.turns_dir = turns_dir or Path("panda_system_docs/turns")

    def _generate_slug(self, url: str, title: str = "") -> str:
        """Generate a unique slug for the visit record directory."""
        # Parse URL for domain
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")

        # Create short hash of URL for uniqueness
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]

        # Sanitize domain for directory name
        safe_domain = re.sub(r'[^a-z0-9]', '_', domain.lower())[:20]

        return f"{safe_domain}_{url_hash}"

    def _infer_content_type(self, url: str, title: str, content: str) -> str:
        """Infer the type of content from URL, title, and content."""
        url_lower = url.lower()
        title_lower = title.lower()
        content_lower = content.lower()[:2000]  # First 2000 chars

        # Forum indicators
        forum_patterns = ["thread", "forum", "discussion", "topic", "post", "comments", "replies"]
        if any(p in url_lower or p in title_lower for p in forum_patterns):
            return "forum_thread"

        # Product page indicators
        product_patterns = ["product", "/dp/", "/item/", "buy", "add to cart", "price"]
        if any(p in url_lower or p in content_lower for p in product_patterns):
            return "product_page"

        # Article indicators
        article_patterns = ["article", "blog", "news", "/post/", "published"]
        if any(p in url_lower or p in title_lower for p in article_patterns):
            return "article"

        # Search results
        if "search" in url_lower or "q=" in url_lower:
            return "search_results"

        return "webpage"

    def _extract_page_info(self, content: str, url: str) -> Optional[str]:
        """Extract pagination or count info from content."""
        content_lower = content.lower()

        # Page number patterns
        page_patterns = [
            r'page\s+(\d+)\s+of\s+(\d+)',
            r'(\d+)\s+of\s+(\d+)\s+page',
            r'page\s+(\d+)',
        ]
        for pattern in page_patterns:
            match = re.search(pattern, content_lower)
            if match:
                groups = match.groups()
                if len(groups) == 2:
                    return f"Page {groups[0]} of {groups[1]}"
                return f"Page {groups[0]}"

        # Comment/reply counts
        count_patterns = [
            r'(\d+)\s+(?:comments?|replies?|posts?)',
            r'(?:comments?|replies?|posts?):\s*(\d+)',
        ]
        for pattern in count_patterns:
            match = re.search(pattern, content_lower)
            if match:
                count = match.group(1)
                return f"{count} comments/replies"

        return None

    def _infer_answerable_questions(
        self,
        content_type: str,
        content: str,
        page_info: Optional[str],
        extracted_data: Optional[Dict] = None
    ) -> List[str]:
        """
        Infer what questions this page can answer.

        This is key for Context Gatherer's fast path - it can check
        if the user's question matches one of these patterns.
        """
        questions = []

        # Based on content type
        if content_type == "forum_thread":
            questions.extend([
                "how many pages is the thread",
                "how many replies are there",
                "what are people saying about",
                "what is the discussion about"
            ])
            if page_info:
                questions.append(f"pagination: {page_info}")

        elif content_type == "product_page":
            questions.extend([
                "what is the price",
                "is it in stock",
                "what are the specifications",
                "product details"
            ])
            if extracted_data and extracted_data.get("price"):
                questions.append(f"price info available")

        elif content_type == "search_results":
            questions.extend([
                "what results were found",
                "how many results",
                "list of options"
            ])

        elif content_type == "article":
            questions.extend([
                "what is the article about",
                "key points",
                "main topic"
            ])

        # Generic questions any page can answer
        questions.append("what is on this page")
        questions.append("page content summary")

        return questions

    def _summarize_content(self, content: str, title: str, max_length: int = 200) -> str:
        """Create a brief summary of the page content."""
        # Clean content
        clean = re.sub(r'\s+', ' ', content).strip()

        if len(clean) <= max_length:
            return clean

        # Try to find a good break point
        truncated = clean[:max_length]
        last_period = truncated.rfind('.')
        last_space = truncated.rfind(' ')

        if last_period > max_length // 2:
            return truncated[:last_period + 1]
        elif last_space > max_length // 2:
            return truncated[:last_space] + "..."
        else:
            return truncated + "..."

    def _extract_key_entities(self, content: str, title: str) -> List[str]:
        """Extract key entities for matching."""
        entities = []

        # Add title words (excluding common words)
        stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "is", "are"}
        for word in title.split():
            word_clean = word.strip(".,!?\"'").lower()
            if len(word_clean) > 2 and word_clean not in stop_words:
                entities.append(word_clean)

        # Look for quoted strings in content (often titles/names)
        quoted = re.findall(r'"([^"]+)"', content)
        entities.extend(quoted[:5])

        return list(set(entities))[:10]

    def create_visit_record(
        self,
        turn_number: int,
        url: str,
        title: str,
        page_content: str,
        extracted_data: Optional[Dict[str, Any]] = None,
        screenshot_path: Optional[str] = None
    ) -> Path:
        """
        Create a visit record for a page visit.

        Args:
            turn_number: Current turn number
            url: URL that was visited
            title: Page title
            page_content: Cleaned text content of the page
            extracted_data: Optional structured data (products, links, etc.)
            screenshot_path: Optional path to screenshot file

        Returns:
            Path to the created visit_record directory
        """
        # Create directory structure
        turn_dir = self.turns_dir / f"turn_{turn_number:06d}"
        visit_records_dir = turn_dir / "visit_records"
        slug = self._generate_slug(url, title)
        record_dir = visit_records_dir / slug
        record_dir.mkdir(parents=True, exist_ok=True)

        # Infer content type
        content_type = self._infer_content_type(url, title, page_content)

        # Extract page info (pagination, counts)
        page_info = self._extract_page_info(page_content, url)

        # Infer answerable questions
        answerable = self._infer_answerable_questions(
            content_type, page_content, page_info, extracted_data
        )

        # Extract domain
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")

        # Create manifest
        manifest = VisitRecordManifest(
            title=title,
            source_url=url,
            domain=domain,
            content_type=content_type,
            content_summary=self._summarize_content(page_content, title),
            page_info=page_info,
            answerable_questions=answerable,
            key_entities=self._extract_key_entities(page_content, title),
            captured_at=datetime.now(timezone.utc).isoformat(),
            has_page_content=True,
            has_extracted_data=extracted_data is not None,
            has_screenshot=screenshot_path is not None
        )

        # Write manifest.json
        manifest_path = record_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2))

        # Write page_content.md
        content_path = record_dir / "page_content.md"
        content_md = f"""# {title}

**URL:** {url}
**Captured:** {manifest.captured_at}
**Type:** {content_type}

---

{page_content}
"""
        content_path.write_text(content_md)

        # Write extracted_data.json if provided
        if extracted_data:
            data_path = record_dir / "extracted_data.json"
            data_path.write_text(json.dumps(extracted_data, indent=2, default=str))

        # Copy screenshot if provided
        if screenshot_path:
            import shutil
            screenshot_src = Path(screenshot_path)
            if screenshot_src.exists():
                screenshot_dst = record_dir / "screenshot.png"
                shutil.copy2(screenshot_src, screenshot_dst)
                manifest.has_screenshot = True
                # Update manifest with screenshot info
                manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2))

        logger.info(
            f"[VisitRecord] Created visit record for '{title[:50]}...' "
            f"at {record_dir} (type={content_type}, questions={len(answerable)})"
        )

        return record_dir


class VisitRecordReader:
    """
    Reads visit records for Context Gatherer's fast path.

    Checks if a question can be answered from cached page data.
    """

    def __init__(self, turns_dir: Path = None):
        self.turns_dir = turns_dir or Path("panda_system_docs/turns")

    def load_manifest(self, record_path: Path) -> Optional[VisitRecordManifest]:
        """Load manifest from a visit record directory."""
        manifest_path = record_path / "manifest.json"
        if not manifest_path.exists():
            return None

        try:
            data = json.loads(manifest_path.read_text())
            return VisitRecordManifest.from_dict(data)
        except Exception as e:
            logger.warning(f"[VisitRecord] Failed to load manifest from {record_path}: {e}")
            return None

    def load_page_content(self, record_path: Path) -> Optional[str]:
        """Load page content from a visit record."""
        content_path = record_path / "page_content.md"
        if not content_path.exists():
            return None
        return content_path.read_text()

    def load_extracted_data(self, record_path: Path) -> Optional[Dict[str, Any]]:
        """Load extracted data from a visit record."""
        data_path = record_path / "extracted_data.json"
        if not data_path.exists():
            return None
        try:
            return json.loads(data_path.read_text())
        except Exception:
            return None

    def can_answer_question(
        self,
        question: str,
        manifest: VisitRecordManifest
    ) -> bool:
        """
        Check if a question can potentially be answered from this visit record.

        This is a heuristic match - the actual answer extraction is done by
        Context Gatherer using the page_content.
        """
        question_lower = question.lower()

        # Check against answerable_questions
        for answerable in manifest.answerable_questions:
            # Fuzzy match: check if key terms overlap
            answerable_lower = answerable.lower()
            question_words = set(question_lower.split())
            answerable_words = set(answerable_lower.split())

            # If significant overlap, probably answerable
            overlap = question_words & answerable_words
            if len(overlap) >= 2:
                return True

        # Check against content summary
        if any(word in manifest.content_summary.lower() for word in question_lower.split() if len(word) > 3):
            return True

        # Check against key entities
        for entity in manifest.key_entities:
            if entity.lower() in question_lower:
                return True

        return False

    def find_matching_record(
        self,
        turn_number: int,
        question: str
    ) -> Optional[tuple[Path, VisitRecordManifest]]:
        """
        Find a visit record that can answer the given question.

        Args:
            turn_number: Turn to search in
            question: Question to answer

        Returns:
            Tuple of (record_path, manifest) if found, None otherwise
        """
        turn_dir = self.turns_dir / f"turn_{turn_number:06d}"
        visit_records_dir = turn_dir / "visit_records"

        if not visit_records_dir.exists():
            return None

        for record_dir in visit_records_dir.iterdir():
            if not record_dir.is_dir():
                continue

            manifest = self.load_manifest(record_dir)
            if manifest and self.can_answer_question(question, manifest):
                return (record_dir, manifest)

        return None


# Convenience functions

def create_visit_record(
    turn_number: int,
    url: str,
    title: str,
    page_content: str,
    extracted_data: Optional[Dict[str, Any]] = None,
    screenshot_path: Optional[str] = None
) -> Path:
    """Create a visit record for a page visit."""
    writer = VisitRecordWriter()
    return writer.create_visit_record(
        turn_number=turn_number,
        url=url,
        title=title,
        page_content=page_content,
        extracted_data=extracted_data,
        screenshot_path=screenshot_path
    )


def find_visit_record(turn_number: int, question: str) -> Optional[tuple[Path, VisitRecordManifest]]:
    """Find a visit record that can answer the given question."""
    reader = VisitRecordReader()
    return reader.find_matching_record(turn_number, question)
