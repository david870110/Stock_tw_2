from abc import ABC, abstractmethod
from typing import Optional
from src.models.log_entry import AgentRole


class AgentResponse:
    def __init__(self, raw: str, role: AgentRole, success: bool = True, error: Optional[str] = None):
        self.raw = raw
        self.role = role
        self.success = success
        self.error = error


class BaseAgentClient(ABC):
    def __init__(self, role: AgentRole, system_prompt: str = ""):
        self.role = role
        self.system_prompt = system_prompt

    @abstractmethod
    def call(self, prompt: str, context: Optional[dict] = None) -> AgentResponse:
        pass
