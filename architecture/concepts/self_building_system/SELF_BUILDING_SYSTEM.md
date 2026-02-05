# Self-Building System

**Version:** 2.0
**Updated:** 2026-02-03

---

## 1. Overview

Panda must be able to **create and evolve its own tools and workflows**. Workflows are the container; tools live inside workflows. The system can:

- Create new workflows
- Create new tools (with code + schema)
- Edit or delete existing workflows/tools (with backups)

This is a **core architecture requirement**, not optional.

---

## 2. Bootstrap Tools

The system starts with a minimal fixed tool set:

| Tool | Purpose |
|------|---------|
| File I/O (read, write, glob, grep) | Required to create/edit workflows and tools |
| Sandboxed code execution | Used to validate tool implementations |
| Internet research | Available for tool design (optional) |
| Workflow registration | Dynamic workflow loading |

These are the only hard-coded tools. Everything else must be created by the system.

---

## 3. Workflow Bundles

Tools live inside workflows. Each workflow is stored as a **bundle** containing:

- **Workflow definition** — triggers, steps, output format, validation criteria
- **Tool specs + implementations** — one file per tool, with inputs/outputs/code
- **Tests** — optional, run in sandbox during validation

The workflow registry loads bundle definitions. The tool catalog registers tools found within bundles.

---

## 4. Self-Extension Actions

The Executor emits explicit self-build actions:

| Action | Purpose |
|--------|---------|
| **CREATE_TOOL_FAMILY_SPEC** | Define a tool family contract (required inputs, outputs, error behavior) before building tools |
| **CREATE_WORKFLOW** | Create a new workflow bundle with triggers, steps, and validation |
| **CREATE_TOOL** | Create a tool inside an existing workflow bundle (spec + code + tests) |
| **EDIT** | Modify an existing workflow or tool (backup created first) |
| **DELETE** | Remove a workflow or tool (backup created first) |

**Rule:** If a tool family spec is missing, the Executor MUST emit CREATE_TOOL_FAMILY_SPEC before CREATE_TOOL.

---

## 5. Validation Rules

All created assets must pass validation before being registered:

**Workflow validation:**
- Required sections: Triggers, Steps, Output, Validation
- All referenced tools must exist in the bundle or registry

**Tool validation:**
- Required sections: Inputs, Outputs, Constraints
- If code exists, run tests in sandbox

Failed validation rolls back to the last backup. No partial registrations.

---

## 6. Backup Policy

Before any edit or delete, the system creates a timestamped backup of the affected files. Rollback restores from the most recent backup.

---

## 7. Triggers for Self-Extension

Self-extension is triggered when:

- No existing workflow or tool matches the task
- A workflow fails repeatedly with the same missing capability
- User explicitly requests a new capability

---

## 8. Pipeline Integration

| Phase | Role in Self-Extension |
|-------|----------------------|
| 3 Planner | Decides if self-extension is required |
| 4 Executor | Emits CREATE_TOOL / CREATE_WORKFLOW actions |
| 5 Coordinator | Performs file writes, sandbox tests, and registration |
| 7 Validation | Ensures new tool/workflow produced valid outputs |

---

## 9. Prompt Integration

When new tools or workflows are created, the system must update prompt context dynamically:

- Tool lists included in Coordinator/Executor prompts must be refreshed
- Workflow triggers must be reflected in Planner guidance via the workflow registry

The system never relies on static prompt text for dynamically created tools.

---

## Related Documents

- `architecture/concepts/system_loops/EXECUTION_SYSTEM.md`
- `architecture/concepts/tools_workflows_system/TOOL_SYSTEM.md`
- `architecture/concepts/self_building_system/BACKTRACKING_POLICY.md`

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-03 | Initial specification |
| 2.0 | 2026-02-03 | Removed directory trees, YAML action schemas, backup paths, and component-specific filenames. Pure concept doc. |

---

**Last Updated:** 2026-02-03
