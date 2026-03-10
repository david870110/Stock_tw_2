"""
Vibe Coding Agent Orchestrator
QA Agent – tests the implementation against the approved spec.
"""
from __future__ import annotations

from orchestrator.agents.base_agent import BaseAgent
from orchestrator.models import PipelineContext, QAVerdict
from orchestrator.utils import get_logger

logger = get_logger("vibe.qa")


class QAAgent(BaseAgent):
    """
    The QA agent reads the spec, Coder output, and QA instructions, then
    produces a PASS / FAIL / SPEC_UNCLEAR verdict with a detailed report.
    Step 8 of the pipeline.
    """

    name = "qa"
    system_prompt = (
        "You are the QA Engineer in a Vibe Coding automated development pipeline. "
        "Your role is to rigorously test implementations against their specs. "
        "Be thorough and critical. Your verdicts directly control whether the "
        "pipeline succeeds or retries. "
        "Your verdict must be exactly one of: PASS, FAIL, or SPEC_UNCLEAR."
    )

    def test(self, ctx: PipelineContext) -> tuple[QAVerdict, str]:
        """
        Test the Coder's implementation and produce a QA report.
        Returns (verdict, report_markdown).
        """
        logger.info("[QA] testing implementation (iteration %d)", ctx.iteration)
        prompt = f"""
You are performing quality assurance on the following implementation.

## QA Instructions (from Manager)
{ctx.qa_instructions}

## Approved Code Spec
{ctx.approved_spec}

## Coder Output
{ctx.coder_output}

Produce a complete QA report using EXACTLY this structure:

---
# QA Report

## Verdict
**VERDICT: <PASS|FAIL|SPEC_UNCLEAR>**

## Tests Performed
List each test with its result (✅ pass / ❌ fail):
- Test 1: description → ✅/❌
- ...

## Issues Found
If PASS, write "None."
Otherwise, for each issue write:
### Issue N
- **Description**: what is wrong
- **Severity**: critical / major / minor
- **Location**: file path or function name
- **Steps to reproduce**: how to trigger the issue

## Spec Clarity Assessment
If SPEC_UNCLEAR, describe exactly what is missing or contradictory.
Otherwise write "Spec is clear."

## Recommendations
Actionable suggestions for the Coder or Planner.
---

Verdict definitions:
- PASS: all acceptance criteria met; no critical/major issues.
- FAIL: one or more critical/major issues found.
- SPEC_UNCLEAR: spec is missing information or is contradictory.
"""
        reply = self.chat(prompt)

        # Extract verdict
        verdict = QAVerdict.FAIL  # default
        for line in reply.splitlines():
            stripped = line.strip()
            if "VERDICT:" in stripped:
                # Handle formats like "**VERDICT: PASS**" or "VERDICT: PASS"
                raw = stripped.split("VERDICT:", 1)[1].strip().strip("*").strip().upper()
                # Take first word only
                raw = raw.split()[0] if raw.split() else raw
                if raw in QAVerdict._value2member_map_:
                    verdict = QAVerdict(raw)
                break

        logger.info("[QA] verdict: %s", verdict.value)
        return verdict, reply
