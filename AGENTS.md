# Repo Agent Rules

This repository uses a role-based multi-agent workflow. Every agent must follow the same delivery path and respect role boundaries.

## Team Roles

- Orchestrator owns workflow state transitions, routing order, and run-level completion control.
- Manager owns intake, routing, approval, and final completion decisions.
- Planner translates requests into implementation-ready specs.
- Coder implements only approved specs and keeps changes scoped.
- QA validates the implementation against the approved spec and reports pass/fail clearly.

## Required Workflow

1. Manager reads the user request and decides whether the work needs decomposition.
2. Planner writes or updates a spec in `specs/` before feature implementation begins.
3. Manager reviews the spec and explicitly approves it before coding starts.
4. Coder implements only the approved spec and updates tests with the code.
5. QA validates code, tests, and regression risk before the task is considered complete.
6. Manager reviews Planner, Coder, and QA outputs before declaring the task done.

## Guardrails

- No feature work begins without a spec, unless the task is a trivial non-behavioral edit.
- Any scope change discovered during implementation must route back to Planner.
- Coder must not invent requirements that are missing from the spec.
- QA must not expand scope or redesign the feature.
- Manager must not skip QA for behavior-changing work.
- A failed QA result blocks completion until the required fixes are addressed.

## File Ownership

- `specs/` stores planner-authored implementation specs.
- `prompts/` stores the existing role prompts used by the project runtime.
- `.codex/agents/` stores human-readable role guidance for Codex-based workflows.
- `.codex/skills/` stores reusable workflow skills.
- `artifacts/` may store generated handoff notes, logs, or summaries.

## Completion Standard

A task is complete only when all of the following are true:

- an approved spec exists when required,
- the code matches the spec,
- relevant tests are added or updated,
- QA has returned a final result,
- Manager has reviewed the evidence and closed the task.

## Suggested Routing

- Use Orchestrator when you need strict stateful execution across multiple role handoffs.
- Use Manager for triage, sequencing, and final decisions.
- Use Planner when requirements need structure, acceptance criteria, or implementation steps.
- Use Coder when an approved spec exists and code changes are needed.
- Use QA when implementation is ready for validation or regression review.

## Skills

Prefer reusable skills for repeated workflows. This repository currently includes:

- `write-spec`
- `run-qa-gate`
- `triage-bug`

## Skill Trigger Matrix

Use this matrix to keep skill selection consistent across Manager and Orchestrator routing.

1. New feature request without implementation-ready detail
- Trigger: `write-spec`
- Owner: Planner
- Required references: `docs/schemas/planner_response_schema.md`, `prompts/templates/manager_to_planner.md`
- Expected result: spec in `specs/` plus planner-contract JSON output

2. Behavior-changing implementation ready for validation
- Trigger: `run-qa-gate`
- Owner: QA
- Required references: `docs/schemas/qa_response_schema.md`, `prompts/templates/manager_to_qa.md`
- Expected result: `PASS|FAIL|SPEC_GAP` with failed criteria and required fixes when applicable

3. Incoming bug report with unclear scope or root cause
- Trigger: `triage-bug`
- Owner: Manager first, then Planner or Coder by routing decision
- Required references: `docs/schemas/manager_response_schema.md`, `prompts/templates/manager_to_planner.md`, `prompts/templates/manager_to_coder.md`
- Expected result: structured triage note and instruction-ready routing payload

4. QA returns `SPEC_GAP`
- Trigger order: `write-spec` then `run-qa-gate`
- Owner: Planner then QA
- Expected result: clarified spec, re-implementation if required, then fresh QA verdict

5. QA returns `FAIL`
- Trigger order: Manager reroute to Coder, then `run-qa-gate`
- Owner: Coder then QA
- Expected result: fix implementation, re-validate, and return final QA verdict

## Skill Execution Rules

- Do not skip `write-spec` when work changes behavior and no approved spec exists.
- Do not skip `run-qa-gate` for behavior-changing tasks.
- Use `triage-bug` before implementation when bug evidence is incomplete or conflicting.
- If a required schema or template file is missing, report the gap explicitly and continue with the closest valid structure.
