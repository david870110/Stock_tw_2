import json
import os
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
from src.models.task import Task
from src.models.log_entry import LogEntry


class LocalStorage:
    def __init__(self, base_path: str = "runs"):
        self.base_path = Path(base_path)
        self.tasks_path = self.base_path / "tasks"
        self.logs_path = self.base_path / "logs"
        self.summaries_path = self.base_path / "summaries"
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        for path in [self.tasks_path, self.logs_path, self.summaries_path]:
            path.mkdir(parents=True, exist_ok=True)

    def save_task(self, task: Task) -> None:
        """Save a task to JSON file."""
        file_path = self.tasks_path / f"{task.id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(task.model_dump(), f, indent=2, default=str)

    def load_task(self, task_id: str) -> Optional[Task]:
        """Load a task by ID from JSON file."""
        file_path = self.tasks_path / f"{task_id}.json"
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Task.model_validate(data)

    def save_log(self, entry: LogEntry) -> None:
        """Save a log entry to a JSON file per task."""
        file_path = self.logs_path / f"{entry.task_id}_{entry.id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(entry.model_dump(), f, indent=2, default=str)

    def load_logs_for_task(self, task_id: str) -> List[LogEntry]:
        """Load all log entries for a specific task."""
        entries = []
        for log_file in self.logs_path.glob(f"{task_id}_*.json"):
            with open(log_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            entries.append(LogEntry.model_validate(data))
        entries.sort(key=lambda e: e.timestamp)
        return entries

    def save_summary(self, run_id: str, summary: Dict[str, Any]) -> None:
        """Save run summary to JSON file."""
        file_path = self.summaries_path / f"{run_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, default=str)

    def load_summary(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Load run summary by run_id."""
        file_path = self.summaries_path / f"{run_id}.json"
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_tasks(self) -> List[str]:
        """List all task IDs stored."""
        return [f.stem for f in self.tasks_path.glob("*.json")]
