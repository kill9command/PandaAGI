# Phase 2.2: Context Gatherer — Synthesis

Compile gathered information into §2 Gathered Context. Output is consumed by the Planner.

---

## Output Format

Output MARKDOWN only. No JSON wrapper, no code blocks around the whole output.

Start directly with the first relevant section header (`### Session Preferences`, etc.).

**Every section MUST have two parts:**

1. A `_meta` YAML block (provenance)
2. **Actual content** below it (the information the Planner needs)

```mermaid
flowchart LR
    A["### Section Title"] --> B["```yaml\n_meta:\n  source_type: ...\n  node_ids: [...]\n```"]
    B --> C["Actual content:\nbullet points, facts,\ndata from the loaded nodes"]
```

### Section Template

```markdown
### [Section Title]

` ``yaml
_meta:
  source_type: [turn_summary | preference | fact | research_cache | visit_record | user_query]
  node_ids: ["[node_id]"]
  confidence_avg: [0.0-1.0]
  provenance: ["[source_ref]"]
` ``

- [Actual content extracted from the loaded nodes]
- [Key facts, summaries, data points the Planner needs]
- [Specific details — names, URLs, topics, numbers]
```

**The content lines after `_meta` are NOT optional.** A section with only `_meta` and no content is useless to the Planner. If you have no content for a section, omit the section entirely.

---

## Canonical Sections

| Section | source_type | Content to include |
|---------|-------------|--------------------|
| `### Session Preferences` | `preference` | User preferences as key-value pairs |
| `### Relevant Prior Turns` | `turn_summary` | What was discussed, what was found, key entities |
| `### Cached Research` | `research_cache` | Research findings, claims, data points |
| `### Visit Data` | `visit_record` | What was found on visited pages, extracted content |
| `### Constraints` | `user_query` (node_ids: []) | Budget, requirements, filters from the query |

Omit empty sections entirely — do not include a header with no content.

---

## Rules

- Use only loaded memory nodes — do not fabricate node_ids or sources
- Exclude nodes with confidence < 0.30
- If confidence is missing, default to 0.50
- Preserve specifics: site names, thread titles, product names, URLs, numbers
- Compress verbosity but keep all facts the Planner would need

## Do NOT

- Output only `_meta` blocks without content — every section needs actual information
- Include sections where you have no loaded data
- Fabricate facts or node_ids not in the loaded nodes
- Wrap output in JSON or code blocks
