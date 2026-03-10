"""
Vibe Coding Agent Orchestrator
Manager Agent – coordinates all other agents across the 9-step pipeline.
"""
from __future__ import annotations

from orchestrator.agents.base_agent import BaseAgent
from orchestrator.models import PipelineContext, QAVerdict
from orchestrator.utils import get_logger

logger = get_logger("vibe.manager")


class ManagerAgent(BaseAgent):
    """
    The Manager directs the entire pipeline:
      Step 1 – analyse the task and produce subtasks
      Step 2 – create Planner instructions
      Step 5 – review the Planner's spec and produce an approved spec
      Step 6 – create Coder instructions from the approved spec
      Step 7 – create QA instructions after reading the Coder output
      Step 9 – evaluate QA results and decide next action
    """

    name = "manager"
    system_prompt = (
        "You are the Manager in a Vibe Coding automated development pipeline. "
        "Your job is to coordinate Planner, Coder, and QA agents by producing "
        "clear, structured markdown documents that each agent can follow. "
        "Be concise, precise, and always reason step-by-step before writing output."
    )

    # ------------------------------------------------------------------
    # Step 1: Analyse the task
    # ------------------------------------------------------------------
    def analyse_task(self, ctx: PipelineContext) -> str:
        """
        Break the user task into subtasks and write an analysis.
        Returns the analysis markdown.
        """
        logger.info("[Manager] Step 1 – analysing task: %s", ctx.task.title)
        prompt = f"""
You have received the following task from the user:

**Title**: {ctx.task.title}

**Description**:
{ctx.task.description}

Please produce a Manager Analysis with the following sections:

## 1. Understanding
Restate what needs to be built in your own words.

## 2. Subtasks
List every concrete subtask required to complete the project. Number them.

## 3. Risks & Considerations
Any technical risks, ambiguities, or important decisions.

## 4. Execution Plan
High-level plan showing the order of agent invocations.

Write the analysis in markdown.
"""
        return self.chat(prompt)

    # ------------------------------------------------------------------
    # Step 2: Create Planner instructions
    # ------------------------------------------------------------------
    def create_planner_instructions(self, ctx: PipelineContext) -> str:
        """
        Create a detailed brief for the Planner agent.
        Returns the instructions markdown.
        """
        logger.info("[Manager] Step 2 – creating Planner instructions")
        prompt = f"""
Based on the following task analysis, write a detailed instruction document for the Planner agent.

## Task Analysis
{ctx.manager_analysis}

The Planner will use this document to write a full Code Spec. Your instructions must include:

1. **Objective** – What exactly should be built.
2. **Key Requirements** – Functional and non-functional requirements.
3. **Technology Constraints** – Preferred languages, frameworks, or tools.
4. **Deliverables** – What files / modules the Coder must produce.
5. **Acceptance Criteria** – How QA will verify success.

Write the instructions in markdown. Be specific and leave no ambiguity.
"""
        return self.chat(prompt)

    # ------------------------------------------------------------------
    # Step 5: Review the Planner's spec
    # ------------------------------------------------------------------
    def review_spec(self, ctx: PipelineContext) -> str:
        """
        Review the Planner's spec, improve it, and produce an approved spec.
        Returns the approved spec markdown.
        """
        logger.info("[Manager] Step 5 – reviewing Planner spec")
        prompt = f"""
The Planner has produced the following Code Spec:

---
{ctx.planner_spec}
---

Your task:
1. Review the spec critically against the original task requirements below.
2. Identify any gaps, ambiguities, or issues.
3. Produce an **Approved Code Spec** that fixes all issues.

**Original Task**: {ctx.task.title}
{ctx.task.description}

Write the full Approved Code Spec in markdown. Add a brief "## Manager Review Notes" section
at the top listing what you changed and why.
"""
        return self.chat(prompt)

    # ------------------------------------------------------------------
    # Step 6: Create Coder instructions
    # ------------------------------------------------------------------
    def create_coder_instructions(self, ctx: PipelineContext) -> str:
        """
        Write implementation instructions for the Coder based on the approved spec.
        Returns the instructions markdown.
        """
        logger.info("[Manager] Step 6 – creating Coder instructions")
        prompt = f"""
The following Code Spec has been approved. Write clear implementation instructions for the Coder agent.

## Approved Spec
{ctx.approved_spec}

Your instructions must include:
1. **Summary of what to implement**.
2. **File list** – Every file the Coder must create or modify with a brief description.
3. **Implementation order** – Which files to write first.
4. **Code style & conventions** – Naming, formatting, documentation requirements.
5. **Special notes** – Anything the Coder must be careful about.

Write in markdown.
"""
        return self.chat(prompt)

    # ------------------------------------------------------------------
    # Step 7: Create QA instructions
    # ------------------------------------------------------------------
    def create_qa_instructions(self, ctx: PipelineContext) -> str:
        """
        After reading the Coder's output, write QA test instructions.
        Returns the instructions markdown.
        """
        logger.info("[Manager] Step 7 – creating QA instructions")
        prompt = f"""
The Coder has finished implementation. Here is their output summary:

## Coder Output
{ctx.coder_output}

## Approved Spec
{ctx.approved_spec}

Write detailed QA instructions for the QA agent. Include:
1. **Test Scenarios** – Functional tests for each feature.
2. **Edge Cases** – Boundary conditions and error paths to test.
3. **How to Run** – Exact commands to execute the code and tests.
4. **Acceptance Criteria** – Precise conditions for a PASS verdict.
5. **Spec Checklist** – Verify every deliverable from the spec is present.

Write in markdown.
"""
        return self.chat(prompt)

    # ------------------------------------------------------------------
    # Step 9: Evaluate QA results
    # ------------------------------------------------------------------
    def evaluate_qa_results(self, ctx: PipelineContext) -> tuple[QAVerdict, str]:
        """
        Read QA output and decide: PASS / FAIL / SPEC_UNCLEAR.
        Returns (verdict, decision_summary_markdown).
        """
        logger.info("[Manager] Step 9 – evaluating QA results (iteration %d)", ctx.iteration)
        prompt = f"""
The QA agent has completed testing. Here is their report:

## QA Report
{ctx.qa_output}

## Context
- Task: {ctx.task.title}
- Pipeline iteration: {ctx.iteration} of {ctx.max_iterations}

Based on the QA report, decide the outcome:

- **PASS** – All acceptance criteria met; the task is complete.
- **FAIL** – Critical or major issues exist; the Coder must fix them.
- **SPEC_UNCLEAR** – The spec is missing or contradictory; the Planner must update it.

Respond in the following exact format:

```
VERDICT: <PASS|FAIL|SPEC_UNCLEAR>

## Reasoning
<Your step-by-step reasoning>

## Action
<What happens next: describe what the next agent should do>
```
"""
        reply = self.chat(prompt)

        # Extract verdict from reply
        verdict = QAVerdict.FAIL  # default
        for line in reply.splitlines():
            stripped = line.strip()
            if stripped.startswith("VERDICT:"):
                raw = stripped.split(":", 1)[1].strip().upper()
                if raw in QAVerdict._value2member_map_:
                    verdict = QAVerdict(raw)
                break

        return verdict, reply
