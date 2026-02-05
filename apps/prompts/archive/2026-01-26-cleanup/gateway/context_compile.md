# Context Gatherer - Compile Phase Prompt

## Purpose
Phase 4 of the 4-phase context gatherer. Compiles gathered information into the final context.md section 1.

## Prompt Template

CURRENT QUERY: {query}
TURN NUMBER: {turn_number}
{session_memory_section}{intel_section}
GATHERED INFORMATION:
{gathered_info}

Create the section 1 Gathered Context section. Output MARKDOWN only (no JSON wrapper).
If user preferences are present, include them in a "### User Preferences" subsection.
If cached intelligence is present, include it in a "### Cached Intelligence (Phase 1)" subsection.

## Expected Output Structure

```markdown
### Topic Classification
- **Topic:** Electronics.Laptops
- **Intent:** transactional

### Prior Turn Context
Summary of relevant prior turn information...

### User Preferences
(if present)

### Cached Intelligence (Phase 1)
(if present)
```

## Key Rules

1. **PRESERVE SPECIFICS:** Keep vendor names, prices, product names.

2. **COMPRESS VERBOSITY:** Remove redundant information.

3. **MAINTAIN STRUCTURE:** Follow the section format above.

4. **BE CONCISE:** Target ~500-800 words for the entire section.

5. **PRIOR TURN CONTEXT IS SUMMARY ONLY:** When describing what prior turns contained, do NOT imply the data is still available. Say things like "The user previously researched X" NOT "Prior research provides price details for X". The actual data availability is determined by Memory Status, not by what turns historically contained.
