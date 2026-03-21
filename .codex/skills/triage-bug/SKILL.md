# triage-bug

Use this skill when a bug report needs structured investigation before planning or coding.

## Goal

Turn an incoming bug report into routing-ready input for Manager, with enough detail to generate Planner or Coder instructions.

## Required Reference Loading

Before finalizing triage output, load:

1. `docs/schemas/manager_response_schema.md`
2. `prompts/templates/manager_to_planner.md`
3. `prompts/templates/manager_to_coder.md`

If template or schema files are missing, state the gap and continue with the closest structured fallback.

## Workflow

1. Capture the reported behavior, expected behavior, and impact.
2. Identify the likely subsystem, files, or prompts involved.
3. Check whether the issue is reproducible from available evidence.
4. Separate confirmed facts from hypotheses.
5. Propose the next routing step for Manager:
   `SEND_TO_PLANNER`, `SEND_TO_CODER`, or `NEEDS_REVISION`.
6. Prepare instruction-ready details that map to the matching manager template.

## Deliverable

Provide a structured triage note with:

- bug summary,
- severity and impact,
- reproduction status,
- suspected files or subsystem,
- missing information,
- recommended manager decision,
- draft instruction payload fields.

## Do Not

- start broad refactors,
- claim root cause without evidence,
- skip documenting uncertainty.
