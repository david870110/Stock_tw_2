"""Contract tests for incremental update planning and orchestration scaffolding."""

from __future__ import annotations

import inspect
from datetime import date, datetime

import pytest

from src.tw_quant.incremental import (
    DateWindow,
    DeterministicMissingWindowComputer,
    InMemoryIncrementalAttemptRunner,
    InMemoryIncrementalUpdateOrchestrator,
    InMemorySymbolWindowPlanner,
    InMemoryWindowDataFetcher,
    IncrementalUpdateRequest,
    IncrementalUpdateResult,
    SymbolWindowPlan,
    WindowAttemptOutcome,
)
from src.tw_quant.incremental.interfaces import (
    IncrementalAttemptRunner,
    IncrementalUpdateOrchestrator,
    MissingWindowComputer,
    SymbolWindowPlanner,
    WindowDataFetcher,
)
from src.tw_quant.storage import (
    CacheEnvelope,
    CacheVersionMetadata,
    InMemoryLocalCache,
    build_deterministic_cache_key,
)


def _assert_has_method(cls: type, method_name: str) -> None:
    assert hasattr(cls, method_name)
    method = getattr(cls, method_name)
    assert callable(method)
    signature = inspect.signature(method)
    assert "self" in signature.parameters


@pytest.fixture
def sample_request() -> IncrementalUpdateRequest:
    return IncrementalUpdateRequest(
        dataset="daily_ohlcv",
        symbols=("2330.TW", "2317.TW"),
        start=date(2024, 1, 1),
        end=date(2024, 1, 10),
        request_id="inc-001",
        max_attempts=2,
    )


def _cache_envelope_for_covered_windows(
    *,
    key: str,
    covered: tuple[tuple[str, str], ...],
) -> CacheEnvelope:
    return CacheEnvelope(
        key=key,
        payload={"covered_windows": [{"start": start, "end": end} for start, end in covered]},
        version=CacheVersionMetadata(schema_name="incremental", schema_version="1.0.0"),
        created_at=datetime(2026, 3, 11, 12, 0, 0),
    )


def test_protocol_missing_window_computer_shape() -> None:
    _assert_has_method(MissingWindowComputer, "compute")


def test_protocol_symbol_window_planner_shape() -> None:
    _assert_has_method(SymbolWindowPlanner, "plan")


def test_protocol_window_data_fetcher_shape() -> None:
    _assert_has_method(WindowDataFetcher, "fetch")


def test_protocol_incremental_attempt_runner_shape() -> None:
    _assert_has_method(IncrementalAttemptRunner, "run_attempts")


def test_protocol_incremental_update_orchestrator_shape() -> None:
    _assert_has_method(IncrementalUpdateOrchestrator, "run")


def test_missing_window_computer_full_gap_when_no_coverage() -> None:
    computer = DeterministicMissingWindowComputer()
    missing = computer.compute(date(2024, 1, 1), date(2024, 1, 5), covered=())
    assert missing == (DateWindow(date(2024, 1, 1), date(2024, 1, 5)),)


def test_missing_window_computer_splits_head_and_tail_around_coverage() -> None:
    computer = DeterministicMissingWindowComputer()
    missing = computer.compute(
        date(2024, 1, 1),
        date(2024, 1, 10),
        covered=(DateWindow(date(2024, 1, 4), date(2024, 1, 6)),),
    )
    assert missing == (
        DateWindow(date(2024, 1, 1), date(2024, 1, 3)),
        DateWindow(date(2024, 1, 7), date(2024, 1, 10)),
    )


def test_missing_window_computer_merges_overlapping_and_adjacent_windows() -> None:
    computer = DeterministicMissingWindowComputer()
    missing = computer.compute(
        date(2024, 1, 1),
        date(2024, 1, 10),
        covered=(
            DateWindow(date(2024, 1, 3), date(2024, 1, 4)),
            DateWindow(date(2024, 1, 5), date(2024, 1, 5)),
            DateWindow(date(2024, 1, 4), date(2024, 1, 6)),
        ),
    )
    assert missing == (
        DateWindow(date(2024, 1, 1), date(2024, 1, 2)),
        DateWindow(date(2024, 1, 7), date(2024, 1, 10)),
    )


