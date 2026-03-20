import pytest
from datetime import datetime
from src.models.task import Task, TaskStatus, TaskPriority, QAResult
from src.models.log_entry import LogEntry, AgentRole


class TestTaskModel:
    def test_task_creation_defaults(self):
        task = Task(title="Test", description="Test description")
        assert task.title == "Test"
        assert task.description == "Test description"
        assert task.status == TaskStatus.NEW
        assert task.priority == TaskPriority.MEDIUM
        assert task.iteration_count == 0
        assert task.id is not None
        assert isinstance(task.created_at, datetime)

    def test_task_creation_custom_fields(self):
        task = Task(
            title="Custom Task",
            description="Custom description",
            priority=TaskPriority.CRITICAL,
            acceptance_criteria=["AC1", "AC2"],
        )
        assert task.priority == TaskPriority.CRITICAL
        assert len(task.acceptance_criteria) == 2

    def test_task_transition_to(self):
        task = Task(title="Test", description="Test")
        old_updated = task.updated_at
        task.transition_to(TaskStatus.MANAGER_PLANNING)
        assert task.status == TaskStatus.MANAGER_PLANNING
        assert task.updated_at >= old_updated

    def test_task_increment_iteration(self):
        task = Task(title="Test", description="Test")
        assert task.iteration_count == 0
        task.increment_iteration()
        assert task.iteration_count == 1
        task.increment_iteration()
        assert task.iteration_count == 2

    def test_task_serialization(self):
        task = Task(title="Test", description="Test")
        data = task.model_dump()
        assert "id" in data
        assert "title" in data
        assert "status" in data

    def test_task_deserialization(self):
        task = Task(title="Test", description="Test")
        data = task.model_dump()
        restored = Task.model_validate(data)
        assert restored.id == task.id
        assert restored.title == task.title

    def test_qa_result_enum(self):
        assert QAResult.PASS == "PASS"
        assert QAResult.FAIL == "FAIL"
        assert QAResult.SPEC_GAP == "SPEC_GAP"

    def test_task_priority_enum(self):
        assert TaskPriority.LOW == "LOW"
        assert TaskPriority.MEDIUM == "MEDIUM"
        assert TaskPriority.HIGH == "HIGH"
        assert TaskPriority.CRITICAL == "CRITICAL"


class TestLogEntryModel:
    def test_log_entry_creation(self):
        entry = LogEntry(
            task_id="task-123",
            iteration=1,
            role=AgentRole.PLANNER,
            raw_response="raw response",
            status="SUCCESS",
        )
        assert entry.task_id == "task-123"
        assert entry.iteration == 1
        assert entry.role == AgentRole.PLANNER
        assert entry.status == "SUCCESS"
        assert entry.id is not None

    def test_log_entry_with_error(self):
        entry = LogEntry(
            task_id="task-123",
            iteration=1,
            role=AgentRole.CODER,
            raw_response="",
            status="AGENT_ERROR",
            error_message="Connection failed",
        )
        assert entry.status == "AGENT_ERROR"
        assert entry.error_message == "Connection failed"

    def test_agent_role_enum(self):
        assert AgentRole.MANAGER == "MANAGER"
        assert AgentRole.PLANNER == "PLANNER"
        assert AgentRole.CODER == "CODER"
        assert AgentRole.QA == "QA"
        assert AgentRole.ORCHESTRATOR == "ORCHESTRATOR"
