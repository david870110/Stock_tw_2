from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import uuid


class AgentRole(str, Enum):
    MANAGER = "MANAGER"
    PLANNER = "PLANNER"
    CODER = "CODER"
    QA = "QA"
    ORCHESTRATOR = "ORCHESTRATOR"


class LogEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    iteration: int
    role: AgentRole
    raw_response: str
    parsed_response: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str  # e.g. "SUCCESS", "PARSE_ERROR", "AGENT_ERROR"
    error_message: Optional[str] = None
