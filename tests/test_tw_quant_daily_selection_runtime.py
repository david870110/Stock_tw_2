from __future__ import annotations

import json
import csv
from datetime import datetime, timedelta

from src.tw_quant.config.models import AppConfig, DataConfig
from src.tw_quant.data import InMemoryMarketDataProvider
from src.tw_quant.schema.models import OHLCVBar, SignalRecord
from src.tw_quant.selection import SelectionConfig
from src.tw_quant.universe import ListingStatus, UniverseEntry
from src.tw_quant.universe.stub import InMemoryUniverseProvider
from src.tw_quant.workflows import DailySelectionRunner


def test_daily_selection_runner_uses_progress_wrapper_for_multi_symbol_run(monkeypatch, tmp_path) -> None:
    universe = InMemoryUniverseProvider(
        [
            UniverseEntry(
                symbol="2330.TW",
                exchange="TWSE",
                market="main",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2024, 1, 1),
                name="TSMC",
            ),
            UniverseEntry(
                symbol="2317.TW",
                exchange="TWSE",
                market="main",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2024, 1, 1),
                name="HonHai",
            ),
        ]
    )
    provider = InMemoryMarketDataProvider(
        [
            OHLCVBar(symbol="2330.TW", date="2024-01-01", open=10, high=10, low=10, close=10, volume=1000),
            OHLCVBar(symbol="2330.TW", date="2024-01-02", open=10, high=10, low=10, close=11, volume=1000),
            OHLCVBar(symbol="2317.TW", date="2024-01-01", open=20, high=20, low=20, close=20, volume=1000),
            OHLCVBar(symbol="2317.TW", date="2024-01-02", open=20, high=20, low=20, close=21, volume=1000),
        ]
    )
    runner = DailySelectionRunner(
        universe_provider=universe,
        market_data_provider=provider,
        output_base=str(tmp_path),
    )

    calls: dict[str, int | bool] = {}

    class DummyTqdm(list):
        def __init__(self, iterable, desc=None, unit=None, **kwargs):  # noqa: ANN001
            super().__init__(iterable)
            calls["started"] = True

        def close(self) -> None:
            calls["closed"] = True

    def fake_generate_strategy_signals(*, strategy_name, parameters, as_of, by_symbol_history):  # noqa: ANN001
        symbol = next(iter(by_symbol_history.keys()))
        return [
            SignalRecord(
                symbol=symbol,
                timestamp=as_of,
                signal="buy",
                score=1.0,
                metadata={"strategy": strategy_name},
            )
        ]

    monkeypatch.setattr("src.tw_quant.workflows.tqdm", DummyTqdm)
    monkeypatch.setattr("src.tw_quant.workflows._generate_strategy_signals", fake_generate_strategy_signals)

    selections = runner.run(
        as_of="2024-01-02",
        strategy_name="demo",
        lookback_bars=2,
    )

    assert len(selections) == 2
    assert calls.get("started") is True
    assert calls.get("closed") is True


def test_daily_selection_runner_prints_parallel_mode_summary(monkeypatch, tmp_path, capsys) -> None:
    universe = InMemoryUniverseProvider(
        [
            UniverseEntry(
                symbol="2330.TW",
                exchange="TWSE",
                market="main",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2024, 1, 1),
                name="TSMC",
            ),
            UniverseEntry(
                symbol="2317.TW",
                exchange="TWSE",
                market="main",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2024, 1, 1),
                name="HonHai",
            ),
        ]
    )
    provider = InMemoryMarketDataProvider(
        [
            OHLCVBar(symbol="2330.TW", date="2024-01-01", open=10, high=10, low=10, close=10, volume=1000),
            OHLCVBar(symbol="2330.TW", date="2024-01-02", open=10, high=10, low=10, close=11, volume=1000),
            OHLCVBar(symbol="2317.TW", date="2024-01-01", open=20, high=20, low=20, close=20, volume=1000),
            OHLCVBar(symbol="2317.TW", date="2024-01-02", open=20, high=20, low=20, close=21, volume=1000),
        ]
    )
    runner = DailySelectionRunner(
        universe_provider=universe,
        market_data_provider=provider,
        output_base=str(tmp_path),
    )

    monkeypatch.setattr("src.tw_quant.workflows._generate_strategy_signals", lambda **kwargs: [])

    runner.run(
        as_of="2024-01-02",
        strategy_name="demo",
        lookback_bars=2,
        max_workers=4,
        show_progress=True,
        progress_label="Daily Selection 2024-01-02",
    )
    output = capsys.readouterr().out

    assert "mode=process-chunk" in output
    assert "requested_workers=4" in output
    assert "effective_workers=4" in output


