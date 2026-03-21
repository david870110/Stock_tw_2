# write-spec

Use this skill when a request needs an implementation-ready plan before coding.

## Goal

Produce a spec that is immediately consumable by Manager and Coder in this repository's JSON-contract workflow.

## Required Inputs

- task context from Manager,
- current constraints and acceptance goals,
- relevant repository context.

## Required Reference Loading

Before writing the result, load:

1. `docs/schemas/planner_response_schema.md`
2. `docs/schemas/manager_response_schema.md`
3. `prompts/templates/manager_to_planner.md`

If any file is missing, state that explicitly and continue with the closest valid structure.

## Workflow

1. Read the request and identify the desired outcome.
2. Inspect the relevant code paths, configs, prompts, or docs.
3. Create or update a markdown spec under `specs/`.
4. Structure the spec so it maps cleanly into planner JSON fields: `spec`, `sections`, `open_questions`, `ready_for_coder`.
5. Ensure acceptance criteria are checkable by QA without inventing hidden assumptions.
6. List open questions instead of guessing.

## Output Standard

The output must satisfy all:

- produces exactly one valid JSON object for Planner when used in role output mode,
- aligns section naming with planner conventions,
- is ready for Manager review and routing,
- keeps scope and non-goals explicit.

## Suggested Spec Structure

- Overview
- Scope
- Non-Goals
- Affected Files or Components
- Implementation Steps
- Acceptance Criteria
- Open Questions

## Do Not

- write production code as part of this skill,
- leave acceptance criteria vague,
- mark the work ready when important questions remain unresolved.
