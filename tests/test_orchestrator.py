import pytest
import json
from typing import Optional
from src.orchestrator.engine import OrchestratorEngine, OrchestratorConfig
from src.agents.base import BaseAgentClient, AgentResponse
from src.agents.manager import MockManagerAgentClient
from src.agents.planner import MockPlannerAgentClient
from src.agents.coder import MockCoderAgentClient
from src.agents.qa import MockQAAgentClient
from src.models.log_entry import AgentRole
from src.models.task import TaskStatus


class SequentialQAClient(BaseAgentClient):
    """QA client that returns results from a sequence."""
    def __init__(self, results: list):
        super().__init__(role=AgentRole.QA)
        self._results = list(results)
        self._index = 0

    def call(self, prompt: str, context: Optional[dict] = None) -> AgentResponse:
        result = self._results[self._index] if self._index < len(self._results) else "PASS"
        self._index += 1
        response = {
            "result": result,
            "findings": [f"Finding for result {result}"],
            "summary": f"QA result: {result}",
        }
        return AgentResponse(raw=json.dumps(response), role=self.role, success=True)


class TestOrchestratorHappyPath:
    def test_run_returns_summary(self, engine_pass):
        summary = engine_pass.run("Build a user authentication system")
        assert "run_id" in summary
        assert "total_tasks" in summary
        assert "tasks_done" in summary
        assert "task_results" in summary

    def test_happy_path_all_tasks_done(self, engine_pass):
        summary = engine_pass.run("Build a user authentication system")
        assert summary["tasks_done"] == summary["total_tasks"]
        assert all(r["status"] == TaskStatus.DONE.value for r in summary["task_results"])

    def test_happy_path_qa_result_pass(self, engine_pass):
        summary = engine_pass.run("Build a simple REST API")
        for result in summary["task_results"]:
            assert result["qa_result"] == "PASS"


class TestOrchestratorFailReroute:
    def test_fail_reroutes_to_coder(self, orchestrator_config):
        """QA returns FAIL first, then PASS on retry."""
        qa_client = SequentialQAClient(["FAIL", "PASS"])
        engine = OrchestratorEngine(
            config=orchestrator_config,
            manager_client=MockManagerAgentClient(),
            planner_client=MockPlannerAgentClient(),
            coder_client=MockCoderAgentClient(),
            qa_client=qa_client,
        )
        summary = engine.run("Build a feature with a bug initially")
        assert summary["total_tasks"] >= 1
        # Final result should be PASS after retry
        for result in summary["task_results"]:
            assert result["qa_result"] == "PASS"


class TestOrchestratorSpecGapReroute:
    def test_spec_gap_reroutes_to_planner(self, orchestrator_config):
        """QA returns SPEC_GAP first, then PASS after planner revision."""
        qa_client = SequentialQAClient(["SPEC_GAP", "PASS"])
        engine = OrchestratorEngine(
            config=orchestrator_config,
            manager_client=MockManagerAgentClient(),
            planner_client=MockPlannerAgentClient(),
            coder_client=MockCoderAgentClient(),
            qa_client=qa_client,
        )
        summary = engine.run("Build a feature with spec gap initially")
        assert summary["total_tasks"] >= 1


class TestOrchestratorMaxIterations:
    def test_max_iterations_blocks_task(self, tmp_path):
        """Task gets BLOCKED when max_iterations is exceeded."""
        config = OrchestratorConfig(
            max_iterations=2,
            storage_path=str(tmp_path / "runs"),
            prompts_path="prompts",
        )
        # QA always returns SPEC_GAP to force max iterations
        qa_client = MockQAAgentClient(result="SPEC_GAP")
        engine = OrchestratorEngine(
            config=config,
            manager_client=MockManagerAgentClient(),
            planner_client=MockPlannerAgentClient(),
            coder_client=MockCoderAgentClient(),
            qa_client=qa_client,
        )
        summary = engine.run("A task that keeps failing QA")
        # With max_iterations=2 and always SPEC_GAP, task should be BLOCKED
        assert summary["total_tasks"] >= 1
        blocked_count = sum(1 for r in summary["task_results"] if r["status"] == TaskStatus.BLOCKED.value)
        assert blocked_count >= 1

    def test_summary_success_rate(self, engine_pass):
        summary = engine_pass.run("Build something")
        assert 0.0 <= summary["success_rate"] <= 1.0


class TestOrchestratorStorage:
    def test_tasks_saved_to_storage(self, engine_pass, tmp_path):
        """Test that tasks are persisted to storage."""
        summary = engine_pass.run("Build a feature")
        task_ids = engine_pass.storage.list_tasks()
        assert len(task_ids) >= 1

    def test_summary_saved_to_storage(self, engine_pass):
        summary = engine_pass.run("Build a feature")
        loaded = engine_pass.storage.load_summary(engine_pass.run_id)
        assert loaded is not None
        assert loaded["run_id"] == summary["run_id"]