def test_daily_selection_runner_uses_requested_processpool_workers(monkeypatch, tmp_path) -> None:
    universe = InMemoryUniverseProvider(
        [
            UniverseEntry(
                symbol="2330.TW",
                exchange="TWSE",
                market="main",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2024, 1, 1),
                name="TSMC",
            ),
            UniverseEntry(
                symbol="2317.TW",
                exchange="TWSE",
                market="main",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2024, 1, 1),
                name="HonHai",
            ),
        ]
    )
    provider = InMemoryMarketDataProvider(
        [
            OHLCVBar(symbol="2330.TW", date="2024-01-01", open=10, high=10, low=10, close=10, volume=1000),
            OHLCVBar(symbol="2330.TW", date="2024-01-02", open=10, high=10, low=10, close=11, volume=1000),
            OHLCVBar(symbol="2317.TW", date="2024-01-01", open=20, high=20, low=20, close=20, volume=1000),
            OHLCVBar(symbol="2317.TW", date="2024-01-02", open=20, high=20, low=20, close=21, volume=1000),
        ]
    )
    runner = DailySelectionRunner(
        universe_provider=universe,
        market_data_provider=provider,
        output_base=str(tmp_path),
    )

    calls: dict[str, int] = {}

    class DummyFuture:
        def __init__(self, value):
            self._value = value

        def result(self):
            return self._value

    class DummyExecutor:
        def __init__(self, max_workers):  # noqa: ANN001
            calls["max_workers"] = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, **kwargs):  # noqa: ANN001
            calls["submitted"] = calls.get("submitted", 0) + 1
            return DummyFuture(fn(**kwargs))

    def fake_as_completed(futures):  # noqa: ANN001
        return list(futures.keys())

    def fake_generate_strategy_signals(*, strategy_name, parameters, as_of, by_symbol_history):  # noqa: ANN001
        symbol = next(iter(by_symbol_history.keys()))
        return [
            SignalRecord(
                symbol=symbol,
                timestamp=as_of,
                signal="buy",
                score=1.0,
                metadata={"strategy": strategy_name},
            )
        ]

    monkeypatch.setattr("src.tw_quant.workflows.ProcessPoolExecutor", DummyExecutor)
    monkeypatch.setattr("src.tw_quant.workflows.as_completed", fake_as_completed)
    monkeypatch.setattr("src.tw_quant.workflows._generate_strategy_signals", fake_generate_strategy_signals)

    selections = runner.run(
        as_of="2024-01-02",
        strategy_name="demo",
        lookback_bars=2,
        max_workers=8,
        show_progress=False,
    )

    assert len(selections) == 2
    assert calls["max_workers"] == 8
    assert calls["submitted"] >= 1


