"""Contract tests for the stock selection pipeline (T12)."""

from datetime import date

import pytest

from src.tw_quant.schema.models import SelectionRecord, SignalRecord
from src.tw_quant.selection import SelectionConfig, SelectionPipeline
from src.tw_quant.selection.pipeline import (
    ConfiguredSelector,
    WeightedRankingModel,
    filter_signals,
    rank_signals,
    select_top,
)


@pytest.fixture
def as_of() -> date:
    return date(2026, 1, 15)


@pytest.fixture
def sample_signals() -> list[SignalRecord]:
    return [
        SignalRecord("2330.TW", date(2026, 1, 15), "momentum", 0.9),
        SignalRecord("2317.TW", date(2026, 1, 15), "value", 0.7),
        SignalRecord("2454.TW", date(2026, 1, 15), "momentum", 0.4),
        SignalRecord("2412.TW", date(2026, 1, 15), "momentum", 0.2),
    ]


# ── Pipeline contract tests ────────────────────────────────────────────────


def test_pipeline_accepts_signal_list_returns_selection_list(
    sample_signals: list[SignalRecord], as_of: date
) -> None:
    result = SelectionPipeline().run(sample_signals, as_of)
    assert isinstance(result, list)
    assert all(isinstance(r, SelectionRecord) for r in result)


def test_pipeline_output_records_have_required_fields(
    sample_signals: list[SignalRecord], as_of: date
) -> None:
    result = SelectionPipeline().run(sample_signals, as_of)
    for r in result:
        assert r.symbol
        assert r.timestamp is not None
        assert r.rank >= 1
        assert r.weight > 0.0


def test_pipeline_empty_input_returns_empty(as_of: date) -> None:
    assert SelectionPipeline().run([], as_of) == []


def test_pipeline_top_n_limits_output(
    sample_signals: list[SignalRecord], as_of: date
) -> None:
    config = SelectionConfig(top_n=2)
    result = SelectionPipeline(config).run(sample_signals, as_of)
    assert len(result) <= 2


def test_pipeline_rank_is_sequential(
    sample_signals: list[SignalRecord], as_of: date
) -> None:
    config = SelectionConfig(top_n=3)
    result = SelectionPipeline(config).run(sample_signals, as_of)
    assert [r.rank for r in result] == list(range(1, len(result) + 1))


def test_pipeline_weight_sum_equals_one(
    sample_signals: list[SignalRecord], as_of: date
) -> None:
    result = SelectionPipeline(SelectionConfig(top_n=4)).run(sample_signals, as_of)
    assert abs(sum(r.weight for r in result) - 1.0) < 1e-9


# ── Filter stage unit tests ────────────────────────────────────────────────


def test_filter_drops_below_min_score(sample_signals: list[SignalRecord]) -> None:
    config = SelectionConfig(min_score=0.5)
    result = filter_signals(sample_signals, config)
    assert all(s.score >= 0.5 for s in result)


def test_filter_whitelist_drops_excluded_types(
    sample_signals: list[SignalRecord],
) -> None:
    config = SelectionConfig(signal_type_whitelist=["momentum"])
    result = filter_signals(sample_signals, config)
    assert all(s.signal == "momentum" for s in result)


def test_filter_empty_whitelist_keeps_all(sample_signals: list[SignalRecord]) -> None:
    config = SelectionConfig()
    result = filter_signals(sample_signals, config)
    assert len(result) == len(sample_signals)


# ── Rank stage unit tests ──────────────────────────────────────────────────


def test_rank_descending_order(sample_signals: list[SignalRecord]) -> None:
    result = rank_signals(list(sample_signals), SelectionConfig())
    scores = [s.score for s in result]
    assert scores == sorted(scores, reverse=True)


def test_rank_score_weights_applied() -> None:
    signals = [
        SignalRecord("A", date(2026, 1, 15), "m", 0.5, {"vol": 2.0}),
        SignalRecord("B", date(2026, 1, 15), "m", 0.8, {"vol": 0.0}),
    ]
    config = SelectionConfig(score_weights={"vol": 1.0})
    result = rank_signals(signals, config)
    # A: 0.5 + 1.0*2.0 = 2.5; B: 0.8 + 1.0*0.0 = 0.8 → A should rank first
    assert result[0].symbol == "A"


# ── Select stage unit tests ────────────────────────────────────────────────


def test_select_rank_is_one_based(
    sample_signals: list[SignalRecord], as_of: date
) -> None:
    ranked = rank_signals(list(sample_signals), SelectionConfig())
    result = select_top(ranked, SelectionConfig(top_n=3), as_of)
    assert result[0].rank == 1
    assert result[-1].rank == len(result)


def test_select_score_cutoff_applied(
    sample_signals: list[SignalRecord], as_of: date
) -> None:
    config = SelectionConfig(score_cutoff=0.5, top_n=10)
    ranked = rank_signals(list(sample_signals), config)
    result = select_top(ranked, config, as_of)
    # Only 0.9 and 0.7 pass cutoff 0.5 (0.4 and 0.2 are dropped)
    assert len(result) <= 2


def test_select_reason_matches_signal_field(
    sample_signals: list[SignalRecord], as_of: date
) -> None:
    ranked = rank_signals(list(sample_signals), SelectionConfig())
    result = select_top(ranked, SelectionConfig(top_n=2), as_of)
    assert all(r.reason in ("momentum", "value") for r in result)


def test_select_timestamp_matches_as_of(
    sample_signals: list[SignalRecord], as_of: date
) -> None:
    ranked = rank_signals(list(sample_signals), SelectionConfig())
    result = select_top(ranked, SelectionConfig(top_n=2), as_of)
    assert all(r.timestamp == as_of for r in result)


# ── Protocol conformance tests ─────────────────────────────────────────────


def test_weighted_ranking_model_conforms_to_protocol(as_of: date) -> None:
    model = WeightedRankingModel(SelectionConfig())
    signal = SignalRecord("X", date(2026, 1, 15), "m", 0.5)
    result = model.score(signal)
    assert isinstance(result, float)


def test_configured_selector_conforms_to_protocol(
    sample_signals: list[SignalRecord], as_of: date
) -> None:
    selector = ConfiguredSelector(SelectionConfig(top_n=2))
    result = selector.select(sample_signals, as_of)
    assert isinstance(result, list)
    assert all(isinstance(r, SelectionRecord) for r in result)
