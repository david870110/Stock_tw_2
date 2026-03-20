import pytest
import json
from pathlib import Path
from src.models.task import Task, TaskStatus, TaskPriority, QAResult
from src.models.log_entry import LogEntry, AgentRole
from src.storage.local_storage import LocalStorage


class TestLocalStorage:
    def test_save_and_load_task(self, tmp_storage, sample_task):
        tmp_storage.save_task(sample_task)
        loaded = tmp_storage.load_task(sample_task.id)
        assert loaded is not None
        assert loaded.id == sample_task.id
        assert loaded.title == sample_task.title
        assert loaded.description == sample_task.description

    def test_load_nonexistent_task(self, tmp_storage):
        result = tmp_storage.load_task("nonexistent-id")
        assert result is None

    def test_save_task_updates_file(self, tmp_storage, sample_task):
        tmp_storage.save_task(sample_task)
        sample_task.transition_to(TaskStatus.MANAGER_PLANNING)
        tmp_storage.save_task(sample_task)

        loaded = tmp_storage.load_task(sample_task.id)
        assert loaded.status == TaskStatus.MANAGER_PLANNING

    def test_list_tasks(self, tmp_storage):
        task1 = Task(title="Task 1", description="Desc 1")
        task2 = Task(title="Task 2", description="Desc 2")
        tmp_storage.save_task(task1)
        tmp_storage.save_task(task2)

        task_ids = tmp_storage.list_tasks()
        assert task1.id in task_ids
        assert task2.id in task_ids

    def test_list_tasks_empty(self, tmp_storage):
        task_ids = tmp_storage.list_tasks()
        assert task_ids == []

    def test_save_and_load_log(self, tmp_storage, sample_log_entry):
        tmp_storage.save_log(sample_log_entry)
        logs = tmp_storage.load_logs_for_task(sample_log_entry.task_id)
        assert len(logs) == 1
        assert logs[0].id == sample_log_entry.id
        assert logs[0].role == AgentRole.PLANNER

    def test_load_logs_for_task_multiple(self, tmp_storage):
        task_id = "task-test-multi"
        for i in range(3):
            entry = LogEntry(
                task_id=task_id,
                iteration=i + 1,
                role=AgentRole.CODER,
                raw_response=f"response {i}",
                status="SUCCESS",
            )
            tmp_storage.save_log(entry)

        logs = tmp_storage.load_logs_for_task(task_id)
        assert len(logs) == 3

    def test_load_logs_for_task_empty(self, tmp_storage):
        logs = tmp_storage.load_logs_for_task("nonexistent-task")
        assert logs == []

    def test_save_and_load_summary(self, tmp_storage):
        run_id = "run-test-001"
        summary = {
            "run_id": run_id,
            "total_tasks": 3,
            "tasks_done": 2,
            "task_results": [],
        }
        tmp_storage.save_summary(run_id, summary)
        loaded = tmp_storage.load_summary(run_id)
        assert loaded is not None
        assert loaded["run_id"] == run_id
        assert loaded["total_tasks"] == 3

    def test_load_nonexistent_summary(self, tmp_storage):
        result = tmp_storage.load_summary("nonexistent-run")
        assert result is None

    def test_directories_created_automatically(self, tmp_path):
        storage = LocalStorage(base_path=str(tmp_path / "new_runs"))
        assert (tmp_path / "new_runs" / "tasks").exists()
        assert (tmp_path / "new_runs" / "logs").exists()
        assert (tmp_path / "new_runs" / "summaries").exists()
