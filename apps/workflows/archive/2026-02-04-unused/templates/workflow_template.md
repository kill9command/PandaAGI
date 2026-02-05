---
name: {{workflow_name}}
version: "1.0"
category: {{category}}
description: >
  {{description}}

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
    type: string
    description: "{{output_description}}"

steps:
  - name: {{step_name}}
    tool: {{tool_name}}
    args:
      {{arg_name}}: "{{arg_value}}"
    outputs:
      - {{output_var}}

success_criteria:
  - "{{criterion_1}}"

fallback:
  workflow: null
  message: "{{fallback_message}}"
---

## {{Workflow Title}}

{{Brief description of what this workflow does.}}

### When to Use

Use this workflow when:
- {{use_case_1}}
- {{use_case_2}}

### Steps

1. **{{Step 1}}**: {{description}}
2. **{{Step 2}}**: {{description}}

### Example

**Input:**
```
{{example_input}}
```

**Output:**
```
{{example_output}}
```
