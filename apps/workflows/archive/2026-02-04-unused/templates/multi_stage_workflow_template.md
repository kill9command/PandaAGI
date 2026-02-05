---
name: {{workflow_name}}
version: "1.0"
category: {{category}}
description: >
  Multi-stage workflow for {{purpose}}.

triggers:
  - "{{trigger_phrase_1}}"
  - "{{trigger_phrase_2}}"

inputs:
  {{input_name}}:
    type: string
    required: true
    description: "{{input_description}}"

outputs:
  {{output_name}}:
    type: object
    description: "{{output_description}}"

steps:
  - name: stage_1_{{name}}
    description: "{{Stage 1 goal}}"
    tool: {{tool_name}}
    args:
      {{arg}}: "{{value}}"
    outputs:
      - stage_1_result

  - name: stage_2_{{name}}
    description: "{{Stage 2 goal}}"
    condition: "{{stage_1_result.success}}"
    tool: {{tool_name}}
    args:
      input: "{{stage_1_result}}"
    outputs:
      - stage_2_result

  - name: stage_3_{{name}}
    description: "{{Stage 3 goal}}"
    condition: "{{stage_2_result.success}}"
    tool: {{tool_name}}
    args:
      input: "{{stage_2_result}}"
    outputs:
      - final_result

success_criteria:
  - "final_result is not empty"
  - "{{additional_criterion}}"

fallback:
  workflow: null
  message: "{{fallback_message}}"
---

## {{Workflow Title}}

Multi-stage workflow for {{purpose}}.

### Workflow Stages

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Stage 1   │───▶│   Stage 2   │───▶│   Stage 3   │───▶│   Complete  │
│  {{name}}   │    │  {{name}}   │    │  {{name}}   │    │             │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

### When to Use

Use this workflow when:
- {{use_case_1}}
- {{use_case_2}}

**Do NOT use when:**
- {{anti_pattern_1}}

### Stage 1: {{Name}}

**Goal:** {{what_this_stage_accomplishes}}

**Checkpoint:** Verify {{verification}} before proceeding.

### Stage 2: {{Name}}

**Goal:** {{what_this_stage_accomplishes}}

**Decision Point:**
| Condition | Action |
|-----------|--------|
| {{condition_1}} | Proceed to Stage 3 |
| {{condition_2}} | Return to Stage 1 |

### Stage 3: {{Name}}

**Goal:** {{what_this_stage_accomplishes}}

### Completion

**Success criteria:**
- {{success_criterion_1}}
- {{success_criterion_2}}

### Troubleshooting

**{{Problem}}:** {{resolution}}
