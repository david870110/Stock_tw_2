"""
Vibe Coding Agent Orchestrator
Pipeline – the 9-step state machine that coordinates all agents.
"""
from __future__ import annotations

import json
from pathlib import Path

from orchestrator.agents import CoderAgent, ManagerAgent, PlannerAgent, QAAgent
from orchestrator.config import get_config
from orchestrator.models import PipelineContext, PipelineState, QAVerdict, Task
from orchestrator.utils import ensure_dir, get_logger, read_log, write_log

logger = get_logger("vibe.pipeline")


class Pipeline:
    """
    Orchestrates the Vibe Coding pipeline across 9 steps.

    Step 1  – Manager analyses task and creates subtasks
    Step 2  – Manager creates Planner instructions
    Step 3  – Manager hands instructions to Planner (recorded in log)
    Step 4  – Planner creates Code Spec
    Step 5  – Manager reviews spec and produces approved spec
    Step 6  – Manager creates Coder instructions and hands them over
    Step 7  – Coder implements; Manager creates QA instructions
    Step 8  – QA tests the implementation
    Step 9  – Manager evaluates QA result → PASS / FAIL / SPEC_UNCLEAR
    """

    def __init__(self) -> None:
        cfg = get_config()
        self.cfg = cfg
        self.manager = ManagerAgent()
        self.planner = PlannerAgent()
        self.coder = CoderAgent()
        self.qa = QAAgent()

        ensure_dir(cfg.logs_dir)
        ensure_dir(cfg.tasks_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, task: Task) -> PipelineContext:
        """
        Run the full pipeline for *task*.
        Returns the final :class:`PipelineContext`.
        """
        ctx = PipelineContext(task=task, max_iterations=self.cfg.max_iterations)
        self._save_state(ctx)

        logger.info("=" * 60)
        logger.info("Starting Vibe Coding pipeline")
        logger.info("Task: %s", task.title)
        logger.info("=" * 60)

        while ctx.state not in (PipelineState.COMPLETED, PipelineState.FAILED):
            ctx = self._tick(ctx)
            self._save_state(ctx)

        self._write_history(ctx)
        logger.info("=" * 60)
        logger.info("Pipeline finished: %s", ctx.state.value)
        logger.info("=" * 60)
        return ctx

    def resume(self) -> PipelineContext:
        """Resume a pipeline from the saved state file."""
        state_path = Path(self.cfg.state_file)
        if not state_path.exists():
            raise FileNotFoundError(f"No saved pipeline state found at {state_path}")
        ctx = PipelineContext.from_json(state_path.read_text(encoding="utf-8"))
        logger.info("Resuming pipeline from state: %s", ctx.state.value)
        return self.run_from(ctx)

    def run_from(self, ctx: PipelineContext) -> PipelineContext:
        """Continue running from an existing context."""
        while ctx.state not in (PipelineState.COMPLETED, PipelineState.FAILED):
            ctx = self._tick(ctx)
            self._save_state(ctx)
        return ctx

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _tick(self, ctx: PipelineContext) -> PipelineContext:
        """Advance the pipeline by one step."""
        state = ctx.state

        if state == PipelineState.INIT:
            ctx = self._step1_task_analysis(ctx)

        elif state == PipelineState.TASK_ANALYSIS:
            ctx = self._step2_planner_instruction(ctx)

        elif state == PipelineState.PLANNER_INSTRUCTION:
            ctx = self._steps3_4_planning(ctx)

        elif state == PipelineState.PLANNING:
            ctx = self._step5_spec_review(ctx)

        elif state == PipelineState.SPEC_REVIEW:
            ctx = self._step6_coding(ctx)

        elif state == PipelineState.CODING:
            ctx = self._step7_qa_instruction(ctx)

        elif state == PipelineState.QA_TESTING:
            ctx = self._step8_qa_test(ctx)

        elif state == PipelineState.QA_REVIEW:
            ctx = self._step9_evaluate(ctx)

        else:
            logger.error("Unknown state: %s", state)
            ctx.state = PipelineState.FAILED

        return ctx

    # ------------------------------------------------------------------
    # Individual steps
    # ------------------------------------------------------------------

    def _step1_task_analysis(self, ctx: PipelineContext) -> PipelineContext:
        """Step 1 – Manager analyses the task."""
        logger.info("--- Step 1: Task Analysis ---")
        ctx.state = PipelineState.TASK_ANALYSIS
        ctx.manager_analysis = self.manager.analyse_task(ctx)
        write_log(f"{self.cfg.logs_dir}/manager_analysis.md", ctx.manager_analysis)
        ctx.add_history_entry("manager", "task_analysis", "Manager analysed task and created subtasks")
        logger.info("Step 1 complete. Analysis written to logs/manager_analysis.md")
        return ctx

    def _step2_planner_instruction(self, ctx: PipelineContext) -> PipelineContext:
        """Step 2 – Manager creates Planner instructions."""
        logger.info("--- Step 2: Creating Planner Instructions ---")
        ctx.planner_instructions = self.manager.create_planner_instructions(ctx)
        write_log(f"{self.cfg.logs_dir}/planner_instructions.md", ctx.planner_instructions)
        ctx.state = PipelineState.PLANNER_INSTRUCTION
        ctx.add_history_entry("manager", "planner_instruction", "Manager created Planner instructions")
        logger.info("Step 2 complete. Instructions written to logs/planner_instructions.md")
        return ctx

    def _steps3_4_planning(self, ctx: PipelineContext) -> PipelineContext:
        """Steps 3–4 – Planner receives instructions and writes the spec."""
        logger.info("--- Steps 3-4: Planning (Planner creates Code Spec) ---")
        # Step 3: The hand-off is represented by the log file already written in step 2.
        # Step 4: Planner reads instructions and creates spec.
        ctx.planner_spec = self.planner.create_spec(ctx)
        write_log(f"{self.cfg.logs_dir}/planner_spec.md", ctx.planner_spec)
        ctx.state = PipelineState.PLANNING
        ctx.add_history_entry("planner", "planning", "Planner created Code Spec")
        logger.info("Steps 3-4 complete. Spec written to logs/planner_spec.md")
        return ctx

    def _step5_spec_review(self, ctx: PipelineContext) -> PipelineContext:
        """Step 5 – Manager reviews and approves the spec."""
        logger.info("--- Step 5: Spec Review ---")
        ctx.approved_spec = self.manager.review_spec(ctx)
        write_log(f"{self.cfg.logs_dir}/approved_spec.md", ctx.approved_spec)
        ctx.state = PipelineState.SPEC_REVIEW
        ctx.add_history_entry("manager", "spec_review", "Manager reviewed and approved the spec")
        logger.info("Step 5 complete. Approved spec written to logs/approved_spec.md")
        return ctx

    def _step6_coding(self, ctx: PipelineContext) -> PipelineContext:
        """Step 6 – Manager creates Coder instructions; Coder implements."""
        logger.info("--- Step 6: Coding ---")
        ctx.coder_instructions = self.manager.create_coder_instructions(ctx)
        write_log(f"{self.cfg.logs_dir}/coder_instructions.md", ctx.coder_instructions)
        ctx.coder_output = self.coder.implement(ctx)
        write_log(f"{self.cfg.logs_dir}/coder_output.md", ctx.coder_output)
        ctx.state = PipelineState.CODING
        ctx.add_history_entry("coder", "coding", "Coder implemented the code")
        logger.info("Step 6 complete. Coder output written to logs/coder_output.md")
        return ctx

    def _step7_qa_instruction(self, ctx: PipelineContext) -> PipelineContext:
        """Step 7 – Manager creates QA instructions."""
        logger.info("--- Step 7: Creating QA Instructions ---")
        ctx.qa_instructions = self.manager.create_qa_instructions(ctx)
        write_log(f"{self.cfg.logs_dir}/qa_instructions.md", ctx.qa_instructions)
        ctx.state = PipelineState.QA_TESTING
        ctx.add_history_entry("manager", "qa_instruction", "Manager created QA instructions")
        logger.info("Step 7 complete. QA instructions written to logs/qa_instructions.md")
        return ctx

    def _step8_qa_test(self, ctx: PipelineContext) -> PipelineContext:
        """Step 8 – QA tests the implementation."""
        logger.info("--- Step 8: QA Testing ---")
        verdict, qa_output = self.qa.test(ctx)
        ctx.qa_verdict = verdict
        ctx.qa_output = qa_output
        write_log(f"{self.cfg.logs_dir}/qa_output.md", ctx.qa_output)
        ctx.state = PipelineState.QA_REVIEW
        ctx.add_history_entry("qa", "qa_testing", f"QA completed testing with preliminary verdict: {verdict.value}")
        logger.info("Step 8 complete. QA report written to logs/qa_output.md")
        return ctx

    def _step9_evaluate(self, ctx: PipelineContext) -> PipelineContext:
        """Step 9 – Manager evaluates QA result and decides next action."""
        logger.info("--- Step 9: Evaluating QA Results ---")
        verdict, decision = self.manager.evaluate_qa_results(ctx)
        ctx.qa_verdict = verdict
        ctx.pipeline_result = decision
        write_log(f"{self.cfg.logs_dir}/pipeline_result.md", ctx.pipeline_result)
        ctx.add_history_entry("manager", "qa_review", f"Manager evaluated QA results: {verdict.value}")

        if verdict == QAVerdict.PASS:
            logger.info("✅ QA PASSED – pipeline complete!")
            ctx.state = PipelineState.COMPLETED

        elif verdict == QAVerdict.FAIL:
            ctx.iteration += 1
            if ctx.iteration >= ctx.max_iterations:
                logger.error(
                    "❌ QA FAILED after %d iterations – pipeline failed.", ctx.max_iterations
                )
                ctx.state = PipelineState.FAILED
            else:
                logger.warning(
                    "⚠️  QA FAILED – sending back to Coder (iteration %d/%d)",
                    ctx.iteration,
                    ctx.max_iterations,
                )
                # Re-enter at SPEC_REVIEW so Coder re-implements with the same spec
                ctx.state = PipelineState.SPEC_REVIEW

        elif verdict == QAVerdict.SPEC_UNCLEAR:
            ctx.iteration += 1
            if ctx.iteration >= ctx.max_iterations:
                logger.error(
                    "❌ SPEC_UNCLEAR after %d iterations – pipeline failed.", ctx.max_iterations
                )
                ctx.state = PipelineState.FAILED
            else:
                logger.warning(
                    "⚠️  SPEC_UNCLEAR – sending back to Planner (iteration %d/%d)",
                    ctx.iteration,
                    ctx.max_iterations,
                )
                # Re-enter at PLANNER_INSTRUCTION so Planner rewrites spec
                ctx.state = PipelineState.PLANNER_INSTRUCTION

        return ctx

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self, ctx: PipelineContext) -> None:
        """Persist pipeline context to disk."""
        write_log(self.cfg.state_file, ctx.to_json())

    def _write_history(self, ctx: PipelineContext) -> None:
        """Write human-readable pipeline history."""
        lines = ["# Pipeline History\n"]
        for entry in ctx.history:
            lines.append(
                f"- [{entry['timestamp']}] iter={entry['iteration']} "
                f"**{entry['agent']}** / {entry['step']}: {entry['summary']}"
            )
        write_log(f"{self.cfg.logs_dir}/pipeline_history.md", "\n".join(lines))
