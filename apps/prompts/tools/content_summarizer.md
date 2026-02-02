# Content Summarizer

Summarize research source content while **STRICTLY** preserving structure.

## Context

RESEARCH QUERY: {query}

SOURCE URL: {url}
SOURCE TYPE: {page_type}

ORIGINAL CONTENT:
{content}

## Critical Summarization Rules

### 1. PRESERVE STRUCTURE

Your output MUST maintain these sections:
- Main summary paragraph (2-3 sentences)
- Key Points (bullet list)
- Any specific products/vendors mentioned
- Any prices mentioned

### 2. PRESERVE SPECIFICS

**NEVER** generalize these:
- Vendor/retailer names (Best Buy, Amazon, Newegg, etc.)
- Product names and model numbers
- Prices and price ranges
- Specifications (GPU, RAM, storage, etc.)
- Expert recommendations

### 3. COMPRESS VERBOSITY

Remove:
- Repetitive information
- Off-topic tangents
- Excessive context/background
- Navigation/UI text artifacts

### 4. TARGET LENGTH

~{target_content_tokens} tokens (~{target_chars} characters)

## Output Format

Provide a structured summary with:

**Summary:** [2-3 sentence overview]

**Key Points:**
- [Specific finding with numbers/names]
- [Another specific finding]

**Vendors Mentioned:** [List any retailers/vendors]

**Products/Prices:** [List any specific products with prices]

**Expert Recommendations:** [Any specific recommendations]

## Output

BEGIN SUMMARY:
