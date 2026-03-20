"""Contract tests for raw historical fetch orchestration scaffolding."""

from __future__ import annotations

import inspect
from datetime import datetime

import pytest

from src.tw_quant.fetch import (
    InMemoryRawArtifactStore,
    InMemoryRawFetchOrchestrator,
    InMemoryRawHistoricalProvider,
    RawArtifactRecord,
    RawFetchRequest,
    RawFetchResultRecord,
    RetryBackoffPolicy,
)
from src.tw_quant.fetch.interfaces import (
    RawArtifactStore,
    RawFetchOrchestrator,
    RawHistoricalProvider,
    RetryBackoffPlanner,
)
from src.tw_quant.fetch.stubs import _planned_delay_seconds


@pytest.fixture
def sample_request() -> RawFetchRequest:
    return RawFetchRequest(
        provider="stub_vendor",
        dataset="daily_ohlcv",
        symbols=("2330.TW", "2317.TW"),
        start="2024-01-01",
        end="2024-01-31",
        request_id="req-001",
        requested_at=datetime(2026, 3, 11, 9, 0, 0),
        options={"interval": "1d"},
    )


def _assert_has_method(cls: type, method_name: str) -> None:
    assert hasattr(cls, method_name)
    method = getattr(cls, method_name)
    assert callable(method)
    signature = inspect.signature(method)
    assert "self" in signature.parameters


def test_protocol_raw_historical_provider_shape() -> None:
    _assert_has_method(RawHistoricalProvider, "fetch_raw")


def test_protocol_raw_artifact_store_shape() -> None:
    _assert_has_method(RawArtifactStore, "save_raw_artifact")


def test_protocol_retry_backoff_planner_shape() -> None:
    _assert_has_method(RetryBackoffPlanner, "plan_delay_seconds")


def test_protocol_raw_fetch_orchestrator_shape() -> None:
    _assert_has_method(RawFetchOrchestrator, "run")


def test_request_model_fields_are_preserved(sample_request: RawFetchRequest) -> None:
    assert sample_request.provider == "stub_vendor"
    assert sample_request.dataset == "daily_ohlcv"
    assert sample_request.request_id == "req-001"


def test_request_model_is_frozen(sample_request: RawFetchRequest) -> None:
    with pytest.raises(Exception):
        sample_request.provider = "another"  # type: ignore[misc]


def test_retry_policy_defaults() -> None:
    policy = RetryBackoffPolicy()
    assert policy.max_attempts == 1
    assert policy.backoff_schedule_seconds == ()


def test_retry_policy_is_frozen() -> None:
    policy = RetryBackoffPolicy(max_attempts=3)
    with pytest.raises(Exception):
        policy.max_attempts = 2  # type: ignore[misc]


def test_raw_artifact_record_is_frozen() -> None:
    artifact = RawArtifactRecord(namespace="ns", key="k", payload={"x": 1})
    with pytest.raises(Exception):
        artifact.key = "new-key"  # type: ignore[misc]


def test_result_record_supports_success_shape() -> None:
    artifact = RawArtifactRecord(namespace="ns", key="k", payload={"raw": True})
    result = RawFetchResultRecord(
        request_id="req-001",
        outcome="success",
        attempts=1,
        raw_artifact=artifact,
    )
    assert result.outcome == "success"
    assert result.raw_artifact is artifact


def test_result_record_supports_failure_shape() -> None:
    result = RawFetchResultRecord(
        request_id="req-001",
        outcome="failure",
        attempts=2,
        raw_artifact=None,
        error_type="TimeoutError",
        error_message="timed out",
        planned_backoff_seconds=(0.2,),
    )
    assert result.outcome == "failure"
    assert result.error_type == "TimeoutError"


def test_inmemory_provider_no_scripted_responses_returns_empty_payload(
    sample_request: RawFetchRequest,
) -> None:
    provider = InMemoryRawHistoricalProvider([])
    payload = provider.fetch_raw(sample_request)
    assert payload == {}


def test_inmemory_provider_returns_scripted_payload(sample_request: RawFetchRequest) -> None:
    provider = InMemoryRawHistoricalProvider([{"rows": [1, 2, 3]}])
    payload = provider.fetch_raw(sample_request)
    assert payload == {"rows": [1, 2, 3]}


def test_inmemory_provider_raises_scripted_exception(sample_request: RawFetchRequest) -> None:
    provider = InMemoryRawHistoricalProvider([RuntimeError("boom")])
    with pytest.raises(RuntimeError):
        provider.fetch_raw(sample_request)


def test_inmemory_provider_tracks_calls(sample_request: RawFetchRequest) -> None:
    provider = InMemoryRawHistoricalProvider([{"ok": 1}, {"ok": 2}])
    provider.fetch_raw(sample_request)
    provider.fetch_raw(sample_request)
    assert len(provider.calls) == 2


