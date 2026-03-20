import pytest
import tempfile
import os
from pathlib import Path
from src.models.task import Task, TaskStatus, TaskPriority, QAResult
from src.models.log_entry import LogEntry, AgentRole
from src.storage.local_storage import LocalStorage
from src.parsing.parser import ResponseParser
from src.orchestrator.engine import OrchestratorEngine, OrchestratorConfig
from src.agents.manager import MockManagerAgentClient
from src.agents.planner import MockPlannerAgentClient
from src.agents.coder import MockCoderAgentClient
from src.agents.qa import MockQAAgentClient


@pytest.fixture
def sample_task():
    return Task(
        title="Test Task",
        description="A test task description",
        priority=TaskPriority.HIGH,
        acceptance_criteria=["Criterion 1", "Criterion 2"],
    )


@pytest.fixture
def sample_log_entry(sample_task):
    return LogEntry(
        task_id=sample_task.id,
        iteration=1,
        role=AgentRole.PLANNER,
        raw_response='{"spec": "test spec", "sections": [], "ready_for_coder": true}',
        parsed_response={"spec": "test spec", "sections": [], "ready_for_coder": True},
        status="SUCCESS",
    )


@pytest.fixture
def tmp_storage(tmp_path):
    return LocalStorage(base_path=str(tmp_path / "runs"))


@pytest.fixture
def parser():
    return ResponseParser()


@pytest.fixture
def mock_manager():
    return MockManagerAgentClient()


@pytest.fixture
def mock_planner():
    return MockPlannerAgentClient()


@pytest.fixture
def mock_coder():
    return MockCoderAgentClient()


@pytest.fixture
def mock_qa_pass():
    return MockQAAgentClient(result="PASS")


@pytest.fixture
def mock_qa_fail():
    return MockQAAgentClient(result="FAIL")


@pytest.fixture
def mock_qa_spec_gap():
    return MockQAAgentClient(result="SPEC_GAP")


@pytest.fixture
def orchestrator_config(tmp_path):
    return OrchestratorConfig(
        max_iterations=3,
        storage_path=str(tmp_path / "runs"),
        prompts_path="prompts",
    )


@pytest.fixture
def engine_pass(orchestrator_config):
    return OrchestratorEngine(
        config=orchestrator_config,
        manager_client=MockManagerAgentClient(),
        planner_client=MockPlannerAgentClient(),
        coder_client=MockCoderAgentClient(),
        qa_client=MockQAAgentClient(result="PASS"),
    )
