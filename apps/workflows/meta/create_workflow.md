---
name: create_workflow
version: "1.0"
category: meta
description: >
  Meta-workflow for creating new workflows from natural language descriptions.
  Analyzes what the user wants, designs the workflow structure, validates
  that it doesn't require bootstrap tools, and writes it to disk.

triggers:
  - "create a workflow for {task}"
  - "make a workflow that {does}"
  - "add a new workflow to {does}"

inputs:
  task_description:
    type: string
    required: true
    description: "Natural language description of what the workflow should do"

  name:
    type: string
    required: false
    description: "Workflow name (snake_case, auto-generated if not provided)"

  category:
    type: string
    required: false
    default: "utility"
    description: "Workflow category (research, memory, file, utility, meta)"

outputs:
  workflow_path:
    type: string
    description: "Path to the created workflow file"

  workflow_name:
    type: string
    description: "Name of the created workflow"

  registered:
    type: boolean
    description: "Whether the workflow was registered successfully"

  can_create:
    type: boolean
    description: "Whether the workflow could be created (no bootstrap dependencies)"

  reason:
    type: string
    description: "Reason if workflow could not be created"

steps:
  - name: analyze_task
    tool: internal://llm.call
    args:
      prompt: |
        Analyze this task and design a workflow:

        Task: {{task_description}}

        Output a JSON object with:
        - name: workflow name in snake_case (e.g., "fetch_weather")
        - category: one of [research, memory, file, utility]
        - description: 1-2 sentence description
        - triggers: list of trigger patterns (strings like "get weather for {city}")
        - required_tools: list of tool URIs needed (e.g., "internal://web.fetch")
        - steps: array of step objects with {name, tool, args, outputs}

        Available tools:
        - internal://internet_research.execute_research - Web research
        - internal://internet_research.execute_full_research - Commerce research
        - internal://memory.save - Save to memory
        - internal://memory.search - Search memory
        - internal://llm.call - Direct LLM call
        - bootstrap://file_io.read - Read file (BOOTSTRAP - cannot use)
        - bootstrap://file_io.write - Write file (BOOTSTRAP - cannot use)
        - bootstrap://code_execution.run - Run code (BOOTSTRAP - cannot use)

        Do NOT use bootstrap tools - they cannot be self-created.

        JSON only, no markdown:
      role: mind
      max_tokens: 1500
    outputs:
      - workflow_spec

  - name: validate_tools
    tool: internal://workflow_registry.validate_tools
    args:
      tools: "{{workflow_spec.required_tools}}"
    outputs:
      - valid_tools
      - bootstrap_tools

  - name: check_bootstrap
    tool: internal://workflow_registry.check_bootstrap
    args:
      tools: "{{bootstrap_tools}}"
    outputs:
      - can_create
      - reason

  - name: generate_workflow_markdown
    condition: "{{can_create}}"
    tool: internal://llm.call
    args:
      prompt: |
        Generate a complete workflow markdown file for this specification:

        {{workflow_spec}}

        Follow this exact format:

        ---
        name: {{workflow_spec.name}}
        version: "1.0"
        category: {{workflow_spec.category}}
        description: >
          {{workflow_spec.description}}

        triggers:
          - [list triggers here]

        inputs:
          [define inputs with type, required, description]

        outputs:
          [define outputs with type, description]

        steps:
          [define steps with name, tool, args, outputs]

        success_criteria:
          - [at least one criterion]

        fallback:
          workflow: null
          message: "Workflow failed."
        ---

        ## [Workflow Name]

        [Documentation paragraph]

        Output ONLY the markdown content, starting with ---
      role: mind
      max_tokens: 2000
    outputs:
      - workflow_content

  - name: write_workflow_file
    condition: "{{can_create}}"
    tool: bootstrap://file_io.write
    args:
      path: "apps/workflows/{{workflow_spec.category}}/{{workflow_spec.name}}.md"
      content: "{{workflow_content}}"
    outputs:
      - workflow_path

  - name: register_workflow
    condition: "{{can_create}}"
    tool: internal://workflow_registry.register
    args:
      path: "{{workflow_path}}"
    outputs:
      - registered
      - workflow_name

success_criteria:
  - "can_create == true"
  - "workflow_path exists"
  - "registered == true"

fallback:
  workflow: null
  message: >
    Cannot create this workflow. Reason: {{reason}}
    The workflow requires bootstrap tools which cannot be self-created.
    Bootstrap tools (file_io, code_execution) must be manually created.
---

## Create Workflow Meta-Workflow

This is a self-extension workflow that allows Pandora to create new workflows
from natural language descriptions.

### How It Works

1. **Analyze Task**: LLM analyzes the task description and designs a workflow
   structure including name, triggers, inputs, outputs, and steps.

2. **Validate Tools**: Check which tools the workflow needs and identify any
   bootstrap tool dependencies.

3. **Check Bootstrap**: Verify the workflow doesn't require bootstrap tools.
   Bootstrap tools (file_io, code_execution) cannot be self-created because
   the workflow system needs them to exist.

4. **Generate Markdown**: LLM generates the complete workflow markdown file
   following the standard format.

5. **Write File**: Write the workflow to the appropriate category directory.

6. **Register**: Register the new workflow with the WorkflowRegistry.

### Bootstrap Tools

These tools CANNOT be self-created:

- `bootstrap://file_io.read` - Read files from disk
- `bootstrap://file_io.write` - Write files to disk
- `bootstrap://code_execution.run` - Execute code in sandbox

The workflow system needs these primitives to exist before it can create
new workflows. They must be manually implemented.

### Example

Input:
```
task_description: "Create a workflow that fetches weather data for a city"
```

The meta-workflow will:
1. Design a workflow with triggers like "get weather for {city}"
2. Determine it needs web fetch capability
3. Generate the workflow markdown
4. Save to `apps/workflows/utility/fetch_weather.md`
5. Register it for immediate use

### Limitations

- Cannot create workflows that need to read/write files
- Cannot create workflows that need code execution
- Can only use existing non-bootstrap tools
- New workflows are limited to research, memory, and LLM operations
