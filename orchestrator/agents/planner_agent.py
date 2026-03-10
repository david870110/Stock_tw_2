"""
Vibe Coding Agent Orchestrator
Planner Agent – produces a detailed Code Spec from Manager instructions.
"""
from __future__ import annotations

from orchestrator.agents.base_agent import BaseAgent
from orchestrator.models import PipelineContext
from orchestrator.utils import get_logger

logger = get_logger("vibe.planner")


class PlannerAgent(BaseAgent):
    """
    The Planner reads Manager instructions and produces a full Code Spec.
    Steps 3–4 of the pipeline.
    """

    name = "planner"
    system_prompt = (
        "You are the Planner in a Vibe Coding automated development pipeline. "
        "Your role is to produce detailed, developer-ready Code Specs from "
        "high-level instructions. Your spec must be complete enough that a "
        "Coder can implement everything without asking questions. "
        "Be precise, structured, and use concrete examples."
    )

    def create_spec(self, ctx: PipelineContext) -> str:
        """
        Read the Manager's Planner instructions and produce a Code Spec.
        Returns the spec as a markdown string.
        """
        logger.info("[Planner] Steps 3-4 – creating Code Spec")
        prompt = f"""
You have received the following instructions from the Manager:

---
{ctx.planner_instructions}
---

Produce a complete **Code Spec** for the Coder. Your spec must include ALL of the following sections:

## 1. Overview
- What is being built (high-level).
- Goals and explicit non-goals.

## 2. Architecture
- System components and their interactions.
- Directory / file structure (tree format).
- Technology stack with justification.

## 3. Data Models
- All key classes, data structures, or database schemas.
- Field names, types, and validation rules.

## 4. API / Interface Design
- Function signatures, REST endpoints, or CLI commands.
- Parameters, return types, and error conditions.

## 5. Implementation Steps
- Ordered, numbered list of concrete coding tasks.
- Each step should be implementable in a single sitting.

## 6. Dependencies
- External packages/libraries to install.
- Exact version constraints where important.
- Include a `requirements.txt` or equivalent snippet.

## 7. Testing Strategy
- Unit tests to write (file, function, assertion).
- Integration or end-to-end test scenarios.
- Acceptance criteria (what QA will verify).

## 8. Open Questions
- List anything that is still ambiguous after reading the instructions.
- If nothing is unclear, write "None".

Write the complete spec in markdown. Be thorough – the Coder will implement exactly what you describe.
"""
        return self.chat(prompt)
