import json
from typing import Optional
from src.agents.base import BaseAgentClient, AgentResponse
from src.models.log_entry import AgentRole


class MockCoderAgentClient(BaseAgentClient):
    def __init__(self, system_prompt: str = ""):
        super().__init__(role=AgentRole.CODER, system_prompt=system_prompt)

    def call(self, prompt: str, context: Optional[dict] = None) -> AgentResponse:
        response = {
            "implementation_log": (
                "Implemented the feature according to the specification. "
                "Created data models with Pydantic validation, implemented business logic, "
                "added API endpoints, and wrote comprehensive unit tests."
            ),
            "files_modified": [
                "src/feature/models.py",
                "src/feature/service.py",
                "src/feature/api.py",
                "tests/test_feature.py",
            ],
            "success": True,
        }
        return AgentResponse(raw=json.dumps(response), role=self.role, success=True)
