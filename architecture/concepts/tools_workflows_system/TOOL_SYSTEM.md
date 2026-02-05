# Tool System

**Version:** 3.0
**Updated:** 2026-02-03

---

## 1. Overview

The Tool System defines how tools are **named, specified, created, validated, registered, and executed**. It is the foundation for tool breadth and self-extension.

Key principles:
- **Spec-first** — Family specs exist before tools are created
- **Normalized contracts** — All tools return the same result structure
- **Sandboxed execution** — Self-built tools run in a restricted environment
- **Bundle packaging** — Tools live inside workflow bundles

---

## 2. Tool Families

Tools are organized into **families** — groups of related tools that share a domain and contract. These families must exist architecturally, even if implementations are created on-demand:

| Family | Purpose |
|--------|---------|
| `file` | File I/O (read, write, search) |
| `spreadsheet` | XLSX / CSV operations |
| `document` | DOCX operations |
| `pdf` | PDF extraction |
| `email` | Email read, send, search |
| `calendar` | Calendar query, create, update |
| `code_sandbox` | Safe code execution |

Each family has a **family spec** that defines the required tools, their inputs/outputs, error behavior, and constraints. Individual tool signatures live in the family spec, not here.

---

## 3. Family Specs

### 3.1 Spec-First Rule

A family spec is a **contract**. It must exist before or alongside the first tool that uses it.

If a tool is needed in a family that does not yet exist, the system must:
1. Create the family spec
2. Create the tool(s)
3. Create or update the workflow that uses them

A family spec defines:
- Required tools (minimum set for the family)
- Input/output schemas and required fields
- Error behavior
- Constraints (limits, privacy, allowed operations)

### 3.2 How the System Learns New Families

When a new capability is required and no family spec exists:

1. **Planner detects missing family** — emits CREATE_TOOL_FAMILY_SPEC
2. **Executor drafts the family spec** — includes required tools, schemas, constraints
3. **Coordinator validates and writes** — registers the family in the Tool Catalog
4. **Follow-on tool creation** — tools and workflows are created against that family contract

---

## 4. Tool Registry

The Tool Catalog is the **single source of truth** for available tools.

Key behaviors:
- Register tools by name to handler
- Enforce mode restrictions (chat vs code)
- Validate tool existence for workflows
- Tools can be global (registered once) or bundled with workflows
- Bundled tools are registered at workflow load time
- Tool lists are injected into prompts dynamically per phase

---

## 5. Execution Contract

All tools return a **normalized structure** with a success/error status, the result payload, and an error message if applicable.

All tools must:
- Return an error status for missing required fields
- Include a human-readable error message
- Never throw unhandled exceptions to the LLM layer

---

## 6. Tool Creation Pipeline

When the system creates a new tool (via self-extension):

1. **Family spec check** — If the tool's family spec does not exist, create it first
2. **Spec generation** — Create tool spec with inputs/outputs/constraints conforming to the family spec
3. **Implementation** — Write code and tests
4. **Validation** — Schema validation (required fields present) + test execution in sandbox
5. **Registration** — Tool registered into Tool Catalog
6. **Persistence** — Files written to workflow bundle

On validation failure: **rollback to last backup**. No partial registrations. See SELF_BUILDING_SYSTEM.md for bundle structure and backup policy.

---

## 7. Sandbox Policy

Self-built tools execute in a restricted sandbox:

| Constraint | Rule |
|------------|------|
| **Filesystem** | Only workspace paths are accessible |
| **Network** | Disabled by default unless explicitly approved |
| **Timeouts** | Max execution time per tool call |
| **Memory** | Hard cap on RAM usage |
| **Dependencies** | Install only from an approved allowlist |

### Failure Modes

Tools must report structured failures:
- `timeout` — execution exceeded time limit
- `permission_denied` — attempted disallowed operation
- `dependency_missing` — required package not available
- `sandbox_violation` — breached sandbox boundary

Any package outside the allowlist requires explicit approval before installation.

---

## 8. Related Documents

- `architecture/concepts/system_loops/EXECUTION_SYSTEM.md` — 3-tier loop and workflow system
- `architecture/concepts/self_building_system/SELF_BUILDING_SYSTEM.md` — Tool + workflow self-extension, bundle structure, backup policy
- `architecture/main-system-patterns/phase5-coordinator.md` — Coordinator specification

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-03 | Initial (separate docs) |
| 2.0 | 2026-02-03 | Merged TOOLING_LAYER + TOOL_FAMILY_SPECS + TOOL_CREATION_PIPELINE + SANDBOX_POLICY |
| 3.0 | 2026-02-03 | Distilled to pure concept. Removed individual tool signatures (belong in family specs), directory trees, YAML/JSON schemas, package allowlist, and content duplicated in SELF_BUILDING_SYSTEM.md. |

---

**Last Updated:** 2026-02-03
