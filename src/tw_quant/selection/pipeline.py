"""Stock selection pipeline: filter → rank → select."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from src.tw_quant.core.types import DateLike
from src.tw_quant.schema.models import SelectionRecord, SignalRecord
from src.tw_quant.selection.interfaces import RankingModel, Selector


@dataclass(slots=True)
class SelectionConfig:
    min_score: float = 0.0
    signal_type_whitelist: list[str] = field(default_factory=list)
    top_n: int = 10
    score_weights: dict[str, float] = field(default_factory=dict)
    score_cutoff: float | None = None


def _compute_weighted_score(signal: SignalRecord, config: SelectionConfig) -> float:
    if not config.score_weights:
        return signal.score
    return signal.score + sum(
        weight * float(signal.metadata.get(key, 0))
        for key, weight in config.score_weights.items()
    )


def filter_signals(
    signals: Sequence[SignalRecord],
    config: SelectionConfig,
) -> list[SignalRecord]:
    result = []
    for s in signals:
        if s.score < config.min_score:
            continue
        if config.signal_type_whitelist and s.signal not in config.signal_type_whitelist:
            continue
        result.append(s)
    return result


def rank_signals(
    signals: list[SignalRecord],
    config: SelectionConfig,
) -> list[SignalRecord]:
    return sorted(
        signals,
        key=lambda s: _compute_weighted_score(s, config),
        reverse=True,
    )


def select_top(
    ranked: list[SignalRecord],
    config: SelectionConfig,
    as_of: DateLike,
) -> list[SelectionRecord]:
    candidates = ranked
    if config.score_cutoff is not None:
        candidates = [
            s for s in candidates
            if _compute_weighted_score(s, config) >= config.score_cutoff
        ]
    sliced = candidates[: config.top_n]
    if not sliced:
        return []
    weight = 1.0 / len(sliced)
    return [
        SelectionRecord(
            symbol=s.symbol,
            timestamp=as_of,
            rank=idx + 1,
            weight=weight,
            reason=s.signal,
        )
        for idx, s in enumerate(sliced)
    ]


class WeightedRankingModel:
    def __init__(self, config: SelectionConfig) -> None:
        self._config = config

    def score(self, signal: SignalRecord) -> float:
        return _compute_weighted_score(signal, self._config)


class ConfiguredSelector:
    def __init__(self, config: SelectionConfig) -> None:
        self._config = config

    def select(
        self, signals: Sequence[SignalRecord], as_of: DateLike
    ) -> list[SelectionRecord]:
        ranked = rank_signals(list(signals), self._config)
        return select_top(ranked, self._config, as_of)


class SelectionPipeline:
    def __init__(self, config: SelectionConfig | None = None) -> None:
        self._config = config or SelectionConfig()
        self._ranking_model: RankingModel = WeightedRankingModel(self._config)
        self._selector: Selector = ConfiguredSelector(self._config)

    def run(
        self,
        signals: Sequence[SignalRecord],
        as_of: DateLike,
    ) -> list[SelectionRecord]:
        filtered = filter_signals(signals, self._config)
        return self._selector.select(filtered, as_of)
