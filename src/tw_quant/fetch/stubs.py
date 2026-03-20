"""In-memory stubs for raw historical fetch orchestration tests."""

from __future__ import annotations

from copy import deepcopy
from collections import defaultdict
from typing import Any

from src.tw_quant.fetch.models import (
    RawArtifactRecord,
    RawFetchRequest,
    RawFetchResultRecord,
    RetryBackoffPolicy,
)


class InMemoryRawHistoricalProvider:
    """Deterministic in-memory provider with scripted payloads or failures."""

    def __init__(self, scripted_responses: list[dict[str, Any] | Exception]) -> None:
        self._scripted_responses = list(scripted_responses)
        self.calls: list[RawFetchRequest] = []

    def fetch_raw(self, request: RawFetchRequest) -> dict[str, Any]:
        self.calls.append(request)
        if not self._scripted_responses:
            return {}

        next_value = self._scripted_responses.pop(0)
        if isinstance(next_value, Exception):
            raise next_value
        return deepcopy(next_value)


class InMemoryRawArtifactStore:
    """Thread-unsafe in-memory artifact sink for raw payload boundaries."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], RawArtifactRecord] = {}
        self._history: list[RawArtifactRecord] = []

    def save_raw_artifact(self, artifact: RawArtifactRecord) -> None:
        key = (artifact.namespace, artifact.key)
        self._entries[key] = artifact
        self._history.append(artifact)

    def load_raw_artifact(self, namespace: str, key: str) -> RawArtifactRecord | None:
        return self._entries.get((namespace, key))

    def list_saved_artifacts(self) -> list[RawArtifactRecord]:
        return list(self._history)


class InMemoryRawFetchOrchestrator:
    """In-memory orchestration stub with retry/backoff placeholders."""

    def __init__(
        self,
        provider: InMemoryRawHistoricalProvider,
        artifact_store: InMemoryRawArtifactStore,
    ) -> None:
        self._provider = provider
        self._artifact_store = artifact_store
        self._delay_ledger: dict[str, list[float]] = defaultdict(list)

    def run(
        self,
        request: RawFetchRequest,
        policy: RetryBackoffPolicy,
    ) -> RawFetchResultRecord:
        max_attempts = max(policy.max_attempts, 1)

        for attempt in range(1, max_attempts + 1):
            try:
                payload = self._provider.fetch_raw(request)
                artifact = RawArtifactRecord(
                    namespace=request.provider,
                    key=f"{request.dataset}/{request.request_id}",
                    payload=payload,
                    metadata={
                        "dataset": request.dataset,
                        "symbols": tuple(request.symbols),
                        "start": request.start,
                        "end": request.end,
                    },
                )
                self._artifact_store.save_raw_artifact(artifact)
                planned = tuple(self._delay_ledger[request.request_id])
                return RawFetchResultRecord(
                    request_id=request.request_id,
                    outcome="success",
                    attempts=attempt,
                    raw_artifact=artifact,
                    planned_backoff_seconds=planned,
                )
            except Exception as exc:  # pragma: no cover - exercised by tests
                if attempt < max_attempts:
                    delay = _planned_delay_seconds(attempt, policy)
                    self._delay_ledger[request.request_id].append(delay)
                    continue

                planned = tuple(self._delay_ledger[request.request_id])
                return RawFetchResultRecord(
                    request_id=request.request_id,
                    outcome="failure",
                    attempts=attempt,
                    raw_artifact=None,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    planned_backoff_seconds=planned,
                )

        return RawFetchResultRecord(
            request_id=request.request_id,
            outcome="failure",
            attempts=max_attempts,
            raw_artifact=None,
            error_type="RuntimeError",
            error_message="Unexpected orchestration fallthrough.",
        )


def _planned_delay_seconds(attempt: int, policy: RetryBackoffPolicy) -> float:
    index = attempt - 1
    if index < len(policy.backoff_schedule_seconds):
        return policy.backoff_schedule_seconds[index]
    return 0.0
