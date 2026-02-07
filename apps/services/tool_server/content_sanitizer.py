"""
Budget-Aware Content Sanitizer for Panda

Removes objective noise from HTML while preserving ALL potentially relevant content.
Enforces hard token budgets via smart chunking.

DESIGN PRINCIPLES:
1. Remove ONLY objective noise (scripts, ads, navigation)
2. NO quality scoring or relevance filtering  
3. Enforce hard token limits via chunking
4. Context Manager evaluates ALL content sent

Usage:
    from apps.services.tool_server.content_sanitizer import sanitize_html

    result = sanitize_html(
        html="<html>...</html>",
        url="https://example.com",
        max_tokens=2000
    )

    # result = {
    #     "chunks": [{"text": "...", "chunk_id": 0, "total_chunks": 2, ...}],
    #     "metadata": {"title": "...", "description": "..."},
    #     "structured_data": {"prices_found": ["$25.99"], ...},
    #     "total_chunks": 2,
    #     "total_tokens_available": 3500
    # }
"""

from bs4 import BeautifulSoup, Comment
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import re
import logging

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Estimate token count (4 chars ≈ 1 token)"""
    if isinstance(text, str):
        return len(text) // 4
    return 0


@dataclass
class ContentChunk:
    """A budget-respecting chunk of content"""
    text: str
    chunk_id: int
    total_chunks: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    token_estimate: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "chunk_id": self.chunk_id,
            "total_chunks": self.total_chunks,
            "token_estimate": self.token_estimate,
            "has_more": self.chunk_id < self.total_chunks - 1,
            "metadata": self.metadata
        }


class ContentSanitizer:
    """
    Budget-aware content sanitizer.

    MAINTAINS EVIDENCE DISCIPLINE:
    - Removes objective noise (scripts, ads, nav)
    - NO quality scoring or content filtering
    - Enforces token budgets via chunking
    - Context Manager still evaluates ALL content
    """

    def __init__(self):
        # Pure noise (always remove)
        self.noise_tags = ['script', 'style', 'noscript', 'iframe', 'svg', 'canvas']
        self.structural_noise = ['header', 'footer', 'nav', 'aside', 'form', 'button']
        self.ad_patterns = [
            r'advertisement',
            r'ad-container',
            r'sponsored',
            r'promo-box',
            r'banner',
            r'google-ad',
            r'tracking'
        ]

    def sanitize(
        self,
        html: str,
        url: str,
        max_tokens: int = 2000,
        chunk_strategy: str = "smart"
    ) -> Dict[str, Any]:
        """
        Clean HTML and enforce token budget.

        Args:
            html: Raw HTML content
            url: Source URL
            max_tokens: Maximum tokens per chunk (hard limit)
            chunk_strategy: "smart" (section-aware) or "simple" (character-based)

        Returns:
            {
                "chunks": [ContentChunk],
                "metadata": dict,
                "structured_data": dict,
                "total_chunks": int,
                "total_tokens_available": int,
                "original_size": int,
                "cleaned_size": int,
                "reduction_pct": float
            }
        """
        if not html or len(html.strip()) < 50:
            return self._empty_result()

        try:
            soup = BeautifulSoup(html, 'html.parser')

            # 1. Remove noise (NO content decisions)
            self._remove_noise(soup)

            # 2. Extract metadata (non-destructive)
            metadata = self._extract_metadata(soup)

            # 3. Extract structured data (extraction NOT evaluation)
            structured = self._extract_structured_data(soup)

            # 4. Get ALL clean text
            clean_text = self._get_clean_text(soup)
            clean_text = self._normalize_text(clean_text)

            # 5. Chunk to respect budget
            if chunk_strategy == "smart":
                chunks = self._smart_chunk(clean_text, max_tokens, metadata, structured)
            else:
                chunks = self._simple_chunk(clean_text, max_tokens)

            total_tokens = sum(chunk.token_estimate for chunk in chunks)

            return {
                "chunks": [c.to_dict() for c in chunks],
                "metadata": metadata,
                "structured_data": structured,
                "total_chunks": len(chunks),
                "total_tokens_available": total_tokens,
                "original_size": len(html),
                "cleaned_size": len(clean_text),
                "reduction_pct": round((1 - len(clean_text) / len(html)) * 100, 1) if len(html) > 0 else 0
            }

        except Exception as e:
            logger.error(f"[ContentSanitizer] Error sanitizing {url}: {e}")
            return self._empty_result()

    def _smart_chunk(
        self,
        text: str,
        max_tokens: int,
        metadata: Dict[str, Any],
        structured: Dict[str, Any]
    ) -> List[ContentChunk]:
        """
        Smart chunking: Preserve paragraph boundaries, prioritize metadata.

        Chunk 0 always contains:
        - Metadata (title, description)
        - Structured data (prices, JSON-LD)
        - As much content as fits in budget
        """
        chunks = []

        # Build chunk 0 header (metadata + structured)
        chunk_0_parts = []
        if metadata.get('title'):
            chunk_0_parts.append(f"TITLE: {metadata['title']}")
        if metadata.get('description'):
            chunk_0_parts.append(f"DESCRIPTION: {metadata['description']}")
        if structured.get('prices_found'):
            # Limit to first 5 prices
            prices = structured['prices_found'][:5]
            chunk_0_parts.append(f"PRICES: {', '.join(prices)}")

        metadata_text = '\n\n'.join(chunk_0_parts)
        metadata_tokens = estimate_tokens(metadata_text)
        remaining_budget = max_tokens - metadata_tokens - 50  # Safety margin

        # Split text into paragraphs (preserve structure)
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]

        current_chunk_parts = chunk_0_parts.copy() if chunk_0_parts else []
        current_chunk_tokens = metadata_tokens

        for para in paragraphs:
            para_tokens = estimate_tokens(para)

            # Check if adding this paragraph would exceed budget
            if current_chunk_tokens + para_tokens <= max_tokens:
                # Fits in current chunk
                current_chunk_parts.append(para)
                current_chunk_tokens += para_tokens
            else:
                # Would exceed budget - need to handle

                # If current chunk is non-empty, save it first
                if current_chunk_parts:
                    chunk_text = '\n\n'.join(current_chunk_parts)
                    chunks.append(ContentChunk(
                        text=chunk_text,
                        chunk_id=len(chunks),
                        total_chunks=0,  # Update later
                        metadata={"has_metadata": len(chunks) == 0},
                        token_estimate=estimate_tokens(chunk_text)
                    ))
                    current_chunk_parts = []
                    current_chunk_tokens = 0

                # Now handle the paragraph that didn't fit
                if para_tokens > max_tokens:
                    # Paragraph itself exceeds budget - must split
                    para_chunks = self._split_oversized_paragraph(para, max_tokens)
                    for pc in para_chunks:
                        chunks.append(ContentChunk(
                            text=pc,
                            chunk_id=len(chunks),
                            total_chunks=0,
                            metadata={"truncated_paragraph": True},
                            token_estimate=estimate_tokens(pc)
                        ))
                else:
                    # Paragraph fits in budget alone - start new chunk
                    current_chunk_parts = [para]
                    current_chunk_tokens = para_tokens

        # Add final chunk
        if current_chunk_parts:
            chunk_text = '\n\n'.join(current_chunk_parts)
            chunks.append(ContentChunk(
                text=chunk_text,
                chunk_id=len(chunks),
                total_chunks=0,
                metadata={},
                token_estimate=estimate_tokens(chunk_text)
            ))

        # Update total_chunks
        total = len(chunks) if chunks else 1
        for chunk in chunks:
            chunk.total_chunks = total

        return chunks if chunks else [self._empty_chunk()]

    def _split_oversized_paragraph(self, para: str, max_tokens: int) -> List[str]:
        """Split paragraph that exceeds budget"""
        sentences = re.split(r'(?<=[.!?])\s+', para)
        chunks = []
        current = []
        current_tokens = 0

        for sentence in sentences:
            sent_tokens = estimate_tokens(sentence)

            if current_tokens + sent_tokens <= max_tokens:
                current.append(sentence)
                current_tokens += sent_tokens
            else:
                if current:
                    chunks.append(' '.join(current))

                # Hard truncate if single sentence too long
                if sent_tokens > max_tokens:
                    max_chars = max_tokens * 4
                    chunks.append(sentence[:max_chars] + "...")
                else:
                    current = [sentence]
                    current_tokens = sent_tokens

        if current:
            chunks.append(' '.join(current))

        return chunks if chunks else [""]

    def _simple_chunk(self, text: str, max_tokens: int) -> List[ContentChunk]:
        """Simple character-based chunking (fallback)"""
        max_chars = max_tokens * 4
        chunks = []

        for i in range(0, len(text), max_chars):
            chunk_text = text[i:i + max_chars]
            chunks.append(ContentChunk(
                text=chunk_text,
                chunk_id=len(chunks),
                total_chunks=0,
                metadata={},
                token_estimate=estimate_tokens(chunk_text)
            ))

        total = len(chunks) if chunks else 1
        for chunk in chunks:
            chunk.total_chunks = total

        return chunks if chunks else [self._empty_chunk()]

    def _remove_noise(self, soup: BeautifulSoup):
        """Remove objectively useless content (NO quality decisions)"""
        # Remove noise tags
        for tag in self.noise_tags:
            for elem in soup.find_all(tag):
                elem.decompose()

        # Remove HTML comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        # Remove ads by pattern
        for pattern in self.ad_patterns:
            for elem in soup.find_all(class_=re.compile(pattern, re.I)):
                elem.decompose()
            for elem in soup.find_all(id=re.compile(pattern, re.I)):
                elem.decompose()

        # Remove structural noise
        for tag in self.structural_noise:
            for elem in soup.find_all(tag):
                elem.decompose()

    def _extract_metadata(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extract page metadata (non-destructive)"""
        metadata = {}

        title_tag = soup.find('title')
        if title_tag:
            metadata['title'] = title_tag.get_text(strip=True)

        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc:
            metadata['description'] = meta_desc.get('content', '')

        og_title = soup.find('meta', property='og:title')
        if og_title:
            metadata['og_title'] = og_title.get('content', '')

        og_desc = soup.find('meta', property='og:description')
        if og_desc:
            metadata['og_description'] = og_desc.get('content', '')

        return metadata

    def _extract_structured_data(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """
        Extract structured data (NOT evaluation).
        Context Manager decides if data is relevant/trustworthy.
        """
        structured = {}

        # Extract JSON-LD
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        if json_ld_scripts:
            import json
            structured['json_ld'] = []
            for script in json_ld_scripts:
                try:
                    if script.string:
                        data = json.loads(script.string)
                        structured['json_ld'].append(data)
                except Exception:
                    pass

        # Extract visible prices (pattern matching, not filtering)
        price_pattern = r'\$\d+(?:,\d{3})*(?:\.\d{2})?'
        text = soup.get_text()
        prices = re.findall(price_pattern, text)
        if prices:
            # Deduplicate and limit
            structured['prices_found'] = list(set(prices))[:20]

        return structured

    def _convert_links_to_markdown(self, soup: BeautifulSoup) -> None:
        """
        Convert <a href="url">text</a> to [text](url) markdown format.

        This preserves link URLs in the extracted text so the LLM can see
        where links point to, enabling follow-up queries about specific items.
        """
        links_found = 0
        links_converted = 0

        for a_tag in soup.find_all('a', href=True):
            links_found += 1
            href = a_tag.get('href', '')
            text = a_tag.get_text(strip=True)

            # Skip empty links, anchors, and javascript
            if not text or not href or href.startswith('#') or href.startswith('javascript:'):
                continue

            # Skip very long URLs (likely tracking/noise)
            if len(href) > 200:
                continue

            # Replace tag with markdown format
            markdown_link = f"[{text}]({href})"
            a_tag.replace_with(markdown_link)
            links_converted += 1

        logger.info(f"[ContentSanitizer] DEBUG: links_found={links_found}, links_converted={links_converted}")

    def _get_clean_text(self, soup: BeautifulSoup) -> str:
        """Extract ALL visible text (no filtering), preserving link URLs as markdown."""
        # Convert links to markdown before extracting text
        self._convert_links_to_markdown(soup)
        return soup.get_text(separator='\n\n', strip=True)

    def _normalize_text(self, text: str) -> str:
        """Normalize whitespace (cosmetic only)"""
        # Remove excessive blank lines
        text = re.sub(r'\n{3,}', '\n\n', text)

        # Remove excessive spaces
        text = re.sub(r' {2,}', ' ', text)

        # Remove leading/trailing whitespace per line
        lines = [line.strip() for line in text.split('\n')]
        return '\n'.join(line for line in lines if line)

    def _empty_result(self) -> Dict[str, Any]:
        """Empty result structure"""
        return {
            "chunks": [],
            "metadata": {},
            "structured_data": {},
            "total_chunks": 0,
            "total_tokens_available": 0,
            "original_size": 0,
            "cleaned_size": 0,
            "reduction_pct": 0.0
        }

    def _empty_chunk(self) -> ContentChunk:
        """Empty chunk"""
        return ContentChunk(
            text="",
            chunk_id=0,
            total_chunks=1,
            metadata={},
            token_estimate=0
        )


# Global instance
_sanitizer = ContentSanitizer()


def sanitize_html(
    html: str,
    url: str,
    max_tokens: int = 2000,
    chunk_strategy: str = "smart"
) -> Dict[str, Any]:
    """
    Public API for budget-aware content sanitization.

    Args:
        html: Raw HTML content
        url: Source URL
        max_tokens: Maximum tokens per chunk (default: 2000)
        chunk_strategy: "smart" (preserves paragraphs) or "simple" (character-based)

    Returns:
        Dictionary with chunks, metadata, structured data, and stats
    """
    return _sanitizer.sanitize(html, url, max_tokens, chunk_strategy)
