from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import uuid


class TaskStatus(str, Enum):
    NEW = "NEW"
    MANAGER_PLANNING = "MANAGER_PLANNING"
    WAIT_PLANNER = "WAIT_PLANNER"
    PLANNER_DONE = "PLANNER_DONE"
    MANAGER_SPEC_REVIEW = "MANAGER_SPEC_REVIEW"
    WAIT_CODER = "WAIT_CODER"
    CODER_DONE = "CODER_DONE"
    WAIT_QA = "WAIT_QA"
    QA_DONE = "QA_DONE"
    DONE = "DONE"
    BLOCKED = "BLOCKED"


class QAResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SPEC_GAP = "SPEC_GAP"


class TaskPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.NEW
    iteration_count: int = 0
    current_owner: Optional[str] = None
    parent_task_id: Optional[str] = None
    dependencies: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    artifacts: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_qa_result: Optional[QAResult] = None
    spec: Optional[str] = None
    coder_log: Optional[str] = None
    qa_log: Optional[str] = None

    def transition_to(self, new_status: TaskStatus) -> None:
        self.status = new_status
        self.updated_at = datetime.now(timezone.utc)

    def increment_iteration(self) -> None:
        self.iteration_count += 1
        self.updated_at = datetime.now(timezone.utc)