def test_daily_selection_runner_parallel_chunk_path_uses_app_config(monkeypatch, tmp_path) -> None:
    universe = InMemoryUniverseProvider(
        [
            UniverseEntry(
                symbol="2330.TW",
                exchange="TWSE",
                market="main",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2024, 1, 1),
                name="TSMC",
            ),
            UniverseEntry(
                symbol="2317.TW",
                exchange="TWSE",
                market="main",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2024, 1, 1),
                name="HonHai",
            ),
        ]
    )
    provider = InMemoryMarketDataProvider([])
    runner = DailySelectionRunner(
        universe_provider=universe,
        market_data_provider=provider,
        output_base=str(tmp_path),
        app_config=AppConfig(data=DataConfig(wiring_mode="active", market_provider="stub_provider")),
    )

    calls: dict[str, int] = {}

    class DummyFuture:
        def __init__(self, value):
            self._value = value

        def result(self):
            return self._value

    class DummyExecutor:
        def __init__(self, max_workers):  # noqa: ANN001
            calls["max_workers"] = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, **kwargs):  # noqa: ANN001
            calls["submitted"] = calls.get("submitted", 0) + 1
            return DummyFuture(fn(**kwargs))

    def fake_as_completed(futures):  # noqa: ANN001
        return list(futures.keys())

    def fake_chunk_task(**kwargs):  # noqa: ANN001
        calls["chunk_task"] = calls.get("chunk_task", 0) + 1
        return {"signals": [], "symbols_with_history": []}

    monkeypatch.setattr("src.tw_quant.workflows.ProcessPoolExecutor", DummyExecutor)
    monkeypatch.setattr("src.tw_quant.workflows.as_completed", fake_as_completed)
    monkeypatch.setattr("src.tw_quant.workflows._process_daily_selection_chunk_task", fake_chunk_task)

    selections = runner.run(
        as_of="2024-01-02",
        strategy_name="demo",
        lookback_bars=2,
        max_workers=4,
        show_progress=False,
    )

    assert selections == []
    assert calls["max_workers"] == 4
    assert calls["submitted"] >= 1
    assert calls["chunk_task"] >= 1


def test_daily_selection_runner_yfinance_mode_caps_workers_and_uses_thread_chunks(monkeypatch, tmp_path, capsys) -> None:
    universe = InMemoryUniverseProvider(
        [
            UniverseEntry(
                symbol="2330.TW",
                exchange="TWSE",
                market="main",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2024, 1, 1),
                name="TSMC",
            ),
            UniverseEntry(
                symbol="2317.TW",
                exchange="TWSE",
                market="main",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2024, 1, 1),
                name="HonHai",
            ),
        ]
    )
    provider = InMemoryMarketDataProvider([])
    runner = DailySelectionRunner(
        universe_provider=universe,
        market_data_provider=provider,
        output_base=str(tmp_path),
        app_config=AppConfig(data=DataConfig(wiring_mode="active", market_provider="yfinance_ohlcv")),
    )

    calls: dict[str, int] = {}

    class DummyExecutor:
        def __init__(self, max_workers):  # noqa: ANN001
            calls["max_workers"] = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, **kwargs):  # noqa: ANN001
            calls["submitted"] = calls.get("submitted", 0) + 1
            return _DummyResult(fn(**kwargs))

    monkeypatch.setattr("src.tw_quant.workflows.ThreadPoolExecutor", DummyExecutor)
    monkeypatch.setattr("src.tw_quant.workflows.as_completed", lambda futures: list(futures.keys()))
    monkeypatch.setattr("src.tw_quant.workflows._resolve_parallel_chunk_size", lambda **kwargs: 2)
    monkeypatch.setattr("src.tw_quant.workflows._resolve_parallel_chunk_size", lambda **kwargs: 2)
    monkeypatch.setattr("src.tw_quant.workflows._resolve_parallel_chunk_size", lambda **kwargs: 2)
    monkeypatch.setattr(
        "src.tw_quant.workflows._process_daily_selection_chunk_with_provider_task",
        lambda **kwargs: {"signals": [], "symbols_with_history": []},
    )

    runner.run(
        as_of="2024-01-02",
        strategy_name="demo",
        lookback_bars=2,
        max_workers=20,
        show_progress=True,
        progress_label="Daily Selection 2024-01-02",
    )
    output = capsys.readouterr().out

    assert "mode=thread-chunk-yfinance" in output
    assert "requested_workers=20" in output
    assert "effective_workers=8" in output
    assert calls["max_workers"] == 8


