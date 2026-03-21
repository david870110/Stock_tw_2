# run-qa-gate

Use this skill when implementation is ready for validation.

## Goal

Return a QA verdict (`PASS|FAIL|SPEC_GAP`) that is schema-compliant and routable by Manager or Orchestrator.

## Required Reference Loading

Before validating, load:

1. `docs/schemas/qa_response_schema.md`
2. `docs/schemas/coder_response_schema.md`
3. `prompts/templates/manager_to_qa.md`

If any file is missing, report it and continue with the closest valid schema-compatible output.

## Workflow

1. Read the approved spec.
2. Review the changed files.
3. Review updated or added tests.
4. Validate acceptance coverage from static evidence first.
5. Run lightweight validation such as `pytest` and lint only when practical or explicitly required.
6. Return `PASS`, `FAIL`, or `SPEC_GAP` with concrete findings and failed criteria when applicable.

## Validation Priority

1. Approved spec coverage
2. Changed file inspection
3. Contract and interface consistency
4. Test presence and test intent
5. Runtime execution evidence if required

## Minimum Report

Always include:

- `status` (`PASS|FAIL|SPEC_GAP`),
- findings,
- `failed_criteria`,
- `required_fixes`,
- summary and next action.

When used as role output, return exactly one valid JSON object.

## Do Not

- expand the feature scope,
- rewrite requirements,
- hide uncertainty behind a pass result,
- block forever on environment setup.
