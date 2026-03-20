# QA Response Schema v0.1

## Required Fields

- `task_id`: string
- `task_title`: string
- `role`: string, allowed value: `"qa"`
- `status`: string, allowed values:
  - `"PASS"`
  - `"FAIL"`
  - `"SPEC_GAP"`
- `findings`: string[]
- `failed_criteria`: string[]
- `required_fixes`: string[]
- `summary`: string
- `next_action`: string
- `success`: boolean

## Optional Fields

- None in v0.1.

## Role Boundary

- QA must return only `PASS`, `FAIL`, or `SPEC_GAP` in `status`.
- QA validates against approved spec and implementation evidence.
- QA must not declare workflow completion.
- QA must not act as Manager, Coder, or Orchestrator.

## Example

```json
{
  "task_id": "T01",
  "task_title": "Create schema docs",
  "role": "qa",
  "status": "PASS",
  "findings": [
    "All required schema files are present",
    "Each file defines required fields, optional fields, allowed values, and one JSON example"
  ],
  "failed_criteria": [],
  "required_fixes": [],
  "summary": "Implementation satisfies the approved specification.",
  "next_action": "Return result to Manager.",
  "success": true
}```