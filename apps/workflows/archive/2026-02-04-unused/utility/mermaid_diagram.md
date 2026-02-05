---
name: mermaid_diagram
version: "1.0"
category: utility
description: >
  Generate Mermaid diagrams from natural language descriptions.
  Supports flowcharts, sequence diagrams, class diagrams, and more.

triggers:
  - "create a diagram"
  - "generate a mermaid diagram"
  - "draw a flowchart"
  - "make a sequence diagram"
  - "visualize {concept}"

inputs:
  description:
    type: string
    required: true
    description: "Natural language description of what to diagram"

  diagram_type:
    type: string
    required: false
    default: "auto"
    description: "Diagram type: flowchart, sequenceDiagram, classDiagram, stateDiagram, erDiagram, gantt, pie, mindmap, or auto"

outputs:
  mermaid_code:
    type: string
    description: "Valid Mermaid.js syntax"

  diagram_type:
    type: string
    description: "The type of diagram generated"

steps:
  - name: generate_mermaid
    tool: llm.call
    args:
      prompt: |
        Generate a Mermaid diagram based on this description:

        Description: {{description}}
        Requested type: {{diagram_type}}

        If type is "auto", choose the most appropriate type:
        - flowchart: for processes, decisions, flows
        - sequenceDiagram: for interactions between entities over time
        - classDiagram: for class structures and relationships
        - stateDiagram: for state machines
        - erDiagram: for database entity relationships
        - gantt: for project timelines
        - pie: for proportional data
        - mindmap: for hierarchical concepts

        Return ONLY valid Mermaid.js syntax. No markdown code fences.
        Start directly with the diagram type (e.g., "flowchart TD" or "sequenceDiagram").

        Example flowchart:
        flowchart TD
            A[Start] --> B{Decision}
            B -->|Yes| C[Action 1]
            B -->|No| D[Action 2]
            C --> E[End]
            D --> E

        Example sequence:
        sequenceDiagram
            participant A as Client
            participant B as Server
            A->>B: Request
            B-->>A: Response
      role: mind
      max_tokens: 1500
    outputs:
      - mermaid_code

success_criteria:
  - "mermaid_code is not empty"
  - "mermaid_code starts with valid diagram type"

fallback:
  workflow: null
  message: "Unable to generate diagram. Please provide a clearer description of what you want to visualize."
---

## Mermaid Diagram Generator

Generate Mermaid.js diagrams from natural language descriptions.

### Supported Diagram Types

| Type | Best For | Example Trigger |
|------|----------|-----------------|
| flowchart | Processes, decisions, flows | "diagram the login process" |
| sequenceDiagram | Interactions over time | "show API request flow" |
| classDiagram | Class structures | "diagram the User class hierarchy" |
| stateDiagram | State machines | "show order states" |
| erDiagram | Database schemas | "diagram the database tables" |
| gantt | Project timelines | "create a project timeline" |
| pie | Proportions | "show budget breakdown" |
| mindmap | Hierarchical concepts | "mind map for project planning" |

### Example

**Input:**
```
description: "User login flow: user enters credentials, system validates,
              if valid show dashboard, if invalid show error and retry"
diagram_type: auto
```

**Output:**
```mermaid
flowchart TD
    A[User enters credentials] --> B{Validate}
    B -->|Valid| C[Show Dashboard]
    B -->|Invalid| D[Show Error]
    D --> A
```

### Usage Notes

- The generated code can be rendered in VS Code, Obsidian, GitHub, or any Mermaid-compatible viewer
- For complex diagrams, provide detailed descriptions with clear entity names
- Use specific diagram types when you know what you want; use "auto" to let the LLM choose