def test_artifact_store_save_and_load_round_trip() -> None:
    store = InMemoryRawArtifactStore()
    artifact = RawArtifactRecord(namespace="vendor", key="dataset/r1", payload={"a": 1})
    store.save_raw_artifact(artifact)
    loaded = store.load_raw_artifact("vendor", "dataset/r1")
    assert loaded == artifact


def test_artifact_store_returns_none_for_missing_key() -> None:
    store = InMemoryRawArtifactStore()
    assert store.load_raw_artifact("missing", "key") is None


def test_artifact_store_overwrites_by_namespace_and_key() -> None:
    store = InMemoryRawArtifactStore()
    first = RawArtifactRecord(namespace="vendor", key="dataset/r1", payload={"a": 1})
    second = RawArtifactRecord(namespace="vendor", key="dataset/r1", payload={"a": 2})
    store.save_raw_artifact(first)
    store.save_raw_artifact(second)
    loaded = store.load_raw_artifact("vendor", "dataset/r1")
    assert loaded == second


def test_artifact_store_history_tracks_each_save() -> None:
    store = InMemoryRawArtifactStore()
    store.save_raw_artifact(RawArtifactRecord(namespace="vendor", key="k1", payload={}))
    store.save_raw_artifact(RawArtifactRecord(namespace="vendor", key="k1", payload={"x": 1}))
    assert len(store.list_saved_artifacts()) == 2


def test_delay_helper_uses_schedule_value() -> None:
    policy = RetryBackoffPolicy(max_attempts=3, backoff_schedule_seconds=(0.1, 0.2))
    assert _planned_delay_seconds(1, policy) == 0.1
    assert _planned_delay_seconds(2, policy) == 0.2


def test_delay_helper_defaults_to_zero_when_schedule_exhausted() -> None:
    policy = RetryBackoffPolicy(max_attempts=3, backoff_schedule_seconds=(0.1,))
    assert _planned_delay_seconds(2, policy) == 0.0


def test_orchestrator_success_single_attempt(sample_request: RawFetchRequest) -> None:
    provider = InMemoryRawHistoricalProvider([{"rows": [1]}])
    store = InMemoryRawArtifactStore()
    orchestrator = InMemoryRawFetchOrchestrator(provider, store)

    result = orchestrator.run(sample_request, RetryBackoffPolicy(max_attempts=1))

    assert result.outcome == "success"
    assert result.attempts == 1
    assert result.error_type is None
    assert result.raw_artifact is not None


def test_orchestrator_persists_raw_artifact_only_on_success(sample_request: RawFetchRequest) -> None:
    provider = InMemoryRawHistoricalProvider([{"rows": [1]}])
    store = InMemoryRawArtifactStore()
    orchestrator = InMemoryRawFetchOrchestrator(provider, store)

    result = orchestrator.run(sample_request, RetryBackoffPolicy(max_attempts=1))

    assert result.raw_artifact is not None
    loaded = store.load_raw_artifact("stub_vendor", "daily_ohlcv/req-001")
    assert loaded is not None
    assert loaded.payload == {"rows": [1]}


def test_orchestrator_populates_raw_artifact_metadata(sample_request: RawFetchRequest) -> None:
    provider = InMemoryRawHistoricalProvider([{"rows": []}])
    store = InMemoryRawArtifactStore()
    orchestrator = InMemoryRawFetchOrchestrator(provider, store)

    result = orchestrator.run(sample_request, RetryBackoffPolicy(max_attempts=1))

    assert result.raw_artifact is not None
    assert result.raw_artifact.metadata["dataset"] == "daily_ohlcv"
    assert result.raw_artifact.metadata["symbols"] == ("2330.TW", "2317.TW")


def test_orchestrator_failure_after_max_attempts(sample_request: RawFetchRequest) -> None:
    provider = InMemoryRawHistoricalProvider([RuntimeError("fail"), RuntimeError("still fail")])
    store = InMemoryRawArtifactStore()
    orchestrator = InMemoryRawFetchOrchestrator(provider, store)

    result = orchestrator.run(
        sample_request,
        RetryBackoffPolicy(max_attempts=2, backoff_schedule_seconds=(0.3,)),
    )

    assert result.outcome == "failure"
    assert result.attempts == 2
    assert result.raw_artifact is None
    assert result.error_type == "RuntimeError"


def test_orchestrator_failure_does_not_persist_artifacts(sample_request: RawFetchRequest) -> None:
    provider = InMemoryRawHistoricalProvider([RuntimeError("fail")])
    store = InMemoryRawArtifactStore()
    orchestrator = InMemoryRawFetchOrchestrator(provider, store)

    result = orchestrator.run(sample_request, RetryBackoffPolicy(max_attempts=1))

    assert result.outcome == "failure"
    assert store.list_saved_artifacts() == []


def test_orchestrator_retries_then_succeeds(sample_request: RawFetchRequest) -> None:
    provider = InMemoryRawHistoricalProvider([RuntimeError("transient"), {"rows": [9]}])
    store = InMemoryRawArtifactStore()
    orchestrator = InMemoryRawFetchOrchestrator(provider, store)

    result = orchestrator.run(
        sample_request,
        RetryBackoffPolicy(max_attempts=2, backoff_schedule_seconds=(0.5,)),
    )

    assert result.outcome == "success"
    assert result.attempts == 2
    assert tuple(result.planned_backoff_seconds) == (0.5,)


def test_orchestrator_uses_zero_delay_placeholder_when_backoff_unspecified(
    sample_request: RawFetchRequest,
) -> None:
    provider = InMemoryRawHistoricalProvider([RuntimeError("transient"), {"rows": [7]}])
    store = InMemoryRawArtifactStore()
    orchestrator = InMemoryRawFetchOrchestrator(provider, store)

    result = orchestrator.run(sample_request, RetryBackoffPolicy(max_attempts=2))

    assert result.outcome == "success"
    assert tuple(result.planned_backoff_seconds) == (0.0,)


def test_orchestrator_records_each_planned_backoff_value(sample_request: RawFetchRequest) -> None:
    provider = InMemoryRawHistoricalProvider(
        [RuntimeError("x"), RuntimeError("y"), RuntimeError("z")]
    )
    store = InMemoryRawArtifactStore()
    orchestrator = InMemoryRawFetchOrchestrator(provider, store)

    result = orchestrator.run(
        sample_request,
        RetryBackoffPolicy(max_attempts=3, backoff_schedule_seconds=(0.1, 0.2)),
    )

    assert result.outcome == "failure"
    assert tuple(result.planned_backoff_seconds) == (0.1, 0.2)


def test_orchestrator_forces_minimum_attempt_count_of_one(sample_request: RawFetchRequest) -> None:
    provider = InMemoryRawHistoricalProvider([{"rows": [1]}])
    store = InMemoryRawArtifactStore()
    orchestrator = InMemoryRawFetchOrchestrator(provider, store)

    result = orchestrator.run(sample_request, RetryBackoffPolicy(max_attempts=0))

    assert result.outcome == "success"
    assert result.attempts == 1


def test_orchestrator_uses_provider_name_as_artifact_namespace(
    sample_request: RawFetchRequest,
) -> None:
    provider = InMemoryRawHistoricalProvider([{"raw": "payload"}])
    store = InMemoryRawArtifactStore()
    orchestrator = InMemoryRawFetchOrchestrator(provider, store)

    result = orchestrator.run(sample_request, RetryBackoffPolicy(max_attempts=1))

    assert result.raw_artifact is not None
    assert result.raw_artifact.namespace == "stub_vendor"


def test_orchestrator_constructs_artifact_key_from_dataset_and_request_id(
    sample_request: RawFetchRequest,
) -> None:
    provider = InMemoryRawHistoricalProvider([{"raw": "payload"}])
    store = InMemoryRawArtifactStore()
    orchestrator = InMemoryRawFetchOrchestrator(provider, store)

    result = orchestrator.run(sample_request, RetryBackoffPolicy(max_attempts=1))

    assert result.raw_artifact is not None
    assert result.raw_artifact.key == "daily_ohlcv/req-001"


def test_orchestrator_provider_payload_is_defensively_copied(
    sample_request: RawFetchRequest,
) -> None:
    payload = {"rows": [1, 2]}
    provider = InMemoryRawHistoricalProvider([payload])
    store = InMemoryRawArtifactStore()
    orchestrator = InMemoryRawFetchOrchestrator(provider, store)

    result = orchestrator.run(sample_request, RetryBackoffPolicy(max_attempts=1))

    payload["rows"].append(3)
    assert result.raw_artifact is not None
    assert result.raw_artifact.payload == {"rows": [1, 2]}


def test_fetch_package_exports_public_api_symbols() -> None:
    import src.tw_quant.fetch as fetch_pkg

    assert hasattr(fetch_pkg, "RawFetchRequest")
    assert hasattr(fetch_pkg, "RetryBackoffPolicy")
    assert hasattr(fetch_pkg, "RawArtifactRecord")
    assert hasattr(fetch_pkg, "RawFetchResultRecord")
    assert hasattr(fetch_pkg, "InMemoryRawHistoricalProvider")
    assert hasattr(fetch_pkg, "InMemoryRawArtifactStore")
    assert hasattr(fetch_pkg, "InMemoryRawFetchOrchestrator")
