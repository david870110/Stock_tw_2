# Skills Guide

This directory contains reusable workflow skills aligned with `.github/agents`, `prompts/templates`, and `docs/schemas`.

## Available Skills

- `write-spec`: Use when a task needs Planner-ready specification output.
- `run-qa-gate`: Use when implementation is ready for QA validation and verdict.
- `triage-bug`: Use when a bug report needs structured routing input for Manager.

## Alignment Rules

1. Load role schemas in `docs/schemas/` before producing role-contract output.
2. Load matching manager templates in `prompts/templates/` before drafting routed instructions.
3. If a referenced schema or template is missing, report the gap explicitly and continue with the closest valid structure.
4. Keep role boundaries strict: Planner plans, Coder implements, QA validates, Manager decides, Orchestrator controls workflow state.
