"""
Vibe Coding Agent Orchestrator
Configuration management – reads from environment variables with sensible defaults.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    # LLM provider settings
    openai_api_key: str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))
    openai_base_url: str = field(
        default_factory=lambda: os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )
    model: str = field(default_factory=lambda: os.environ.get("VIBE_MODEL", "gpt-4o"))
    temperature: float = field(
        default_factory=lambda: float(os.environ.get("VIBE_TEMPERATURE", "0.2"))
    )
    max_tokens: int = field(
        default_factory=lambda: int(os.environ.get("VIBE_MAX_TOKENS", "4096"))
    )

    # Pipeline settings
    max_iterations: int = field(
        default_factory=lambda: int(os.environ.get("VIBE_MAX_ITERATIONS", "3"))
    )
    logs_dir: str = field(
        default_factory=lambda: os.environ.get("VIBE_LOGS_DIR", "logs")
    )
    tasks_dir: str = field(
        default_factory=lambda: os.environ.get("VIBE_TASKS_DIR", "tasks")
    )
    state_file: str = field(
        default_factory=lambda: os.environ.get("VIBE_STATE_FILE", "logs/pipeline_state.json")
    )

    def validate(self) -> None:
        """Raise ValueError if required configuration is missing."""
        if not self.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable is not set. "
                "Please set it before running the orchestrator."
            )


_config: Config | None = None


def get_config() -> Config:
    """Return the singleton Config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
