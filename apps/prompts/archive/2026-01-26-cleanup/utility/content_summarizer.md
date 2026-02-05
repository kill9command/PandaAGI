# Content Summarizer

Summarize this research source while preserving key facts, specifics, and page metadata.

**Query:** {query}
**URL:** {url}
**Page Type:** {page_type}

---

## Content to Summarize

{content}

---

## Rules

### 1. PRESERVE SPECIFICS - Never generalize these:
- Names: vendors, retailers, brands, authors, usernames
- Products: model numbers, SKUs, exact product names
- Numbers: prices, specs, counts, measurements, ratings
- Dates: publication dates, timestamps, "posted X ago"
- Recommendations: specific advice from experts or users

### 2. PRESERVE PAGE METADATA - Capture structural info visible on the page:
- Pagination: "Page X of Y", total pages, current page
- Counts: replies, comments, views, posts, answers, ratings, reviews
- Dates: published, updated, last activity
- Author: name, role, contribution count
- Status: solved, answered, closed, pinned, featured, verified
- Length: word count, read time, number of posts/sections

### 3. REMOVE - Compress these out:
- Repetitive or redundant information
- Off-topic tangents and filler
- Navigation menus (Home, About, Contact, etc.)
- Cookie banners, login prompts, ads, footers
- Generic boilerplate text

### 4. TARGET LENGTH: ~{target_content_tokens} tokens

---

## Output Format

**Summary:** [2-3 sentence overview of what this page contains]

**Key Points:**
- [Specific finding - include names, numbers, dates]
- [Another finding - be specific, not generic]

**Vendors/Sources:** [Named vendors, retailers, or authoritative sources mentioned - or "None"]

**Products/Prices:** [Specific products with prices if any - or "None"]

**Recommendations:** [Specific advice or recommendations from the content - or "None"]

**Page Metadata:** [Page count, reply count, view count, dates, author, status - whatever is visible on the page - or "None visible"]

---

BEGIN SUMMARY:
