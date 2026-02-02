"""
Note template rendering for obsidian_memory.

Per architecture/services/OBSIDIAN_MEMORY.md:
- Research Finding Template
- Product Knowledge Template
- User Preference Template
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
import yaml

logger = logging.getLogger(__name__)

# Template directory
TEMPLATE_DIR = Path("panda_system_docs/obsidian_memory/Meta/Templates")


def render_template(artifact_type: str, variables: Dict[str, Any]) -> str:
    """
    Render a note template with the given variables.

    Args:
        artifact_type: "research", "product", or "preference"
        variables: Dict of template variables

    Returns:
        Rendered markdown content with frontmatter
    """
    # Map artifact type to template
    template_map = {
        "research": "research_finding.md",
        "product": "product_knowledge.md",
        "preference": "user_preference.md",
        "fact": "research_finding.md",  # Use research template for facts
    }

    template_name = template_map.get(artifact_type, "research_finding.md")
    template_path = TEMPLATE_DIR / template_name

    if template_path.exists():
        template = template_path.read_text()
    else:
        # Fallback to built-in templates
        template = _get_builtin_template(artifact_type)

    # Replace template variables
    for key, value in variables.items():
        placeholder = f"{{{{{key}}}}}"
        if isinstance(value, list):
            if key in ["tags", "source_urls", "related"]:
                # Format as YAML list
                # For empty lists, we need special handling based on template format
                if value:
                    value_str = "\n".join(f"  - {item}" for item in value)
                else:
                    # Empty list - check if placeholder is on its own line
                    # If so, replace the whole line including the key
                    value_str = "[]"
            else:
                value_str = str(value)
        elif value is None:
            value_str = ""
        else:
            value_str = str(value)

        template = template.replace(placeholder, value_str)

    # Fix empty lists that ended up on their own line (invalid YAML)
    # Convert "key:\n[]" to "key: []"
    template = re.sub(r'(\w+):\n\[\]', r'\1: []', template)

    # Clean up any remaining placeholders
    template = re.sub(r'\{\{[^}]+\}\}', '', template)

    return template


def _get_builtin_template(artifact_type: str) -> str:
    """Get built-in template for artifact type."""

    if artifact_type == "research":
        return """---
artifact_type: research
topic: {{topic}}
subtopic: {{subtopic}}
created: {{created}}
modified: {{modified}}
source: {{source}}
source_urls:
{{source_urls}}
confidence: {{confidence}}
status: active
tags:
{{tags}}
related:
{{related}}
expires: {{expires}}
---

# {{title}}

## Summary
{{summary}}

## Key Findings
{{findings}}

## Sources
| Source | Date | Relevance |
|--------|------|-----------|
{{source_table}}

## Related Research
{{related_links}}
"""

    elif artifact_type == "product":
        return """---
artifact_type: product
product_name: {{product_name}}
category: {{category}}
created: {{created}}
modified: {{modified}}
source: {{source}}
confidence: {{confidence}}
status: active
tags:
{{tags}}
related:
{{related}}
---

# {{product_name}}

## Overview
{{overview}}

## Specifications
| Spec | Value |
|------|-------|
{{specs_table}}

## Price History
| Date | Vendor | Price |
|------|--------|-------|
{{price_table}}

## Community Sentiment
{{sentiment}}

## Pros
{{pros}}

## Cons
{{cons}}

## Related
{{related_links}}
"""

    elif artifact_type == "preference":
        return """---
artifact_type: preference
user_id: {{user_id}}
created: {{created}}
modified: {{modified}}
confidence: {{confidence}}
status: active
---

# User Preferences: {{user_id}}

## Budget Preferences
{{budget_preferences}}

## Category Preferences
{{category_preferences}}

## Brand Preferences
{{brand_preferences}}

## Shopping Preferences
{{shopping_preferences}}

## Learned From
{{learned_from}}
"""

    else:
        # Generic template
        return """---
artifact_type: {{artifact_type}}
topic: {{topic}}
created: {{created}}
modified: {{modified}}
confidence: {{confidence}}
status: active
tags:
{{tags}}
---

# {{title}}

{{summary}}

{{findings}}
"""


def format_research_content(
    topic: str,
    summary: str,
    findings: List[Dict[str, Any]],
    source_urls: List[str] = None,
    tags: List[str] = None,
    confidence: float = 0.8,
) -> Dict[str, Any]:
    """
    Format research findings into template variables.

    Args:
        topic: Research topic
        summary: Brief summary
        findings: List of finding dicts with 'title' and 'content'
        source_urls: Source URLs
        tags: Tags for categorization
        confidence: Confidence score

    Returns:
        Dict of template variables
    """
    now = datetime.now()

    # Format findings as markdown
    findings_md = ""
    for finding in findings:
        if isinstance(finding, dict):
            title = finding.get("title", "Finding")
            content = finding.get("content", "")
            findings_md += f"### {title}\n{content}\n\n"
        else:
            findings_md += f"- {finding}\n"

    return {
        "topic": topic,
        "subtopic": "",
        "created": now.isoformat(),
        "modified": now.isoformat(),
        "source": "internet_research",
        "source_urls": source_urls or [],
        "confidence": confidence,
        "tags": tags or [],
        "related": [],
        "expires": None,  # Will be calculated by write.py
        "title": topic,
        "summary": summary,
        "findings": findings_md.strip(),
        "source_table": "",  # Will be formatted by write.py
        "related_links": "",
    }


def format_product_content(
    product_name: str,
    category: str,
    overview: str,
    specs: Dict[str, str] = None,
    prices: List[Dict[str, Any]] = None,
    pros: List[str] = None,
    cons: List[str] = None,
    sentiment: str = "",
    tags: List[str] = None,
    confidence: float = 0.8,
) -> Dict[str, Any]:
    """
    Format product knowledge into template variables.

    Args:
        product_name: Product name
        category: Product category
        overview: Brief overview
        specs: Specifications dict
        prices: Price history list
        pros: List of pros
        cons: List of cons
        sentiment: Community sentiment summary
        tags: Tags for categorization
        confidence: Confidence score

    Returns:
        Dict of template variables
    """
    now = datetime.now()

    return {
        "product_name": product_name,
        "category": category,
        "created": now.isoformat(),
        "modified": now.isoformat(),
        "source": "internet_research",
        "confidence": confidence,
        "tags": tags or [],
        "related": [],
        "overview": overview,
        "specs": specs or {},
        "prices": prices or [],
        "pros": pros or [],
        "cons": cons or [],
        "sentiment": sentiment,
    }
