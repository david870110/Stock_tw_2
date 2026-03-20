# Coder Response Schema v0.1

## Required Fields

- `task_id`: string
- `task_title`: string
- `role`: string, allowed value: `"coder"`
- `status`: string, allowed values:
  - `"DONE"`
  - `"PARTIAL"`
  - `"BLOCKED"`
- `implementation_log`: string
- `files_modified`: string[]
- `tests_added_or_updated`: string[]
- `blockers`: string[]
- `known_issues`: string[]
- `summary`: string
- `next_action`: string
- `success`: boolean

## Optional Fields

- `test_execution_summary`: string

## Role Boundary

- Coder reports implementation status only.
- Coder must not declare workflow completion.
- Coder must not emit `PASS`, `FAIL`, or `SPEC_GAP` as final task judgment.
- Coder must not emit orchestration terminal states.

## Example

```json
{
  "task_id": "T01",
  "task_title": "Create schema docs",
  "role": "coder",
  "status": "DONE",
  "implementation_log": "Created formal schema markdown files for all role responses.",
  "files_modified": [
    "docs/schemas/schema_version.md",
    "docs/schemas/coder_response_schema.md"
  ],
  "tests_added_or_updated": [],
  "test_execution_summary": "",
  "blockers": [],
  "known_issues": [],
  "summary": "Implementation complete and ready for QA validation.",
  "next_action": "Send implementation to Manager for QA routing.",
  "success": true
}
```