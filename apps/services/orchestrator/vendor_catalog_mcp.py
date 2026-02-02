"""
orchestrator/vendor_catalog_mcp.py

Vendor catalog exploration tool - deep-crawls vendor websites to extract
all available products/listings with pagination and category support.

Created: 2025-11-16
"""

import logging
import re
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)


async def explore_catalog(
    vendor_url: str,
    vendor_name: str,
    category: str = "all",
    max_items: int = 20,
    session_id: str = "default"
) -> Dict[str, Any]:
    """
    Deep-crawl vendor catalog to extract all available products/listings.

    Args:
        vendor_url: Base URL of vendor website
        vendor_name: Display name of vendor
        category: Optional category filter ("available", "retired", "upcoming", "all")
        max_items: Maximum items to extract (default 20)
        session_id: Browser session ID for cookie reuse

    Returns:
        {
            "vendor_name": str,
            "vendor_url": str,
            "items_found": int,
            "pages_crawled": int,
            "items": [...],
            "contact_info": {...},
            "metadata": {...}
        }
    """
    from apps.services.orchestrator.human_page_reader import HumanPageReader

    logger.info(f"[VendorCatalog] Starting exploration of {vendor_name} (category={category})")

    reader = HumanPageReader(session_id=session_id)
    items = []
    pages_crawled = 0

    try:
        # Step 1: Visit main page
        logger.info(f"[VendorCatalog] Visiting main page: {vendor_url}")
        main_page = await reader.visit_and_extract(vendor_url)

        # Step 2: Detect catalog structure
        catalog_structure = detect_catalog_structure(main_page, vendor_url)
        logger.info(
            f"[VendorCatalog] Detected structure: "
            f"pagination={catalog_structure['has_pagination']}, "
            f"categories={len(catalog_structure['category_links'])}, "
            f"item_links={len(catalog_structure['item_links'])}"
        )

        # Step 3: Determine starting URL
        if category != "all" and category in catalog_structure["category_links"]:
            start_url = catalog_structure["category_links"][category]
            logger.info(f"[VendorCatalog] Starting from category page: {start_url}")
        else:
            start_url = vendor_url

        # Step 4: Crawl pages
        current_url = start_url
        visited_urls = set()

        while len(items) < max_items and pages_crawled < 5 and current_url:
            # Avoid infinite loops
            if current_url in visited_urls:
                logger.warning(f"[VendorCatalog] Already visited {current_url}, stopping")
                break

            visited_urls.add(current_url)

            logger.info(f"[VendorCatalog] Crawling page {pages_crawled + 1}: {current_url}")
            page_data = await reader.visit_and_extract(current_url)

            # Extract items from this page
            page_items = extract_product_listings(page_data, vendor_url)
            logger.info(f"[VendorCatalog] Extracted {len(page_items)} items from page")
            items.extend(page_items)
            pages_crawled += 1

            # Find next page
            next_url = find_next_page_link(page_data, current_url, vendor_url)
            if not next_url:
                logger.info(f"[VendorCatalog] No more pages found")
                break

            current_url = next_url

        # Step 5: Extract contact info (from main page)
        contact_info = extract_contact_info(main_page, vendor_url)

        logger.info(
            f"[VendorCatalog] Exploration complete: {len(items)} items "
            f"from {pages_crawled} pages"
        )

        return {
            "vendor_name": vendor_name,
            "vendor_url": vendor_url,
            "items_found": len(items),
            "pages_crawled": pages_crawled,
            "items": items[:max_items],
            "contact_info": contact_info,
            "metadata": {
                "category": category,
                "crawl_timestamp": datetime.now(timezone.utc).isoformat()
            }
        }

    except Exception as e:
        logger.error(f"[VendorCatalog] Exploration failed: {e}", exc_info=True)
        return {
            "vendor_name": vendor_name,
            "vendor_url": vendor_url,
            "items_found": 0,
            "pages_crawled": 0,
            "items": [],
            "contact_info": {},
            "error": str(e),
            "metadata": {
                "category": category,
                "crawl_timestamp": datetime.now(timezone.utc).isoformat()
            }
        }


def detect_catalog_structure(page_data: Dict[str, Any], base_url: str) -> Dict[str, Any]:
    """
    Analyze page HTML/links to detect catalog navigation patterns.

    Detects:
    - Pagination links (Next, numbered pages, Load More)
    - Category links (Available, Sold, Upcoming, Retired)
    - Individual item/product links

    Returns:
        {
            "pagination_links": [urls],
            "category_links": {category_name: url},
            "item_links": [urls],
            "has_pagination": bool
        }
    """
    html = page_data.get("html", "")
    links = page_data.get("links", [])

    structure = {
        "pagination_links": [],
        "category_links": {},
        "item_links": [],
        "has_pagination": False
    }

    for link in links:
        href = link.get("href", "")
        text = link.get("text", "").lower().strip()

        # Convert relative URLs to absolute
        if href and not href.startswith("http"):
            href = urljoin(base_url, href)

        # Detect pagination
        if any(word in text for word in ["next", "more", "→"]) or text.isdigit():
            structure["pagination_links"].append(href)
            structure["has_pagination"] = True

        # Detect categories
        elif any(cat in text for cat in ["available", "retired", "upcoming", "sold", "shop", "catalog", "inventory"]):
            structure["category_links"][text] = href

        # Detect item pages (product detail pages)
        elif any(pattern in href for pattern in ["/item/", "/listing/", "/hamster/", "/product/", "/detail/"]):
            structure["item_links"].append(href)

    return structure


