# Content Extractor

Extract useful information from this page.

## Goal
{original_query}

## Intent
{informational | commerce}

## Page URL
{url}

## Page Content
{sanitized_page_text}

## What to Extract

### For Informational Queries:
- key_facts: Important information relevant to the goal
- recommendations: Any advice or suggestions
- sources_cited: If the page references other sources
- linked_items: If the page lists items that link to other pages (threads, articles, products), include them as `[title](url)` markdown format so we can follow up

### For Commerce Queries:
- recommended_products: Products mentioned positively
- price_expectations: Price ranges mentioned
- specs_to_look_for: Features users recommend
- warnings: Things to avoid, common issues
- vendors_mentioned: Where users suggest buying

### Always Include:
- relevance: 0.0-1.0 how relevant was this page
- confidence: 0.0-1.0 how confident in the extracted info
- summary: 1-2 sentence summary of what was useful

**IMPORTANT:** If the page content contains links in markdown format `[text](url)`, preserve them!
The URLs enable follow-up queries to navigate directly to specific items.

Output as JSON.
