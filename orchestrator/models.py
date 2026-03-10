"""
Vibe Coding Agent Orchestrator
Data models for pipeline state management.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional


class PipelineState(str, Enum):
    """States in the Vibe Coding pipeline."""
    INIT = "init"
    TASK_ANALYSIS = "task_analysis"          # Step 1: Manager analyses task
    PLANNER_INSTRUCTION = "planner_instruction"  # Step 2: Manager creates Planner brief
    PLANNING = "planning"                    # Step 3-4: Planner writes spec
    SPEC_REVIEW = "spec_review"              # Step 5: Manager reviews spec
    CODING = "coding"                        # Step 6-7: Coder implements
    QA_TESTING = "qa_testing"               # Step 8: QA tests
    QA_REVIEW = "qa_review"                 # Step 9: Manager reviews QA output
    COMPLETED = "completed"
    FAILED = "failed"


class QAVerdict(str, Enum):
    """Possible QA verdicts."""
    PASS = "PASS"
    FAIL = "FAIL"
    SPEC_UNCLEAR = "SPEC_UNCLEAR"


@dataclass
class Task:
    """Represents a user-submitted task."""
    title: str
    description: str
    id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        return cls(**data)


@dataclass
class PipelineContext:
    """Full state of a pipeline run."""
    task: Optional[Task] = None
    state: PipelineState = PipelineState.INIT
    iteration: int = 0
    max_iterations: int = 3

    # Agent outputs (all stored as markdown text)
    manager_analysis: Optional[str] = None
    planner_instructions: Optional[str] = None
    planner_spec: Optional[str] = None
    approved_spec: Optional[str] = None
    coder_instructions: Optional[str] = None
    coder_output: Optional[str] = None
    qa_instructions: Optional[str] = None
    qa_output: Optional[str] = None
    qa_verdict: Optional[QAVerdict] = None
    pipeline_result: Optional[str] = None

    # History of all agent calls
    history: list = field(default_factory=list)

    def add_history_entry(self, agent: str, step: str, summary: str) -> None:
        """Record a step in the pipeline history."""
        self.history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "iteration": self.iteration,
                "agent": agent,
                "step": step,
                "summary": summary,
            }
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        if self.qa_verdict:
            d["qa_verdict"] = self.qa_verdict.value
        if self.task:
            d["task"] = self.task.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "PipelineContext":
        if "task" in data and data["task"]:
            data["task"] = Task.from_dict(data["task"])
        if "state" in data:
            data["state"] = PipelineState(data["state"])
        if "qa_verdict" in data and data["qa_verdict"]:
            data["qa_verdict"] = QAVerdict(data["qa_verdict"])
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "PipelineContext":
        return cls.from_dict(json.loads(text))