def test_planner_uses_cache_covered_windows_to_compute_missing(sample_request: IncrementalUpdateRequest) -> None:
    cache = InMemoryLocalCache()
    key = build_deterministic_cache_key(
        namespace="twq",
        topic="incremental:daily_ohlcv",
        parts={"symbol": "2330.TW"},
    ).value
    cache.write(
        _cache_envelope_for_covered_windows(
            key=key,
            covered=(("2024-01-01", "2024-01-03"), ("2024-01-07", "2024-01-10")),
        )
    )

    planner = InMemorySymbolWindowPlanner(cache=cache, computer=DeterministicMissingWindowComputer())
    plans = planner.plan(sample_request)

    first_plan = plans[0]
    second_plan = plans[1]
    assert first_plan.symbol == "2330.TW"
    assert first_plan.missing_windows == (DateWindow(date(2024, 1, 4), date(2024, 1, 6)),)
    assert second_plan.symbol == "2317.TW"
    assert second_plan.missing_windows == (DateWindow(date(2024, 1, 1), date(2024, 1, 10)),)


def test_attempt_runner_retries_until_success(sample_request: IncrementalUpdateRequest) -> None:
    window = DateWindow(date(2024, 1, 1), date(2024, 1, 2))
    plans = (SymbolWindowPlan(symbol="2330.TW", cache_key="k", missing_windows=(window,)),)
    fetcher = InMemoryWindowDataFetcher(
        scripted={
            "2330.TW:2024-01-01:2024-01-02": [RuntimeError("temp"), {"rows": [1]}],
        }
    )
    runner = InMemoryIncrementalAttemptRunner(fetcher)

    outcomes = runner.run_attempts(plans=plans, request=sample_request)

    assert outcomes == (
        WindowAttemptOutcome(
            symbol="2330.TW",
            window=window,
            outcome="success",
            attempts=2,
            payload={"rows": [1]},
        ),
    )


def test_attempt_runner_records_failure_after_max_attempts(
    sample_request: IncrementalUpdateRequest,
) -> None:
    window = DateWindow(date(2024, 1, 4), date(2024, 1, 5))
    plans = (SymbolWindowPlan(symbol="2317.TW", cache_key="k2", missing_windows=(window,)),)
    fetcher = InMemoryWindowDataFetcher(
        scripted={
            "2317.TW:2024-01-04:2024-01-05": [RuntimeError("e1"), RuntimeError("e2")],
        }
    )
    runner = InMemoryIncrementalAttemptRunner(fetcher)

    outcomes = runner.run_attempts(plans=plans, request=sample_request)

    assert len(outcomes) == 1
    assert outcomes[0].outcome == "failure"
    assert outcomes[0].attempts == 2
    assert outcomes[0].error_type == "RuntimeError"


def test_orchestrator_runs_plan_attempt_collect(sample_request: IncrementalUpdateRequest) -> None:
    cache = InMemoryLocalCache()
    planner = InMemorySymbolWindowPlanner(cache=cache, computer=DeterministicMissingWindowComputer())
    fetcher = InMemoryWindowDataFetcher()
    runner = InMemoryIncrementalAttemptRunner(fetcher)
    orchestrator = InMemoryIncrementalUpdateOrchestrator(planner, runner)

    result = orchestrator.run(sample_request)

    assert isinstance(result, IncrementalUpdateResult)
    assert result.request_id == "inc-001"
    assert len(result.plans) == 2
    assert len(result.outcomes) == 2
    assert all(outcome.outcome == "success" for outcome in result.outcomes)


def test_orchestrator_returns_empty_outcomes_when_no_missing_windows(
    sample_request: IncrementalUpdateRequest,
) -> None:
    cache = InMemoryLocalCache()
    for symbol in sample_request.symbols:
        key = build_deterministic_cache_key(
            namespace="twq",
            topic="incremental:daily_ohlcv",
            parts={"symbol": symbol},
        ).value
        cache.write(
            _cache_envelope_for_covered_windows(
                key=key,
                covered=(("2024-01-01", "2024-01-10"),),
            )
        )

    planner = InMemorySymbolWindowPlanner(cache=cache, computer=DeterministicMissingWindowComputer())
    runner = InMemoryIncrementalAttemptRunner(InMemoryWindowDataFetcher())
    orchestrator = InMemoryIncrementalUpdateOrchestrator(planner, runner)

    result = orchestrator.run(sample_request)

    assert result.outcomes == ()


def test_incremental_package_exports_public_api_symbols() -> None:
    import src.tw_quant.incremental as incremental_pkg

    assert hasattr(incremental_pkg, "DateWindow")
    assert hasattr(incremental_pkg, "IncrementalUpdateRequest")
    assert hasattr(incremental_pkg, "DeterministicMissingWindowComputer")
    assert hasattr(incremental_pkg, "InMemorySymbolWindowPlanner")
    assert hasattr(incremental_pkg, "InMemoryIncrementalUpdateOrchestrator")


def test_models_are_frozen() -> None:
    window = DateWindow(date(2024, 1, 1), date(2024, 1, 2))
    with pytest.raises(Exception):
        window.start = date(2024, 1, 3)  # type: ignore[misc]
