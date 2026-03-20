# Planner Response Schema v0.1

## Required Fields

- `task_id`: string
- `task_title`: string
- `role`: string, allowed value: `"planner"`
- `status`: string, allowed values:
  - `"READY"`
  - `"NEEDS_CLARIFICATION"`
- `spec`: string (full markdown specification text)
- `sections`: string[]
- `open_questions`: string[]
- `ready_for_coder`: boolean
- `summary`: string
- `next_action`: string
- `success`: boolean

## Optional Fields

- None in v0.1.

## Role Boundary

- Planner produces implementation-ready specifications only.
- Planner must not implement code.
- Planner must not perform QA.
- Planner must not declare workflow completion.

## Example

```json
{
  "task_id": "T01",
  "task_title": "Create schema docs",
  "role": "planner",
  "status": "READY",
  "spec": "## Overview\nDefine frozen response schema contracts for all workflow agents.",
  "sections": [
    "Overview",
    "Field Definitions",
    "Allowed Values",
    "Examples",
    "Acceptance Criteria"
  ],
  "open_questions": [],
  "ready_for_coder": true,
  "summary": "Specification is implementation-ready.",
  "next_action": "Send spec to Manager for review.",
  "success": true
}
```