def extract_product_listings(page_data: Dict[str, Any], base_url: str) -> List[Dict[str, Any]]:
    """
    Extract structured product data from a catalog page.

    Returns list of products with:
    - title, price, availability, description, url, image_url
    - details: {born_date, color, sex, status, etc.}
    """
    from apps.services.orchestrator.product_extractor import extract_products

    # Use existing product extractor
    products = extract_products(page_data)

    # Enhance with catalog-specific fields
    for product in products:
        # Ensure URL is absolute
        if "url" in product and product["url"] and not product["url"].startswith("http"):
            product["url"] = urljoin(base_url, product["url"])

        # Add availability status detection
        description = product.get("description", "")
        product["availability"] = extract_availability_status(description)

        # Try to extract birth date
        born_date = extract_born_date(description)
        if born_date:
            if "details" not in product:
                product["details"] = {}
            product["details"]["born_date"] = born_date

    return products


def extract_availability_status(description: str) -> str:
    """
    Detect availability status from product description.

    Returns: "Available now" | "Reserved/Sold" | "Upcoming" | "Unknown"
    """
    if not description:
        return "Unknown"

    desc_lower = description.lower()

    # Sold/Reserved indicators
    if any(word in desc_lower for word in ["sold", "reserved", "adopted", "pending", "hold"]):
        return "Reserved/Sold"

    # Available indicators
    if any(word in desc_lower for word in ["available", "ready", "in stock", "now"]):
        return "Available now"

    # Upcoming indicators
    if any(word in desc_lower for word in ["upcoming", "expected", "litter", "soon", "future", "coming"]):
        return "Upcoming"

    # Date detection (e.g., "Ready 2025-12-01")
    if re.search(r'\d{4}-\d{2}-\d{2}', desc_lower):
        return "Upcoming (dated)"

    return "Unknown"


def extract_born_date(description: str) -> Optional[str]:
    """
    Extract birth date from product description.

    Patterns: "Born: 2025-10-15", "DOB 10/15/2025", "Born Oct 15"

    Returns: ISO date string (YYYY-MM-DD) or None
    """
    if not description:
        return None

    # ISO date pattern
    iso_match = re.search(r'(\d{4}-\d{2}-\d{2})', description)
    if iso_match:
        return iso_match.group(1)

    # US date pattern
    us_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', description)
    if us_match:
        try:
            from datetime import datetime
            date_obj = datetime.strptime(us_match.group(1), "%m/%d/%Y")
            return date_obj.strftime("%Y-%m-%d")
        except ValueError:
            pass

    return None


def extract_contact_info(page_data: Dict[str, Any], base_url: str) -> Dict[str, Optional[str]]:
    """
    Extract vendor contact information from page.

    Returns:
        {
            "email": str | None,
            "phone": str | None,
            "application_url": str | None,
            "contact_page_url": str | None
        }
    """
    html = page_data.get("html", "")
    links = page_data.get("links", [])

    contact = {
        "email": None,
        "phone": None,
        "application_url": None,
        "contact_page_url": None
    }

    # Extract email addresses
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    emails = re.findall(email_pattern, html)
    if emails:
        contact["email"] = emails[0]  # Take first email found

    # Extract phone numbers (US format)
    phone_pattern = r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'
    phones = re.findall(phone_pattern, html)
    if phones:
        contact["phone"] = phones[0]

    # Find contact/application pages
    for link in links:
        href = link.get("href", "")
        text = link.get("text", "").lower()

        if not href:
            continue

        # Convert to absolute URL
        if not href.startswith("http"):
            href = urljoin(base_url, href)

        if "contact" in text or "contact" in href:
            contact["contact_page_url"] = href

        if any(word in text for word in ["apply", "application", "adopt", "adoption"]):
            contact["application_url"] = href

    return contact


def find_next_page_link(page_data: Dict[str, Any], current_url: str, base_url: str) -> Optional[str]:
    """
    Find the "next page" link for pagination crawling.

    Looks for:
    - Links with text "Next", "→", "More"
    - Numbered pagination (if current is page 2, find page 3)
    - "Load More" buttons with href
    """
    links = page_data.get("links", [])

    # Strategy 1: Find "Next" link
    for link in links:
        text = link.get("text", "").lower().strip()
        href = link.get("href", "")

        if any(word in text for word in ["next", "→", "more"]):
            # Convert to absolute URL
            if href and not href.startswith("http"):
                href = urljoin(base_url, href)
            return href

    # Strategy 2: Find numbered pagination
    # Extract page number from current URL
    page_match = re.search(r'[?&]page=(\d+)', current_url)
    if page_match:
        current_page = int(page_match.group(1))
        next_page = current_page + 1

        # Look for next page number link
        for link in links:
            text = link.get("text", "").strip()
            href = link.get("href", "")

            if text == str(next_page):
                if href and not href.startswith("http"):
                    href = urljoin(base_url, href)
                return href

    return None
