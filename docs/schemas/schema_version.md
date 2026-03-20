# Schema Version v0.1

This document freezes the response schemas used by the multi-agent workflow.

## Version Metadata

- `schema_version`: required, string, allowed value: `"v0.1"`
- `release_date`: required, string, ISO date format (`YYYY-MM-DD`)
- `status`: required, string, allowed value: `"FROZEN"`
- `workflow_roles`: required, string[], allowed values per item:
  - `"Manager"`
  - `"Planner"`
  - `"Coder"`
  - `"QA"`
  - `"Orchestrator"`
- `completion_authority`: required, string, allowed value: `"Orchestrator"`
- `notes`: optional, string

## Role Boundary Guarantees

- `Coder` must report implementation status only (`DONE`, `PARTIAL`, `BLOCKED`) and must not declare workflow completion.
- `QA` must return only `PASS`, `FAIL`, or `SPEC_GAP`.
- Only `Orchestrator` may emit workflow completion state (`DONE`/`BLOCKED`) at workflow level.

## Common Response Pattern

All role responses should remain structurally consistent where applicable.

Shared fields across role schemas:
- `task_id`
- `task_title`
- `role`
- `summary`
- `next_action`
- `success`

## Example

```json
{
  "schema_version": "v0.1",
  "release_date": "2026-03-11",
  "status": "FROZEN",
  "workflow_roles": [
    "Manager",
    "Planner",
    "Coder",
    "QA",
    "Orchestrator"
  ],
  "completion_authority": "Orchestrator",
  "notes": "Schema Freeze v0.1 baseline for multi-agent workflow."
}