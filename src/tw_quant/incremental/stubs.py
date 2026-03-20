"""In-memory stubs for deterministic incremental update orchestration."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Mapping

from src.tw_quant.incremental.models import (
    DateWindow,
    IncrementalUpdateRequest,
    IncrementalUpdateResult,
    SymbolWindowPlan,
    WindowAttemptOutcome,
)
from src.tw_quant.storage.cache import LocalCache, build_deterministic_cache_key


class DeterministicMissingWindowComputer:
    """Computes uncovered windows deterministically from covered boundaries."""

    def compute(self, start: date, end: date, covered: tuple[DateWindow, ...]) -> tuple[DateWindow, ...]:
        if start > end:
            return ()

        normalized: list[DateWindow] = []
        for window in sorted(covered, key=lambda w: (w.start, w.end)):
            if window.end < start or window.start > end:
                continue
            clipped = DateWindow(start=max(start, window.start), end=min(end, window.end))
            if not normalized:
                normalized.append(clipped)
                continue
            last = normalized[-1]
            if clipped.start <= last.end + timedelta(days=1):
                merged_end = max(last.end, clipped.end)
                normalized[-1] = DateWindow(start=last.start, end=merged_end)
                continue
            normalized.append(clipped)

        missing: list[DateWindow] = []
        cursor = start
        for window in normalized:
            if cursor < window.start:
                missing.append(DateWindow(start=cursor, end=window.start - timedelta(days=1)))
            cursor = max(cursor, window.end + timedelta(days=1))
        if cursor <= end:
            missing.append(DateWindow(start=cursor, end=end))

        return tuple(missing)


class InMemorySymbolWindowPlanner:
    """Cache-backed planner that computes deterministic per-symbol missing windows."""

    def __init__(self, cache: LocalCache, computer: DeterministicMissingWindowComputer) -> None:
        self._cache = cache
        self._computer = computer

    def plan(self, request: IncrementalUpdateRequest) -> tuple[SymbolWindowPlan, ...]:
        plans: list[SymbolWindowPlan] = []
        for symbol in request.symbols:
            cache_key = build_deterministic_cache_key(
                namespace="twq",
                topic=f"incremental:{request.dataset}",
                parts={"symbol": symbol},
            ).value
            read_result = self._cache.read(cache_key)
            covered = _extract_covered_windows(read_result.envelope.payload if read_result.envelope else None)
            missing = self._computer.compute(request.start, request.end, covered)
            plans.append(SymbolWindowPlan(symbol=symbol, cache_key=cache_key, missing_windows=missing))
        return tuple(plans)


class InMemoryWindowDataFetcher:
    """Scriptable fetcher for deterministic orchestration tests."""

    def __init__(self, scripted: Mapping[str, list[Mapping[str, Any] | Exception]] | None = None) -> None:
        self._scripted = {key: list(values) for key, values in (scripted or {}).items()}
        self.calls: list[tuple[str, DateWindow]] = []

    def fetch(self, symbol: str, window: DateWindow, request: IncrementalUpdateRequest) -> Mapping[str, Any]:
        self.calls.append((symbol, window))
        lane_key = f"{symbol}:{window.start.isoformat()}:{window.end.isoformat()}"
        lane = self._scripted.get(lane_key, [])
        if not lane:
            return {
                "dataset": request.dataset,
                "symbol": symbol,
                "start": window.start.isoformat(),
                "end": window.end.isoformat(),
            }

        next_value = lane.pop(0)
        self._scripted[lane_key] = lane
        if isinstance(next_value, Exception):
            raise next_value
        return dict(next_value)


class InMemoryIncrementalAttemptRunner:
    """Attempts each missing window with bounded retries and records outcomes."""

    def __init__(self, fetcher: InMemoryWindowDataFetcher) -> None:
        self._fetcher = fetcher
        self.attempt_ledger: dict[str, list[int]] = defaultdict(list)

    def run_attempts(
        self,
        plans: tuple[SymbolWindowPlan, ...],
        request: IncrementalUpdateRequest,
    ) -> tuple[WindowAttemptOutcome, ...]:
        outcomes: list[WindowAttemptOutcome] = []
        max_attempts = max(request.max_attempts, 1)

        for plan in plans:
            for window in plan.missing_windows:
                lane_key = _lane_key(plan.symbol, window)
                for attempt in range(1, max_attempts + 1):
                    self.attempt_ledger[lane_key].append(attempt)
                    try:
                        payload = self._fetcher.fetch(plan.symbol, window, request)
                        outcomes.append(
                            WindowAttemptOutcome(
                                symbol=plan.symbol,
                                window=window,
                                outcome="success",
                                attempts=attempt,
                                payload=payload,
                            )
                        )
                        break
                    except Exception as exc:  # pragma: no cover - exercised by tests
                        if attempt < max_attempts:
                            continue
                        outcomes.append(
                            WindowAttemptOutcome(
                                symbol=plan.symbol,
                                window=window,
                                outcome="failure",
                                attempts=attempt,
                                error_type=type(exc).__name__,
                                error_message=str(exc),
                            )
                        )

        return tuple(outcomes)


class InMemoryIncrementalUpdateOrchestrator:
    """Flow orchestrator for deterministic incremental plan-attempt-collect."""

    def __init__(
        self,
        planner: InMemorySymbolWindowPlanner,
        runner: InMemoryIncrementalAttemptRunner,
    ) -> None:
        self._planner = planner
        self._runner = runner

    def run(self, request: IncrementalUpdateRequest) -> IncrementalUpdateResult:
        plans = self._planner.plan(request)
        outcomes = self._runner.run_attempts(plans, request)
        return IncrementalUpdateResult(
            request_id=request.request_id,
            plans=plans,
            outcomes=outcomes,
        )


def _extract_covered_windows(payload: Mapping[str, Any] | None) -> tuple[DateWindow, ...]:
    if not payload:
        return ()

    raw_windows = payload.get("covered_windows", ())
    windows: list[DateWindow] = []
    for item in raw_windows:
        start_raw = item.get("start")
        end_raw = item.get("end")
        if not isinstance(start_raw, str) or not isinstance(end_raw, str):
            continue
        start = date.fromisoformat(start_raw)
        end = date.fromisoformat(end_raw)
        if start <= end:
            windows.append(DateWindow(start=start, end=end))
    return tuple(windows)


def _lane_key(symbol: str, window: DateWindow) -> str:
    return f"{symbol}:{window.start.isoformat()}:{window.end.isoformat()}"
