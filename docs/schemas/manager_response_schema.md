# Manager Response Schema v0.1

## Required Fields

- `task_id`: string
- `task_title`: string
- `role`: string, allowed value: `"manager"`
- `status`: string, allowed values:
  - `"READY"`
  - `"NEEDS_REVISION"`
  - `"DONE"`
- `decision`: string, allowed values:
  - `"DECOMPOSE"`
  - `"SEND_TO_PLANNER"`
  - `"REVISE_PLANNER"`
  - `"SEND_TO_CODER"`
  - `"SEND_TO_QA"`
  - `"REROUTE_CODER"`
  - `"REROUTE_PLANNER"`
  - `"COMPLETE"`
- `instruction`: string
- `summary`: string
- `next_action`: string
- `success`: boolean

## Optional Fields

- `tasks`: object[]
  - Required per task item:
    - `task_id`: string
    - `title`: string
    - `description`: string
    - `priority`: string, allowed values: `"CRITICAL"`, `"HIGH"`, `"MEDIUM"`, `"LOW"`
    - `acceptance_criteria`: string[]

## Role Boundary

- Manager analyzes, routes, reviews, and decides next actions.
- Manager may decompose work into tasks, but `tasks` is only required during decomposition-style responses.
- Manager must not implement code.
- Manager must not perform QA validation directly.
- Manager may declare workflow completion only as a management decision, not as a workflow state emission.

## Example: Task Decomposition

```json
{
  "task_id": "T01",
  "task_title": "Create schema docs",
  "role": "manager",
  "status": "READY",
  "tasks": [
    {
      "task_id": "T01",
      "title": "Define response schemas",
      "description": "Write formal markdown schema docs for each role.",
      "priority": "HIGH",
      "acceptance_criteria": [
        "Each schema includes required and optional fields",
        "Each schema includes allowed values and one JSON example"
      ]
    }
  ],
  "decision": "SEND_TO_PLANNER",
  "instruction": "Produce implementation-ready schema specifications for all agent roles.",
  "summary": "Task decomposed and routed to Planner.",
  "next_action": "Wait for Planner spec.",
  "success": true
}
```

## Example: Runtime Routing
```json
{
  "task_id": "T01",
  "task_title": "Create schema docs",
  "role": "manager",
  "status": "READY",
  "decision": "SEND_TO_QA",
  "instruction": "Validate the implementation against the approved specification.",
  "summary": "Implementation review complete; ready for QA.",
  "next_action": "Wait for QA result.",
  "success": true
}
```