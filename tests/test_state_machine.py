import pytest
from src.models.task import Task, TaskStatus, TaskPriority, QAResult


class TestStateMachine:
    def test_happy_path_transitions(self):
        """Test full happy path: NEW → ... → DONE"""
        task = Task(title="Test", description="Test")
        assert task.status == TaskStatus.NEW

        transitions = [
            TaskStatus.MANAGER_PLANNING,
            TaskStatus.WAIT_PLANNER,
            TaskStatus.PLANNER_DONE,
            TaskStatus.MANAGER_SPEC_REVIEW,
            TaskStatus.WAIT_CODER,
            TaskStatus.CODER_DONE,
            TaskStatus.WAIT_QA,
            TaskStatus.QA_DONE,
            TaskStatus.DONE,
        ]

        for status in transitions:
            task.transition_to(status)
            assert task.status == status

    def test_fail_branch_transition(self):
        """FAIL branch: QA_DONE → WAIT_CODER (retry)"""
        task = Task(title="Test", description="Test")
        task.transition_to(TaskStatus.QA_DONE)
        task.last_qa_result = QAResult.FAIL

        # Reroute to coder
        task.transition_to(TaskStatus.WAIT_CODER)
        assert task.status == TaskStatus.WAIT_CODER
        assert task.last_qa_result == QAResult.FAIL

        # Complete the retry
        task.transition_to(TaskStatus.CODER_DONE)
        task.transition_to(TaskStatus.WAIT_QA)
        task.transition_to(TaskStatus.QA_DONE)
        task.last_qa_result = QAResult.PASS
        task.transition_to(TaskStatus.DONE)
        assert task.status == TaskStatus.DONE

    def test_spec_gap_branch_transition(self):
        """SPEC_GAP branch: QA_DONE → WAIT_PLANNER (retry)"""
        task = Task(title="Test", description="Test")
        task.transition_to(TaskStatus.QA_DONE)
        task.last_qa_result = QAResult.SPEC_GAP

        # Reroute to planner
        task.transition_to(TaskStatus.WAIT_PLANNER)
        assert task.status == TaskStatus.WAIT_PLANNER

        # Complete after spec fix
        task.transition_to(TaskStatus.PLANNER_DONE)
        task.transition_to(TaskStatus.MANAGER_SPEC_REVIEW)
        task.transition_to(TaskStatus.WAIT_CODER)
        task.transition_to(TaskStatus.CODER_DONE)
        task.transition_to(TaskStatus.WAIT_QA)
        task.transition_to(TaskStatus.QA_DONE)
        task.last_qa_result = QAResult.PASS
        task.transition_to(TaskStatus.DONE)
        assert task.status == TaskStatus.DONE

    def test_blocked_state(self):
        """Test BLOCKED state when max iterations exceeded."""
        task = Task(title="Test", description="Test")

        # Simulate hitting max iterations
        task.transition_to(TaskStatus.WAIT_QA)
        task.last_qa_result = QAResult.FAIL
        task.transition_to(TaskStatus.BLOCKED)

        assert task.status == TaskStatus.BLOCKED

    def test_iteration_tracking(self):
        """Test that iteration count is tracked correctly."""
        task = Task(title="Test", description="Test")
        assert task.iteration_count == 0

        task.increment_iteration()
        task.increment_iteration()
        task.increment_iteration()

        assert task.iteration_count == 3

    def test_updated_at_changes_on_transition(self):
        """Test that updated_at is updated on state transitions."""
        task = Task(title="Test", description="Test")
        initial_updated = task.updated_at

        task.transition_to(TaskStatus.MANAGER_PLANNING)
        assert task.updated_at >= initial_updated
