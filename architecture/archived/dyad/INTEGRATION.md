# Dyad Integration Notes

## Relevance to Pandora Code Mode

Dyad's patterns are directly applicable to enhancing Pandora's code mode capabilities.

---

## Key Patterns to Consider

### 1. XML-Based Tool Execution

Dyad uses XML tags instead of native function calling for code operations.

**Dyad approach:**
```xml
<dyad-write path="src/utils/helper.ts">
export function formatDate(date: Date): string {
  return date.toISOString().split('T')[0];
}
</dyad-write>
```

**Potential Pandora adaptation:**
```xml
<panda-write path="apps/services/gateway/utils/new_helper.py">
def format_date(dt: datetime) -> str:
    return dt.isoformat()[:10]
</panda-write>
```

**Benefits:**
- Cleaner code output (no JSON escaping issues)
- Works consistently across models
- Easy to parse and validate
- Natural for code-heavy responses

### 2. Mode Switching

Dyad has distinct modes (Build, Ask, Agent, Local-Agent) with different capabilities.

**Pandora already has:**
- Intent classification (informational, transactional, code, etc.)
- Phase-based processing

**Enhancement opportunity:**
- Explicit "code mode" that behaves more like Dyad's Build mode
- Distinct prompts and constraints per mode
- Mode-specific validation rules

### 3. Context Strategies

| Strategy | Dyad | Pandora Equivalent |
|----------|------|-------------------|
| Full context | Send entire codebase | Send full turn document |
| Smart filter | Pre-filter with small model | Phase 2 context gathering |
| Targeted | User specifies files | Tool-specific context |

**Consideration:** Dyad's "smart filter" pattern could improve Pandora's code mode efficiency - use a fast model to identify relevant files before the main code generation call.

---

## Integration Scenarios

### Scenario A: Dyad as Code Mode Backend

Pandora delegates code operations to Dyad:

```
User: "Add error handling to the API endpoint"
    ↓
Pandora Phase 0-3: Classify, gather context, plan
    ↓
Pandora Phase 4: Delegate to Dyad
    ├── Send: task description + relevant code context
    ├── Dyad: Generate XML-tagged code changes
    └── Return: Proposed changes
    ↓
Pandora Phase 5-6: Present and validate
```

**Pros:**
- Leverage Dyad's optimized code generation
- Consistent XML format for changes
- Multi-model flexibility

**Cons:**
- Additional integration complexity
- Two systems to maintain

### Scenario B: Adopt Dyad Patterns in Pandora

Incorporate Dyad's patterns directly into Pandora's code mode:

**1. XML Tags for Code Operations**
```python
# In coordinator or code synthesis phase
CODE_TAGS = {
    'panda-write': handle_file_write,
    'panda-delete': handle_file_delete,
    'panda-rename': handle_file_rename,
    'panda-command': handle_command,
}

def parse_code_response(response: str) -> list[CodeOperation]:
    """Parse XML tags from LLM response."""
    operations = []
    for tag, content, attrs in extract_xml_tags(response):
        if tag in CODE_TAGS:
            operations.append(CodeOperation(
                type=tag,
                path=attrs.get('path'),
                content=content,
            ))
    return operations
```

**2. Build Mode System Prompt**
Adapt Dyad's comprehensive system prompt for code generation:

```markdown
# Code Mode Instructions

You are helping modify a Python codebase. Follow these rules:

## Output Format
Use XML tags for all file operations:

- <panda-write path="...">content</panda-write> - Create or modify file
- <panda-delete path="..." /> - Delete file
- <panda-rename from="..." to="..." /> - Rename file

## Constraints
- Keep files under 200 lines when possible
- Follow existing code patterns in the codebase
- Do not overengineer - minimal changes to achieve the goal
- Include only necessary imports
```

### Scenario C: Research-to-Code Pipeline

Use Pandora's research capabilities to inform Dyad's code generation:

