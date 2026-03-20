import json
from typing import Optional
from src.agents.base import BaseAgentClient, AgentResponse
from src.models.log_entry import AgentRole


class MockManagerAgentClient(BaseAgentClient):
    def __init__(self, system_prompt: str = ""):
        super().__init__(role=AgentRole.MANAGER, system_prompt=system_prompt)

    def call(self, prompt: str, context: Optional[dict] = None) -> AgentResponse:
        response = {
            "tasks": [
                {
                    "title": "Implement requested feature",
                    "description": "Implement the feature as described in the requirement",
                    "priority": "HIGH",
                    "acceptance_criteria": [
                        "Feature is implemented correctly",
                        "Unit tests are written",
                        "Code is documented",
                    ],
                }
            ],
            "decision": "approve_spec",
            "instruction": "Please create a detailed implementation specification for this task.",
        }
        return AgentResponse(raw=json.dumps(response), role=self.role, success=True)
