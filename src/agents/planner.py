import json
from typing import Optional
from src.agents.base import BaseAgentClient, AgentResponse
from src.models.log_entry import AgentRole


class MockPlannerAgentClient(BaseAgentClient):
    def __init__(self, system_prompt: str = ""):
        super().__init__(role=AgentRole.PLANNER, system_prompt=system_prompt)

    def call(self, prompt: str, context: Optional[dict] = None) -> AgentResponse:
        response = {
            "spec": (
                "## Implementation Spec\n\n"
                "### Overview\n"
                "Implement the requested feature following best practices.\n\n"
                "### Data Models\n"
                "Define appropriate data models with validation.\n\n"
                "### API Endpoints\n"
                "Expose RESTful endpoints for the feature.\n\n"
                "### Implementation Steps\n"
                "1. Define data models\n"
                "2. Implement business logic\n"
                "3. Add API layer\n"
                "4. Write unit tests\n"
            ),
            "sections": ["Overview", "Data Models", "API Endpoints", "Implementation Steps"],
            "ready_for_coder": True,
        }
        return AgentResponse(raw=json.dumps(response), role=self.role, success=True)
