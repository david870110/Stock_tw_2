"""
Vibe Coding Agent Orchestrator
Base agent – wraps an OpenAI-compatible LLM call.
"""
from __future__ import annotations

from typing import Any

from openai import OpenAI

from orchestrator.config import get_config
from orchestrator.utils import get_logger

logger = get_logger("vibe.agent")


class BaseAgent:
    """
    Thin wrapper around an OpenAI-compatible chat completion call.
    Sub-classes provide a *system_prompt* and call :meth:`chat`.
    """

    name: str = "base"
    system_prompt: str = "You are a helpful assistant."

    def __init__(self) -> None:
        cfg = get_config()
        self._client = OpenAI(
            api_key=cfg.openai_api_key,
            base_url=cfg.openai_base_url,
        )
        self._model = cfg.model
        self._temperature = cfg.temperature
        self._max_tokens = cfg.max_tokens

    def chat(self, user_message: str, **extra_kwargs: Any) -> str:
        """
        Send *user_message* to the LLM with this agent's system prompt.
        Returns the assistant's reply as a plain string.
        """
        logger.debug("[%s] sending prompt (%d chars)", self.name, len(user_message))
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_message},
            ],
            **extra_kwargs,
        )
        reply = response.choices[0].message.content or ""
        logger.debug("[%s] received reply (%d chars)", self.name, len(reply))
        return reply