def test_daily_selection_runner_yfinance_recovers_missing_symbols_and_persists_diagnostics(monkeypatch, tmp_path) -> None:
    universe = InMemoryUniverseProvider(
        [
            UniverseEntry(
                symbol="2330.TW",
                exchange="TWSE",
                market="main",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2024, 1, 1),
                name="TSMC",
            ),
            UniverseEntry(
                symbol="2317.TW",
                exchange="TWSE",
                market="main",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2024, 1, 1),
                name="HonHai",
            ),
        ]
    )

    class FlakyProvider:
        def __init__(self) -> None:
            self.calls = 0

        def fetch_ohlcv(self, symbols, start, end):  # noqa: ANN001
            self.calls += 1
            if self.calls == 1:
                return [
                    OHLCVBar(symbol="2330.TW", date="2024-01-01", open=10, high=10, low=10, close=10, volume=1000),
                    OHLCVBar(symbol="2330.TW", date="2024-01-02", open=10, high=10, low=10, close=11, volume=1000),
                ]
            return [
                OHLCVBar(symbol="2317.TW", date="2024-01-01", open=20, high=20, low=20, close=20, volume=1000),
                OHLCVBar(symbol="2317.TW", date="2024-01-02", open=20, high=20, low=20, close=21, volume=1000),
            ]

    provider = FlakyProvider()
    runner = DailySelectionRunner(
        universe_provider=universe,
        market_data_provider=provider,
        output_base=str(tmp_path),
        app_config=AppConfig(data=DataConfig(wiring_mode="active", market_provider="yfinance_ohlcv")),
    )

    class DummyExecutor:
        def __init__(self, max_workers):  # noqa: ANN001
            self._max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, **kwargs):  # noqa: ANN001
            return _DummyResult(fn(**kwargs))

    monkeypatch.setattr("src.tw_quant.workflows.ThreadPoolExecutor", DummyExecutor)
    monkeypatch.setattr("src.tw_quant.workflows.as_completed", lambda futures: list(futures.keys()))
    monkeypatch.setattr("src.tw_quant.workflows._resolve_parallel_chunk_size", lambda **kwargs: 2)

    def fake_generate_strategy_signals(*, strategy_name, parameters, as_of, by_symbol_history):  # noqa: ANN001
        symbol = next(iter(by_symbol_history.keys()))
        return [
            SignalRecord(
                symbol=symbol,
                timestamp=as_of,
                signal="buy",
                score=1.0,
                metadata={"strategy": strategy_name},
            )
        ]

    monkeypatch.setattr("src.tw_quant.workflows._generate_strategy_signals", fake_generate_strategy_signals)

    selections = runner.run(
        as_of="2024-01-02",
        strategy_name="demo",
        lookback_bars=2,
        max_workers=8,
        show_progress=False,
    )

    assert len(selections) == 2
    assert provider.calls >= 2

    payload_path = tmp_path / "tw_quant" / "daily_selection" / "2024-01-02" / "demo.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert payload["universe_size"] == 2
    assert payload["symbols_with_history_count"] == 2
    assert payload["missing_history_count"] == 0
    assert payload["buy_signal_count"] == 2
    assert payload["selections"][0]["criteria"]["strategy"] == "demo"

    csv_path = tmp_path / "tw_quant" / "daily_selection" / "2024-01-02" / "demo.csv"
    csv_text = csv_path.read_text(encoding="utf-8")
    png_path = csv_path.with_suffix(".png")
    assert "criteria_json" not in csv_text
    assert "stock_name" in csv_text
    assert "TSMC" in csv_text
    assert "criteria_strategy" in csv_text
    assert png_path.exists()
    assert png_path.stat().st_size > 0


class _DummyResult:
    def __init__(self, value):
        self._value = value

    def result(self):
        return self._value


