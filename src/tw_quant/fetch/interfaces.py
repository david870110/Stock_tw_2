"""Contracts for raw historical fetch orchestration scaffolding."""

from __future__ import annotations

from typing import Any, Protocol

from src.tw_quant.fetch.models import (
    RawArtifactRecord,
    RawFetchRequest,
    RawFetchResultRecord,
    RetryBackoffPolicy,
)


class RawHistoricalProvider(Protocol):
    def fetch_raw(self, request: RawFetchRequest) -> dict[str, Any]:
        """Fetch vendor-native raw payload for a request."""


class RawArtifactStore(Protocol):
    def save_raw_artifact(self, artifact: RawArtifactRecord) -> None:
        """Persist a raw payload artifact boundary object."""


class RetryBackoffPlanner(Protocol):
    def plan_delay_seconds(self, attempt: int, policy: RetryBackoffPolicy) -> float:
        """Return a placeholder delay value for the next retry attempt."""


class RawFetchOrchestrator(Protocol):
    def run(
        self,
        request: RawFetchRequest,
        policy: RetryBackoffPolicy,
    ) -> RawFetchResultRecord:
        """Run raw fetch flow with retry/backoff placeholders and result records."""
