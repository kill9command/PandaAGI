# Phase 4: Coordinator - User Prompt Template

## Task Plan from Phase 3

{task_plan}

## Tool Execution Results

{tool_results}

## Your Task

Analyze the tool execution results and extract key claims. For each result:

1. **Interpret the findings**: What did the tool actually return?
2. **Extract claims**: Pull out specific factual claims with confidence scores
3. **Note any failures**: If tools failed, document what went wrong
4. **Track goal progress**: For multi-goal queries, note which goals are addressed

### Claim Extraction Guidelines

- Include exact prices, URLs, and product names
- Assign confidence based on source reliability
- Set TTL based on claim type (prices: 6h, specs: 24h, general info: 48h)
- Format claims to be usable by synthesis phase

### Important

- ONLY extract facts that appear in the tool results
- Do NOT invent information not present in results
- Preserve original URLs for clickable links in response

Output your ToolExecutionResult JSON.
