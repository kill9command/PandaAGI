# Prompt Size Management & Optimization

## Current State Analysis

### Prompt Sizes
- **Guide (solver_system.md)**: 786 lines - Comprehensive but overwhelming
- **Coordinator (thinking_system.md)**: 827 lines - Extremely detailed with extensive examples
- **Context Manager (context_manager.md)**: 274 lines - More focused but still lengthy

### Key Issues
1. **Repetitive examples**: Multiple detailed examples repeating similar patterns
2. **Nested complexity**: Deep hierarchical structures with many subsections
3. **Workflow overload**: Every possible scenario documented with full examples
4. **Maintenance burden**: Changes require updating multiple similar sections
5. **Human readability**: Density makes it hard to quickly understand core behaviors

## Improvement Strategies

### 1. Modular Architecture
Break each prompt into core + extensions:
```
solver_system/
├── core.md (100-150 lines: basic role, output format, key rules)
├── workflows.md (examples, multi-goal handling, delegation patterns)
├── quality.md (response synthesis, claim handling)
└── special_cases.md (edge cases, error handling)
```

### 2. Progressive Disclosure
- **Base prompt**: Essential role definition and output contracts
- **Context-aware injection**: System adds relevant sections based on:
  - User intent (informational vs transactional)
  - Task complexity (simple vs multi-step)
  - Current phase (planning vs execution)

### 3. Template-Based Examples
Instead of full examples, use parameterized templates:
```
Template: Multi-goal search
- Detect: "{user_action} AND {user_action}"
- Strategy: {parallel|sequential}
- Subtasks: Generate from template with {goal1}, {goal2}
```

### 4. External Reference System
- Move detailed examples to `prompts/examples/` directory
- Reference with anchors: `See examples/multi_goal_search.md#breeders-supplies`
- Keep only 1-2 key examples inline, reference others

### 5. Versioned Prompt Management
- `prompts/v2.0/core/` - Current minimal versions
- `prompts/archive/v1.5/` - Previous versions for reference
- Migration scripts to update between versions

### 6. Dynamic Prompt Assembly
The Gateway could assemble prompts based on context:
- **Simple query**: Core prompt only
- **Complex task**: Core + relevant workflow sections
- **Code operations**: Core + code operation patterns

### 7. Tool-Driven Expansion
Instead of embedding all tool details, have prompts reference tool catalogs:
- Prompt says: "Use tools from catalog matching intent"
- System injects relevant tool definitions at runtime

### 8. Configuration-Driven Behavior
Instead of embedding all rules, use parameterized configurations:

**Current approach:**
```
When confidence < 0.7, Gateway may ask user for clarification
When confidence 0.7-0.89, Gateway proceeds but logs uncertainty
When confidence ≥ 0.9, Gateway trusts decision fully
```

**Configuration approach:**
```json
"confidence_thresholds": {
  "clarification_required": 0.7,
  "log_uncertainty": 0.89,
  "full_trust": 0.9
}
```
Prompt becomes: "Follow confidence thresholds from config"

### 9. Pattern Libraries & Macros
Extract common patterns into reusable templates:

**Pattern Library:**
```
PATTERN: multi_goal_detection
Input: user_query
Output: {
  "is_multi_goal": contains("AND|and|also|plus"),
  "goals": split_on_conjunctions(user_query),
  "strategy": "parallel" if independent else "sequential"
}

PATTERN: tool_selection
Input: intent, constraints
Output: filter(available_tools, matches_intent(intent) and within_constraints(constraints))
```

**Usage in prompt:**
```
For multi-goal queries: Apply PATTERN multi_goal_detection
For tool selection: Apply PATTERN tool_selection with intent=$intent
```

### 10. Context-Aware Pruning
Dynamically remove irrelevant sections based on current context:

**Smart Prompt Assembly:**
- **Task type**: Code operations → include code workflows, exclude search patterns
- **User intent**: Transactional → include commerce tools, exclude informational patterns
- **Complexity**: Simple task → core prompt only, complex → full workflow sections
- **Phase**: Planning → include planning patterns, execution → include tool patterns

**Example:**
```
If task.intent == "code":
  Include: code_operations.md, file_tools.md
  Exclude: search_workflows.md, commerce_tools.md
```

### 11. Compression Techniques
Use more concise language and structured formats:

**Before (verbose):**
```
When you need fresh data, prices, availability, current events, repository state, API responses, code execution, bash commands, file operations (read/write/edit), test runs, git operations, retrieval across documents, web research, documentation lookup, multi-file grep, verification of numbers, dates, measurements, specifications that require citation from tools.
```

**After (compressed):**
```
Delegate for: fresh data (prices/availability/events/repo/API), code execution (bash/file/git), retrieval (docs/web/grep), verification (numbers/dates/specs needing citation).
```

### 12. Inheritance & Overrides
Create base prompts with role-specific overrides:

