import json
from typing import Optional
from src.agents.base import BaseAgentClient, AgentResponse
from src.models.log_entry import AgentRole


class MockQAAgentClient(BaseAgentClient):
    def __init__(self, system_prompt: str = "", result: str = "PASS"):
        super().__init__(role=AgentRole.QA, system_prompt=system_prompt)
        self._result = result

    def call(self, prompt: str, context: Optional[dict] = None) -> AgentResponse:
        response = {
            "result": self._result,
            "findings": [
                "All acceptance criteria are met",
                "Code follows best practices",
                "Unit tests provide adequate coverage",
                "Documentation is complete",
            ],
            "summary": "Implementation fully complies with the specification and all acceptance criteria are satisfied.",
        }
        return AgentResponse(raw=json.dumps(response), role=self.role, success=True)
