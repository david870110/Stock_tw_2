# Orchestrator Response Schema v0.1

## Required Fields

- `run_id`: string
- `task_id`: string
- `task_title`: string
- `role`: string, allowed value: `"orchestrator"`
- `current_state`: string, allowed values:
  - `"NEW"`
  - `"MANAGER_PLANNING"`
  - `"WAIT_PLANNER"`
  - `"PLANNER_DONE"`
  - `"MANAGER_SPEC_REVIEW"`
  - `"WAIT_CODER"`
  - `"CODER_DONE"`
  - `"WAIT_QA"`
  - `"QA_DONE"`
  - `"DONE"`
  - `"BLOCKED"`
- `last_role_called`: string, allowed values:
  - `"Manager"`
  - `"Planner"`
  - `"Coder"`
  - `"QA"`
  - `"Orchestrator"`
- `last_result`: string
- `decision`: string, allowed values:
  - `"ROUTE_TO_PLANNER"`
  - `"ROUTE_TO_CODER"`
  - `"ROUTE_TO_QA"`
  - `"COMPLETE"`
  - `"BLOCK_TASK"`
- `next_action`: string
- `iteration_count`: integer
- `success`: boolean
- `summary`: string

## Optional Fields

- `files_delivered`: string[]
- `notes`: string

## Role Boundary

- Only Orchestrator can emit workflow completion state (`current_state: "DONE"` or `"BLOCKED"`) at the workflow level.
- Orchestrator applies workflow transitions and terminal states based on Manager decisions and QA results.
- Coder completion is not workflow completion.
- QA `PASS` is not workflow completion until Manager confirms closure and Orchestrator emits the terminal state.

## Example

```json
{
  "run_id": "run_001",
  "task_id": "T01",
  "task_title": "Create schema docs",
  "role": "orchestrator",
  "current_state": "DONE",
  "last_role_called": "Manager",
  "last_result": "QA returned PASS and Manager confirmed completion.",
  "decision": "COMPLETE",
  "next_action": "Finalize run summary and persist logs.",
  "iteration_count": 1,
  "success": true,
  "summary": "Workflow completed successfully.",
  "files_delivered": [
    "docs/schemas/schema_version.md",
    "docs/schemas/manager_response_schema.md",
    "docs/schemas/planner_response_schema.md",
    "docs/schemas/coder_response_schema.md",
    "docs/schemas/qa_response_schema.md",
    "docs/schemas/orchestrator_response_schema.md"
  ],
  "notes": "Schema Freeze v0.1 delivered."
}
```