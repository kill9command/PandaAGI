"""
apps/services/tool_server/data_normalizer.py

Data normalization and cleaning for product search results.
Ensures consistent formatting across different sources and APIs.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse
import hashlib


class ProductNormalizer:
    """
    Normalizes product data from various sources into consistent formats.
    Handles prices, availability, seller types, and deduplication.
    """
    
    def __init__(self):
        # Synonym maps for different categories
        self.synonym_maps: Dict[str, Dict[str, List[str]]] = {
            "pet:hamster": {
                "Syrian": ["Golden", "Syrian hamster", "Golden hamster", "Teddy bear hamster"],
                "Dwarf": ["Dwarf hamster", "Campbell", "Winter White", "Roborovski"],
                "Chinese": ["Chinese hamster", "Chinese dwarf"],
            },
            "computing:laptop": {
                "notebook": ["laptop", "notebook computer", "portable computer"],
                "ultrabook": ["thin laptop", "lightweight laptop"],
            },
        }
        
        # Availability mappings
        self.availability_patterns = {
            "in_stock": [
                r"\bin stock\b",
                r"\bavailable\b",
                r"\bavailable now\b",
                r"\bin-stock\b",
                r"\bready to ship\b",
                r"\bin store\b",
            ],
            "out_of_stock": [
                r"\bout of stock\b",
                r"\bunavailable\b",
                r"\bsold out\b",
                r"\bnot available\b",
                r"\btemporarily unavailable\b",
            ],
            "preorder": [
                r"\bpreorder\b",
                r"\bpre-order\b",
                r"\bcoming soon\b",
                r"\bbackorder\b",
            ],
        }
        
        # Seller type indicators
        self.seller_type_patterns = {
            "breeder": [
                r"\bbreeder\b",
                r"\bbreeding\b",
                r"\bUSDA\b",
                r"\bpuppies\b",
                r"\bkittens\b",
                r"\blitter\b",
            ],
            "retailer": [
                r"\bpet\s*store\b",
                r"\bpet\s*shop\b",
                r"\bretailer\b",
                r"\bstore\b",
            ],
            "marketplace": [
                r"\bmarketplace\b",
                r"\bclassified\b",
                r"\blisting\b",
            ],
            "educational": [
                r"\beducation\b",
                r"\bschool\b",
                r"\bclassroom\b",
                r"\bteaching\b",
                r"\b\.edu\b",
                r"\bnsta\b",
            ],
        }
    
    def normalize_price(self, raw_price: Any) -> Tuple[Optional[float], str]:
        """
        Convert any price format to (amount, currency).
        
        Examples:
            "$25.99" → (25.99, "USD")
            "£35" → (35.0, "GBP")
            "25.99 USD" → (25.99, "USD")
            25.99 → (25.99, "USD")
        
        Returns:
            (amount, currency) or (None, "USD") if unparseable
        """
        if raw_price is None:
            return (None, "USD")
        
        # Already a number
        if isinstance(raw_price, (int, float)):
            return (float(raw_price), "USD")
        
        # String processing
        text = str(raw_price).strip()
        
        if not text:
            return (None, "USD")
        
        # Detect currency
        currency = "USD"
        if "£" in text or "GBP" in text.upper():
            currency = "GBP"
        elif "€" in text or "EUR" in text.upper():
            currency = "EUR"
        elif "¥" in text or "JPY" in text.upper() or "CNY" in text.upper():
            currency = "JPY"
        elif "CAD" in text.upper():
            currency = "CAD"
        elif "AUD" in text.upper():
            currency = "AUD"
        
        # Extract numeric value
        # Remove currency symbols and letters
        cleaned = re.sub(r'[^\d.,\-]', '', text)
        cleaned = cleaned.replace(',', '')  # Remove thousands separators
        
        if not cleaned or cleaned == '-':
            return (None, currency)
        
        try:
            amount = float(cleaned)
            return (amount, currency)
        except ValueError:
            return (None, currency)
    
    def normalize_availability(self, raw_status: str) -> str:
        """
        Map various availability formats to standard enum.
        
        Returns:
            "in_stock" | "out_of_stock" | "preorder" | "unknown"
        """
        if not raw_status:
            return "unknown"
        
        text = str(raw_status).lower().strip()
        
        # Check patterns for each status
        for status, patterns in self.availability_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    return status
        
        return "unknown"
    
    def normalize_seller_type(
        self,
        seller_name: str = "",
        url: str = "",
        description: str = "",
    ) -> str:
        """
        Classify seller type based on available signals.
        
        Returns:
            "breeder" | "retailer" | "marketplace" | "educational" | "unknown"
        """
        combined_text = " ".join([seller_name, url, description]).lower()
        
        if not combined_text.strip():
            return "unknown"
        
        # Check patterns for each type
        scores: Dict[str, int] = {}
        
        for seller_type, patterns in self.seller_type_patterns.items():
            score = 0
            for pattern in patterns:
                matches = len(re.findall(pattern, combined_text, re.IGNORECASE))
                score += matches
            if score > 0:
                scores[seller_type] = score
        
        if not scores:
            return "unknown"
        
        # Return type with highest score
        return max(scores.items(), key=lambda x: x[1])[0]
    
    def get_synonyms(self, category: str, term: str) -> List[str]:
        """
        Get synonyms for a term in a given category.
        
        Args:
            category: "pet:hamster", "computing:laptop", etc.
            term: The term to look up
        
        Returns:
            List of synonyms including the original term
        """
        if category not in self.synonym_maps:
            return [term]
        
        synonym_dict = self.synonym_maps[category]
        
        # Check if term is a key
        if term in synonym_dict:
            return [term] + synonym_dict[term]
        
        # Check if term is in any synonym list
        for key, synonyms in synonym_dict.items():
            if term.lower() in [s.lower() for s in synonyms]:
                return [key] + synonyms
        
        return [term]
    
    def add_synonyms(self, category: str, key: str, synonyms: List[str]):
        """Add custom synonyms for a category."""
        if category not in self.synonym_maps:
            self.synonym_maps[category] = {}
        self.synonym_maps[category][key] = synonyms
    
    def compute_listing_hash(
        self,
        title: str,
        url: str,
        seller_name: str = ""
    ) -> str:
        """
        Compute a hash for deduplication.
        
        Similar listings should have similar hashes.
        Uses normalized title + domain + seller name.
        """
        # Normalize title (lowercase, remove punctuation)
        norm_title = re.sub(r'[^\w\s]', '', title.lower()).strip()
        norm_title = ' '.join(norm_title.split())  # Normalize whitespace
        
        # Extract domain from URL
        try:
            domain = urlparse(url).netloc.lower()
        except Exception:
            domain = ""
        
        # Normalize seller name
        norm_seller = re.sub(r'[^\w\s]', '', seller_name.lower()).strip()
        
        # Combine for hash
        hash_input = f"{norm_title}|{domain}|{norm_seller}"
        return hashlib.md5(hash_input.encode()).hexdigest()[:12]
    
    def normalize_url(self, url: str) -> str:
        """
        Normalize URL for comparison (remove query params, fragments).
        """
        try:
            parsed = urlparse(url)
            # Keep only scheme + netloc + path
            normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            # Remove trailing slash
            return normalized.rstrip('/')
        except Exception:
            return url
    
    def is_duplicate(
        self,
        listing1: Dict[str, Any],
        listing2: Dict[str, Any],
        *,
        title_similarity_threshold: float = 0.8,
        same_domain: bool = True
    ) -> bool:
        """
        Check if two listings are likely duplicates.
        
        Args:
            listing1, listing2: Product listing dicts
            title_similarity_threshold: Minimum title similarity (0-1)
            same_domain: If True, only consider same-domain duplicates
        
        Returns:
            True if listings are likely duplicates
        """
        url1 = listing1.get("url", "")
        url2 = listing2.get("url", "")
        
        # Exact URL match (after normalization)
        if self.normalize_url(url1) == self.normalize_url(url2):
            return True
        
        # Check domain requirement
        if same_domain:
            try:
                domain1 = urlparse(url1).netloc
                domain2 = urlparse(url2).netloc
                if domain1 != domain2:
                    return False
            except Exception:
                pass
        
        # Compute title similarity
        title1 = listing1.get("title", "").lower()
        title2 = listing2.get("title", "").lower()
        
        if not title1 or not title2:
            return False
        
        similarity = self._string_similarity(title1, title2)
        
        if similarity >= title_similarity_threshold:
            # Also check price if available
            price1 = listing1.get("price")
            price2 = listing2.get("price")
            
            if price1 and price2:
                # If prices are very different, not a duplicate
                if abs(price1 - price2) / max(price1, price2) > 0.2:  # 20% difference
                    return False
            
            return True
        
        return False
    
    def _string_similarity(self, s1: str, s2: str) -> float:
        """
        Compute simple string similarity (Jaccard on words).
        Returns value between 0 and 1.
        """
        words1 = set(s1.lower().split())
        words2 = set(s2.lower().split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1 & words2
        union = words1 | words2
        
        return len(intersection) / len(union) if union else 0.0
    
    def deduplicate_listings(
        self,
        listings: List[Dict[str, Any]],
        *,
        keep_first: bool = True
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Remove duplicate listings from a list.
        
        Args:
            listings: List of product listing dicts
            keep_first: If True, keep first occurrence; else keep highest relevance
        
        Returns:
            (unique_listings, duplicates_removed)
        """
        if not listings:
            return ([], [])
        
        unique: List[Dict[str, Any]] = []
        duplicates: List[Dict[str, Any]] = []
        seen_hashes: Set[str] = set()
        
        for listing in listings:
            # Compute hash
            listing_hash = self.compute_listing_hash(
                listing.get("title", ""),
                listing.get("url", ""),
                listing.get("seller_name", "")
            )
            
            # Check hash first (fast)
            if listing_hash in seen_hashes:
                duplicates.append(listing)
                continue
            
            # Check for similar duplicates in unique list
            is_dup = False
            for unique_listing in unique:
                if self.is_duplicate(listing, unique_listing):
                    is_dup = True
                    duplicates.append(listing)
                    
                    # If keeping highest relevance, maybe replace
                    if not keep_first:
                        new_score = listing.get("relevance_score", 0.0)
                        old_score = unique_listing.get("relevance_score", 0.0)
                        if new_score > old_score:
                            # Swap
                            unique.remove(unique_listing)
                            unique.append(listing)
                            duplicates.remove(listing)
                            duplicates.append(unique_listing)
                    break
            
            if not is_dup:
                unique.append(listing)
                seen_hashes.add(listing_hash)
        
        return (unique, duplicates)


# Singleton instance
_normalizer = None

def get_normalizer() -> ProductNormalizer:
    """Get singleton normalizer instance"""
    global _normalizer
    if _normalizer is None:
        _normalizer = ProductNormalizer()
    return _normalizer