def test_daily_selection_qizhang_csv_includes_detailed_thresholds_and_values(tmp_path) -> None:
    universe = InMemoryUniverseProvider(
        [
            UniverseEntry(
                symbol="8299.TW",
                exchange="TWSE",
                market="main",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2024, 1, 1),
                name="Phison",
            ),
        ]
    )
    start = datetime(2024, 1, 1)
    entries: list[OHLCVBar] = []
    for i in range(80):
        open_price = 100.0 + i * 0.1
        close_price = open_price + 0.3
        high_price = close_price + 0.2
        low_price = open_price - 0.2
        volume = 1000.0
        if i == 79:
            previous_close = entries[-1].close
            open_price = previous_close * 1.01
            close_price = previous_close * 1.08
            high_price = close_price
            low_price = previous_close * 1.005
            volume = 2200.0
        entries.append(
            OHLCVBar(
                symbol="8299.TW",
                date=(start + timedelta(days=i)).date().isoformat(),
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume,
            )
        )

    provider = InMemoryMarketDataProvider(entries)
    runner = DailySelectionRunner(
        universe_provider=universe,
        market_data_provider=provider,
        output_base=str(tmp_path),
    )

    selections = runner.run(
        as_of="2024-03-20",
        strategy_name="qizhang_selection_strategy",
        lookback_bars=80,
        show_progress=False,
    )

    assert len(selections) == 1

    payload_path = tmp_path / "tw_quant" / "daily_selection" / "2024-03-20" / "qizhang_selection_strategy.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert payload["selections"][0]["criteria"]["indicator"] == "qizhang_signal"
    assert payload["selections"][0]["criteria"]["selected_setup"] == "sig_explosive"

    csv_path = tmp_path / "tw_quant" / "daily_selection" / "2024-03-20" / "qizhang_selection_strategy.csv"
    csv_text = csv_path.read_text(encoding="utf-8")
    png_path = csv_path.with_suffix(".png")
    assert "criteria_json" not in csv_text
    assert "stock_name" in csv_text
    assert "Phison" in csv_text
    assert "criteria_selected_setup" in csv_text
    assert "criteria_price_change_pct" in csv_text
    assert "criteria_indicator" in csv_text
    assert "criteria_check_sig_explosive_price_change_pct" in csv_text
    assert "qizhang_signal" in csv_text
    assert "threshold_sig_explosive_price_change_pct_min" in csv_text
    assert png_path.exists()
    assert png_path.stat().st_size > 0


def test_daily_selection_csv_writes_all_buy_signals_not_only_top_n(tmp_path) -> None:
    universe = InMemoryUniverseProvider(
        [
            UniverseEntry(
                symbol="A001.TW",
                exchange="TWSE",
                market="main",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2024, 1, 1),
                name="A001",
            ),
            UniverseEntry(
                symbol="B001.TW",
                exchange="TWSE",
                market="main",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2024, 1, 1),
                name="B001",
            ),
        ]
    )
    provider = InMemoryMarketDataProvider([])
    runner = DailySelectionRunner(
        universe_provider=universe,
        market_data_provider=provider,
        output_base=str(tmp_path),
    )

    def fake_generate_strategy_signals(*, strategy_name, parameters, as_of, by_symbol_history):  # noqa: ANN001
        symbol = next(iter(by_symbol_history.keys()))
        return [
            SignalRecord(
                symbol=symbol,
                timestamp=as_of,
                signal="buy",
                score=1.0,
                metadata={"strategy": strategy_name, "indicator": "demo_signal"},
            )
        ]

    original_fetch = provider.fetch_ohlcv

    def fake_fetch(symbols, start, end):  # noqa: ANN001
        rows: list[OHLCVBar] = []
        for symbol in symbols:
            rows.append(OHLCVBar(symbol=symbol, date="2024-01-01", open=10, high=10, low=10, close=10, volume=1000))
            rows.append(OHLCVBar(symbol=symbol, date="2024-01-02", open=10, high=11, low=10, close=11, volume=1000))
        return rows

    provider.fetch_ohlcv = fake_fetch  # type: ignore[method-assign]
    try:
        from src.tw_quant import workflows as workflows_module
        original_generate = workflows_module._generate_strategy_signals
        workflows_module._generate_strategy_signals = fake_generate_strategy_signals
        try:
            selections = runner.run(
                as_of="2024-01-02",
                strategy_name="demo",
                lookback_bars=2,
                selection_config=SelectionConfig(signal_type_whitelist=["buy"], min_score=0.0, top_n=1),
                show_progress=False,
            )
        finally:
            workflows_module._generate_strategy_signals = original_generate
    finally:
        provider.fetch_ohlcv = original_fetch  # type: ignore[method-assign]

    assert len(selections) == 1

    csv_path = tmp_path / "tw_quant" / "daily_selection" / "2024-01-02" / "demo.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    png_path = csv_path.with_suffix(".png")

    assert len(rows) == 2
    by_symbol = {row["symbol"]: row for row in rows}
    assert by_symbol["A001.TW"]["stock_name"] == "A001"
    assert by_symbol["B001.TW"]["stock_name"] == "B001"
    assert by_symbol["A001.TW"]["selected"] in {"True", "true", "1"}
    assert by_symbol["B001.TW"]["selected"] in {"False", "false", "0", ""}
    assert png_path.exists()
    assert png_path.stat().st_size > 0
