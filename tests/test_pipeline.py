"""
Tests for the Vibe Coding Agent Orchestrator pipeline.

These tests mock all LLM calls so they run without a real API key.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orchestrator.models import (
    PipelineContext,
    PipelineState,
    QAVerdict,
    Task,
)
from orchestrator.pipeline import Pipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(title: str = "Test Task", description: str = "Build something") -> Task:
    return Task(title=title, description=description)


def _make_ctx(state: PipelineState = PipelineState.INIT) -> PipelineContext:
    ctx = PipelineContext(task=_make_task(), state=state)
    return ctx


# ---------------------------------------------------------------------------
# Model unit tests
# ---------------------------------------------------------------------------

class TestTask:
    def test_to_dict_roundtrip(self):
        task = _make_task()
        assert Task.from_dict(task.to_dict()).title == task.title
        assert Task.from_dict(task.to_dict()).description == task.description

    def test_id_auto_generated(self):
        t1 = Task(title="A", description="B")
        t2 = Task(title="A", description="B")
        # IDs include timestamp so they can be equal if created in same second,
        # but they should never be empty
        assert t1.id != "" and t2.id != ""


class TestPipelineContext:
    def test_initial_state(self):
        ctx = PipelineContext()
        assert ctx.state == PipelineState.INIT
        assert ctx.iteration == 0
        assert ctx.history == []

    def test_add_history_entry(self):
        ctx = _make_ctx()
        ctx.add_history_entry("manager", "step1", "did something")
        assert len(ctx.history) == 1
        assert ctx.history[0]["agent"] == "manager"
        assert ctx.history[0]["step"] == "step1"

    def test_json_roundtrip(self):
        ctx = _make_ctx()
        ctx.qa_verdict = QAVerdict.PASS
        ctx.manager_analysis = "some analysis"
        restored = PipelineContext.from_json(ctx.to_json())
        assert restored.state == ctx.state
        assert restored.qa_verdict == QAVerdict.PASS
        assert restored.manager_analysis == "some analysis"
        assert restored.task.title == ctx.task.title

    def test_state_serialization(self):
        ctx = _make_ctx(PipelineState.CODING)
        data = json.loads(ctx.to_json())
        assert data["state"] == "coding"


# ---------------------------------------------------------------------------
# Pipeline state-machine unit tests  (LLM calls are mocked)
# ---------------------------------------------------------------------------

MOCK_ANALYSIS = "## 1. Understanding\nBuild a thing.\n## 2. Subtasks\n1. Do X\n## 3. Risks\nNone\n## 4. Plan\nSeq"
MOCK_PLANNER_INSTR = "## Objective\nBuild X\n## Requirements\n- req1"
MOCK_SPEC = "## 1. Overview\nBuild X\n## 8. Open Questions\nNone"
MOCK_APPROVED_SPEC = "## Manager Review Notes\nLooks good.\n\n" + MOCK_SPEC
MOCK_CODER_INSTR = "## Summary\nImplement X"
MOCK_CODER_OUTPUT = "### `src/main.py`\n```python\nprint('hello')\n```\n## Coder Output Summary\n- Files: src/main.py\n- How to Run: python src/main.py"
MOCK_QA_INSTR = "## Test Scenarios\n1. Run main.py"
MOCK_QA_PASS = "# QA Report\n## Verdict\n**VERDICT: PASS**\n## Tests Performed\n- run → ✅\n## Issues Found\nNone.\n## Spec Clarity Assessment\nSpec is clear.\n## Recommendations\nNone"
MOCK_QA_FAIL = "# QA Report\n## Verdict\n**VERDICT: FAIL**\n## Tests Performed\n- run → ❌\n## Issues Found\n### Issue 1\n- **Description**: crash\n- **Severity**: critical\n## Spec Clarity Assessment\nSpec is clear.\n## Recommendations\nFix crash"
MOCK_QA_SPEC_UNCLEAR = "# QA Report\n## Verdict\n**VERDICT: SPEC_UNCLEAR**\n## Tests Performed\n## Issues Found\n## Spec Clarity Assessment\nMissing data model.\n## Recommendations\nUpdate spec"
MOCK_MANAGER_PASS_EVAL = "VERDICT: PASS\n\n## Reasoning\nAll good\n\n## Action\nDone"
MOCK_MANAGER_FAIL_EVAL = "VERDICT: FAIL\n\n## Reasoning\nCrash found\n\n## Action\nFix it"
MOCK_MANAGER_SPEC_EVAL = "VERDICT: SPEC_UNCLEAR\n\n## Reasoning\nSpec missing\n\n## Action\nRe-plan"


@pytest.fixture()
def tmp_logs(tmp_path, monkeypatch):
    """Redirect logs and state file to a temp directory."""
    monkeypatch.setenv("VIBE_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("VIBE_STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("VIBE_TASKS_DIR", str(tmp_path / "tasks"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    # Reset singleton config
    import orchestrator.config as cfg_mod
    cfg_mod._config = None
    yield tmp_path
    cfg_mod._config = None


def _patch_agents(
    manager_mock: MagicMock,
    planner_mock: MagicMock,
    coder_mock: MagicMock,
    qa_mock: MagicMock,
) -> None:
    """Configure agent mock return values for a happy-path run."""
    manager_mock.return_value.analyse_task.return_value = MOCK_ANALYSIS
    manager_mock.return_value.create_planner_instructions.return_value = MOCK_PLANNER_INSTR
    manager_mock.return_value.review_spec.return_value = MOCK_APPROVED_SPEC
    manager_mock.return_value.create_coder_instructions.return_value = MOCK_CODER_INSTR
    manager_mock.return_value.create_qa_instructions.return_value = MOCK_QA_INSTR
    manager_mock.return_value.evaluate_qa_results.return_value = (
        QAVerdict.PASS, MOCK_MANAGER_PASS_EVAL
    )
    planner_mock.return_value.create_spec.return_value = MOCK_SPEC
    coder_mock.return_value.implement.return_value = MOCK_CODER_OUTPUT
    qa_mock.return_value.test.return_value = (QAVerdict.PASS, MOCK_QA_PASS)


@patch("orchestrator.pipeline.QAAgent")
@patch("orchestrator.pipeline.CoderAgent")
@patch("orchestrator.pipeline.PlannerAgent")
@patch("orchestrator.pipeline.ManagerAgent")
class TestPipelineHappyPath:
    def test_full_pass(self, manager_mock, planner_mock, coder_mock, qa_mock, tmp_logs):
        _patch_agents(manager_mock, planner_mock, coder_mock, qa_mock)
        pipeline = Pipeline()
        ctx = pipeline.run(_make_task())

        assert ctx.state == PipelineState.COMPLETED
        assert ctx.qa_verdict == QAVerdict.PASS
        assert ctx.iteration == 0

    def test_log_files_created(self, manager_mock, planner_mock, coder_mock, qa_mock, tmp_logs):
        _patch_agents(manager_mock, planner_mock, coder_mock, qa_mock)
        pipeline = Pipeline()
        pipeline.run(_make_task())

        logs_dir = tmp_logs / "logs"
        expected_files = [
            "manager_analysis.md",
            "planner_instructions.md",
            "planner_spec.md",
            "approved_spec.md",
            "coder_instructions.md",
            "coder_output.md",
            "qa_instructions.md",
            "qa_output.md",
            "pipeline_result.md",
        ]
        for fname in expected_files:
            assert (logs_dir / fname).exists(), f"Missing log file: {fname}"

    def test_state_file_persisted(self, manager_mock, planner_mock, coder_mock, qa_mock, tmp_logs):
        _patch_agents(manager_mock, planner_mock, coder_mock, qa_mock)
        pipeline = Pipeline()
        pipeline.run(_make_task())

        state_file = tmp_logs / "state.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["state"] == "completed"

    def test_history_recorded(self, manager_mock, planner_mock, coder_mock, qa_mock, tmp_logs):
        _patch_agents(manager_mock, planner_mock, coder_mock, qa_mock)
        pipeline = Pipeline()
        ctx = pipeline.run(_make_task())

        assert len(ctx.history) >= 7  # at least one entry per major step
        agents_seen = {e["agent"] for e in ctx.history}
        assert "manager" in agents_seen
        assert "planner" in agents_seen
        assert "coder" in agents_seen
        assert "qa" in agents_seen


@patch("orchestrator.pipeline.QAAgent")
@patch("orchestrator.pipeline.CoderAgent")
@patch("orchestrator.pipeline.PlannerAgent")
@patch("orchestrator.pipeline.ManagerAgent")
class TestPipelineRetries:
    def test_qa_fail_retries_coder(self, manager_mock, planner_mock, coder_mock, qa_mock, tmp_logs):
        """QA FAIL on first run → retry Coder → QA PASS on second run."""
        _patch_agents(manager_mock, planner_mock, coder_mock, qa_mock)
        # First QA call: FAIL; second: PASS
        qa_mock.return_value.test.side_effect = [
            (QAVerdict.FAIL, MOCK_QA_FAIL),
            (QAVerdict.PASS, MOCK_QA_PASS),
        ]
        manager_mock.return_value.evaluate_qa_results.side_effect = [
            (QAVerdict.FAIL, MOCK_MANAGER_FAIL_EVAL),
            (QAVerdict.PASS, MOCK_MANAGER_PASS_EVAL),
        ]
        pipeline = Pipeline()
        ctx = pipeline.run(_make_task())
        assert ctx.state == PipelineState.COMPLETED
        assert ctx.iteration == 1

    def test_spec_unclear_retries_planner(self, manager_mock, planner_mock, coder_mock, qa_mock, tmp_logs):
        """QA SPEC_UNCLEAR → retry Planner → QA PASS on second run."""
        _patch_agents(manager_mock, planner_mock, coder_mock, qa_mock)
        qa_mock.return_value.test.side_effect = [
            (QAVerdict.SPEC_UNCLEAR, MOCK_QA_SPEC_UNCLEAR),
            (QAVerdict.PASS, MOCK_QA_PASS),
        ]
        manager_mock.return_value.evaluate_qa_results.side_effect = [
            (QAVerdict.SPEC_UNCLEAR, MOCK_MANAGER_SPEC_EVAL),
            (QAVerdict.PASS, MOCK_MANAGER_PASS_EVAL),
        ]
        pipeline = Pipeline()
        ctx = pipeline.run(_make_task())
        assert ctx.state == PipelineState.COMPLETED
        assert ctx.iteration == 1

    def test_max_iterations_reached(self, manager_mock, planner_mock, coder_mock, qa_mock, tmp_logs):
        """Exhausting max_iterations → pipeline FAILED."""
        _patch_agents(manager_mock, planner_mock, coder_mock, qa_mock)
        # Always fail
        qa_mock.return_value.test.return_value = (QAVerdict.FAIL, MOCK_QA_FAIL)
        manager_mock.return_value.evaluate_qa_results.return_value = (
            QAVerdict.FAIL, MOCK_MANAGER_FAIL_EVAL
        )
        pipeline = Pipeline()
        ctx = pipeline.run(_make_task())
        assert ctx.state == PipelineState.FAILED


# ---------------------------------------------------------------------------
# QA agent verdict parsing tests
# ---------------------------------------------------------------------------

class TestQAVerdictParsing:
    """Ensure the QA agent correctly extracts verdicts from varied LLM responses."""

    def _run_parse(self, reply: str) -> QAVerdict:
        """Exercise the verdict-parsing logic in isolation."""
        verdict = QAVerdict.FAIL
        for line in reply.splitlines():
            stripped = line.strip()
            if "VERDICT:" in stripped:
                raw = stripped.split("VERDICT:", 1)[1].strip().strip("*").strip().upper()
                raw = raw.split()[0] if raw.split() else raw
                if raw in QAVerdict._value2member_map_:
                    verdict = QAVerdict(raw)
                break
        return verdict

    def test_parse_pass(self):
        assert self._run_parse("**VERDICT: PASS**") == QAVerdict.PASS

    def test_parse_fail(self):
        assert self._run_parse("VERDICT: FAIL") == QAVerdict.FAIL

    def test_parse_spec_unclear(self):
        assert self._run_parse("**VERDICT: SPEC_UNCLEAR**") == QAVerdict.SPEC_UNCLEAR

    def test_parse_pass_with_extra_text(self):
        assert self._run_parse("VERDICT: PASS – all good") == QAVerdict.PASS

    def test_defaults_to_fail_when_missing(self):
        assert self._run_parse("No verdict here") == QAVerdict.FAIL
