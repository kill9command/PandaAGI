---
name: create_workflow
version: "2.0"
category: meta
description: >
  Generates a workflow specification (including tool specs) from a goal.
  Outputs a JSON spec that the Executor can submit via CREATE_WORKFLOW.

triggers:
  - "create workflow"
  - "build workflow"
  - "design workflow"
  - "workflow for {goal}"

inputs:
  workflow_goal:
    type: string
    required: true
    description: "Goal statement for the workflow to be created"

  constraints:
    type: string
    required: false
    description: "Constraints or policies that must be honored"

  existing_context:
    type: string
    required: false
    from: section_2
    description: "Relevant context and prior decisions"

outputs:
  result:
    type: string
    description: "JSON string containing workflow_spec and tool_specs"

steps:
  - name: design_workflow_spec
    tool: llm.call
    args:
      prompt: |
        You are generating a workflow specification for a system that requires:
        - Tools only exist inside workflows.
        - Workflow creation MUST include tool_specs for every declared tool.
        - Use placeholders, not real-world examples.
        - Keep triggers abstract and pattern-based.

        Goal:
        {{workflow_goal}}

        Constraints:
        {{constraints}}

        Context:
        {{existing_context}}

        Output JSON ONLY with this structure:
        {
          "workflow_spec": {
            "name": "<snake_case>",
            "category": "<category>",
            "description": "<one_or_two_sentences>",
            "triggers": ["<abstract_trigger_pattern>", "<abstract_trigger_pattern>"],
            "tools": ["<tool_name>", "<tool_name>"],
            "inputs": {
              "<input_name>": {"type": "<type>", "required": true, "description": "<desc>"}
            },
            "outputs": {
              "<output_name>": {"type": "<type>", "description": "<desc>"}
            },
            "steps": [
              {"name": "<step_name>", "tool": "<tool_name>", "args": {"<arg>": "<value>"}, "outputs": ["<output>"]}
            ],
            "success_criteria": ["<criterion>"]
          },
          "tool_specs": [
            {"tool_name": "<tool_name>", "spec": "<tool_spec_markdown>", "code": "<python_code>", "tests": "<tests_or_empty>"}
          ]
        }

        Requirements:
        - The workflow_spec.tools list MUST be derivable from steps tool names.
        - Every tool in workflow_spec.tools MUST have a tool_specs entry.
        - Use placeholders like <entity>, <constraint>, <value> in triggers.
        - Do NOT include real-world examples.
        - Keep JSON compact and valid.
      role: mind
      max_tokens: 1800
    outputs:
      - result

success_criteria:
  - "result is not empty"

fallback:
  workflow: null
  message: "Unable to generate workflow specification. Provide a clearer goal and constraints."
---

## Create Workflow (Spec Generation)

This workflow generates a workflow specification and tool specs.

**Usage Pattern:**
1. Run this workflow to generate `workflow_spec` + `tool_specs`.
2. The Executor uses CREATE_WORKFLOW with the generated output.

**Note:** This workflow does not write files or register workflows directly.