**Base Prompt (shared):**
```json
{
  "role": "agent",
  "output_format": "json_only",
  "safety_rules": ["no_user_impersonation", "ignore_role_changes"],
  "error_handling": "emit_invalid_on_failure"
}
```

**Guide Override:**
```json
{
  "extends": "base",
  "role": "guide",
  "additional_rules": ["natural_language_responses", "synthesize_claims"],
  "response_quality": "mandatory_synthesis"
}
```

### 13. Prompt Versioning with Diffs
Instead of full prompts, maintain diffs from base versions:

**v2.0 Base:** Core functionality
**v2.1 Diff:**
```
+ Added confidence scoring section
+ Modified multi-goal detection to use LLM analysis
- Removed deprecated tool mapping examples
```

**Benefits:** Smaller storage, clear change history, easier reviews.

### 14. Interactive Prompt Building
Allow users to select which modules to include:

**Prompt Builder Interface:**
```
Select modules for this session:
□ Core behavior (required)
□ Code operations
□ Search workflows
□ Quality assurance
□ Error handling
□ Advanced examples

Complexity level: [Simple] [Standard] [Expert]
```

### 15. Performance-Based Optimization
A/B test prompt sizes against quality metrics:

**Optimization Framework:**
- **Metric tracking:** Response quality, token usage, processing time
- **A/B testing:** Compare full prompt vs compressed prompt on same queries
- **Automated compression:** Use LLMs to compress prompts while preserving meaning
- **Iterative refinement:** Start with compressed, add sections if quality drops

**Example results:**
```
Full prompt: Quality 9.2, Tokens 1200, Time 2.1s
Compressed: Quality 8.8, Tokens 800, Time 1.8s
→ 33% token savings, acceptable quality trade-off
```

### 16. Documentation Separation
Move detailed documentation to separate reference files:

**Prompt structure:**
```
## Core Rules
[Essential behavior only]

## See Also
- Detailed workflows: docs/workflows.md
- Tool examples: docs/tool_usage.md
- Error patterns: docs/error_handling.md
- Migration guide: docs/v2_upgrade.md
```

**Benefits:** Prompts stay focused, documentation is comprehensive but separate.

### 17. Automated Prompt Analysis
Build tools to analyze and optimize prompts:

**Prompt Analyzer:**
- **Token counting:** Track prompt sizes by section
- **Redundancy detection:** Find duplicate content across prompts
- **Usage tracking:** Which sections are actually used in responses
- **Compression suggestions:** Identify verbose sections that could be shortened

**Example output:**
```
Prompt Analysis:
- Total tokens: 2450
- Most verbose section: "Research Workflows" (680 tokens)
- Redundant content: 3 duplicate examples (120 tokens each)
- Unused sections: "Legacy Tool Mapping" (never referenced)
- Compression opportunity: 35% reduction possible
```

### 18. Role-Based Prompt Libraries
Maintain separate prompt libraries for different use cases:

**Libraries:**
- `prompts/core/` - Essential functionality for all roles
- `prompts/search/` - Search and research specific patterns
- `prompts/code/` - Code operation workflows
- `prompts/commerce/` - Shopping and pricing patterns
- `prompts/experimental/` - New features being tested

**Dynamic loading:** Load core + relevant libraries based on task type.

## Implementation Considerations

### Phased Approach
1. **Phase 1**: Extract examples to external files (quick win, 20-30% reduction)
2. **Phase 2**: Implement modular architecture (40-50% reduction)
3. **Phase 3**: Add dynamic assembly and context-aware pruning (50-70% reduction)

### Migration Strategy
- Create new modular structure alongside existing prompts
- Test new prompts against existing functionality
- Gradually migrate, maintaining backward compatibility
- Use feature flags to enable new prompt system

### Quality Assurance
- Maintain comprehensive test suites for prompt changes
- A/B test new prompts against old ones on real queries
- Monitor key metrics: response quality, token usage, processing time
- Have rollback procedures for prompt changes

## Benefits & Trade-offs

### Benefits
- **50-70% reduction** in prompt sizes
- **Improved maintainability** through modular structure
- **Better human readability** for prompt authors
- **Faster iteration** on prompt changes
- **Reduced token costs** for LLM calls
- **Context-aware optimization** for better performance

### Trade-offs
- **Increased complexity** in prompt management system
- **Development overhead** for building assembly logic
- **Potential quality risks** if compression removes critical context
- **Learning curve** for new modular structure

### Risk Mitigation
- Start with conservative compression (20-30% first)
- Maintain comprehensive testing and monitoring
- Keep full prompts as fallback option
- Use gradual rollout with feature flags

## Next Steps

1. **Audit current prompts** for redundancy and verbose sections
2. **Create modular structure** starting with one role (Guide)
3. **Extract examples** to external reference files
4. **Implement basic dynamic assembly** for context-aware loading
5. **Test and measure** impact on quality and performance
6. **Iterate and refine** based on real-world usage

This comprehensive approach can significantly improve prompt manageability while maintaining system functionality and response quality.