```
User: "Build a data visualization dashboard for sales data"
    ↓
Pandora Research (Phase 1):
  - Best practices for sales dashboards
  - Recommended chart types for sales metrics
  - Popular libraries (D3, Chart.js, Recharts)
  - UX patterns for dashboard layouts
    ↓
Pandora Synthesis: Research summary + recommendations
    ↓
Dyad Build Mode:
  - Receives: Research findings + user requirements
  - Generates: Complete dashboard implementation
  - Uses: Recommended libraries and patterns from research
    ↓
Output: Working dashboard informed by research
```

---

## Technical Integration Points

### If Using Dyad as External Service

```python
# Hypothetical integration
class DyadCodeService:
    """Delegate code operations to Dyad."""

    async def generate_code(
        self,
        task: str,
        context: dict,
        files: list[str],
    ) -> list[CodeOperation]:
        """
        Send code task to Dyad and parse response.

        Args:
            task: Description of code changes needed
            context: Relevant context (from Pandora phases)
            files: List of file paths to include

        Returns:
            List of CodeOperation objects (write, delete, rename)
        """
        # Build Dyad-compatible request
        prompt = self._build_prompt(task, context, files)

        # Call Dyad's LLM integration
        response = await self._call_dyad(prompt)

        # Parse XML tags from response
        return self._parse_operations(response)
```

### If Adopting Patterns Directly

```python
# XML tag parser for code operations
import re
from dataclasses import dataclass
from typing import Optional

@dataclass
class CodeOperation:
    type: str  # write, delete, rename
    path: str
    content: Optional[str] = None
    new_path: Optional[str] = None  # for rename

def parse_code_operations(response: str) -> list[CodeOperation]:
    """Extract code operations from XML-tagged response."""
    operations = []

    # Match <panda-write path="...">content</panda-write>
    write_pattern = r'<panda-write\s+path="([^"]+)">(.*?)</panda-write>'
    for match in re.finditer(write_pattern, response, re.DOTALL):
        operations.append(CodeOperation(
            type='write',
            path=match.group(1),
            content=match.group(2).strip(),
        ))

    # Match <panda-delete path="..." />
    delete_pattern = r'<panda-delete\s+path="([^"]+)"\s*/>'
    for match in re.finditer(delete_pattern, response):
        operations.append(CodeOperation(
            type='delete',
            path=match.group(1),
        ))

    # Match <panda-rename from="..." to="..." />
    rename_pattern = r'<panda-rename\s+from="([^"]+)"\s+to="([^"]+)"\s*/>'
    for match in re.finditer(rename_pattern, response):
        operations.append(CodeOperation(
            type='rename',
            path=match.group(1),
            new_path=match.group(2),
        ))

    return operations
```

---

## Comparison: Current Pandora Code Mode vs Dyad Patterns

| Aspect | Current Pandora | Dyad Pattern | Recommendation |
|--------|-----------------|--------------|----------------|
| Output format | Markdown code blocks | XML tags | Consider XML for structured operations |
| Context | Phase 2 gathering | Full codebase option | Add "full project" mode for refactoring |
| Validation | Phase 6 gate | None explicit | Keep Pandora's validation (strength) |
| Mode switching | Intent-based | Explicit modes | Consider explicit "code mode" toggle |
| Cost strategy | Quality-first | Token-efficient | Keep quality-first, but offer "fast mode" |

---

## Recommendations

### Short-term (Low Effort)

1. **Adopt XML tag pattern** for code operations in code mode
2. **Add explicit code mode toggle** in addition to intent detection
3. **Create code-specific system prompt** inspired by Dyad's 24KB prompt

### Medium-term (Moderate Effort)

1. **Smart context filtering** - Use fast model to identify relevant files
2. **Code operation preview** - Show proposed changes before applying
3. **Operation batching** - Group related file changes

### Long-term (Higher Effort)

1. **Research-to-code pipeline** - Pandora researches, then generates informed code
2. **Multi-model code generation** - Use specialized code models for generation
3. **Full Dyad integration** - Use Dyad as code backend service

---

## Key Takeaways

1. **XML tags are cleaner than JSON** for code-heavy responses
2. **Explicit modes** give users control over behavior
3. **Context strategies** matter for large codebases
4. **Pandora's validation is a strength** - don't lose it when adopting Dyad patterns
5. **Research + Code is powerful** - Pandora can inform code generation with research
