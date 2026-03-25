from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path

import yaml
from src.tw_quant.batch import DeterministicBatchRunner, build_run_id
import src.tw_quant.data.providers as provider_module
from src.tw_quant.adapters.yfinance_ohlcv import YFinanceRateLimitError
from src.tw_quant.config.models import AppConfig, BacktestConfig, BacktestExitConfig, BacktestStrategyDefaults, DataConfig
from src.tw_quant.data import InMemoryMarketDataProvider, ResilientMarketDataProvider
from src.tw_quant.runner import _load_config
from src.tw_quant.schema.models import OHLCVBar, OrderIntent
from src.tw_quant.universe import ListingStatus, UniverseEntry
from src.tw_quant.universe.providers import normalize_tw_symbol, parse_universe_csv_rows
from src.tw_quant.universe.stub import InMemoryUniverseProvider
from src.tw_quant.wiring.container import build_app_context
from src.tw_quant.workflows import (
    AtomicBacktestExecutor,
    DailySelectionRunner,
    _apply_position_cash_sizing,
    execute_atomic_backtest_run,
)


def test_symbol_normalization_and_validity_contract() -> None:
    assert normalize_tw_symbol("2330") == "2330.TW"
    assert normalize_tw_symbol("2330.tw") == "2330.TW"
    assert normalize_tw_symbol("2330.TWO") == "2330.TWO"
    assert normalize_tw_symbol("  123456.tpe  ") == "123456.TWO"
    assert normalize_tw_symbol("abc") is None


def test_apply_position_cash_sizing_scales_buy_quantity_from_close_price() -> None:
    orders = [OrderIntent(symbol="2330.TW", timestamp="2024-01-02", side="buy", quantity=1.0)]
    current_bar = OHLCVBar(
        symbol="2330.TW",
        date="2024-01-02",
        open=50.0,
        high=50.0,
        low=50.0,
        close=50.0,
        volume=1000.0,
    )

    sized = _apply_position_cash_sizing(
        orders=orders,
        current_bar=current_bar,
        position_cash=100000.0,
    )

    assert len(sized) == 1
    assert sized[0].quantity == 2000.0


def test_apply_position_cash_sizing_prefers_risk_budget_when_stop_distance_provided() -> None:
    orders = [OrderIntent(symbol="2330.TW", timestamp="2024-01-02", side="buy", quantity=1.0)]
    current_bar = OHLCVBar(
        symbol="2330.TW",
        date="2024-01-02",
        open=50.0,
        high=50.0,
        low=50.0,
        close=50.0,
        volume=1000.0,
    )

    sized = _apply_position_cash_sizing(
        orders=orders,
        current_bar=current_bar,
        position_cash=100000.0,
        risk_budget_cash=2000.0,
        stop_distance=10.0,
    )

    assert len(sized) == 1
    assert sized[0].quantity == 200.0


def test_parse_universe_rows_deduplicates_and_filters_invalid() -> None:
    rows = [
        {"symbol": "2330", "exchange": "twse", "market": "main", "listing_status": "listed"},
        {"symbol": "2330.TW", "exchange": "TWSE", "market": "main", "listing_status": "listed"},
        {"symbol": "invalid", "exchange": "TWSE", "market": "main", "listing_status": "listed"},
        {"symbol": "6488", "exchange": "tpex", "market": "otc", "listing_status": "suspended"},
    ]

    entries = parse_universe_csv_rows(rows, updated_at=datetime(2026, 3, 12, 9, 0, 0))
    assert [entry.symbol for entry in entries] == ["2330.TW", "6488.TWO"]
    assert entries[1].listing_status == ListingStatus.SUSPENDED


def test_market_provider_batch_retry_and_date_alignment() -> None:
    calls: list[tuple[str, str, str, float]] = []
    attempts = {"2330.TW": 0, "2317.TW": 0}

    def fetcher(symbol, start, end, timeout):
        calls.append((symbol, str(start), str(end), timeout))
        attempts[symbol] += 1
        if symbol == "2317.TW" and attempts[symbol] == 1:
            raise TimeoutError("transient")
        return [
            {"date": "2024-01-01", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
            {"date": "2025-01-01", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
        ]

    provider = ResilientMarketDataProvider(
        fetcher=fetcher,
        timeout_seconds=3.0,
        max_retries=1,
        batch_size=1,
    )
    bars = provider.fetch_ohlcv(["2330.TW", "2317.TW"], "2024-01-01", "2024-01-31")

    assert len(bars) == 2
    assert all(bar.date == "2024-01-01" for bar in bars)
    assert attempts["2317.TW"] == 2
    assert len(calls) == 3


def test_market_provider_retries_rate_limits_up_to_twenty_attempts(monkeypatch) -> None:
    attempts = {"2330.TW": 0}
    sleeps: list[float] = []

    def fetcher(symbol, start, end, timeout):
        attempts[symbol] += 1
        if attempts[symbol] < 20:
            raise YFinanceRateLimitError("Too Many Requests")
        return [
            {"date": "2024-01-02", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
        ]

    monkeypatch.setattr(provider_module.time, "sleep", lambda seconds: sleeps.append(seconds))

    provider = ResilientMarketDataProvider(
        fetcher=fetcher,
        timeout_seconds=3.0,
        max_retries=2,
        retry_backoff_seconds=0.25,
        batch_size=1,
    )

    bars = provider.fetch_ohlcv(["2330.TW"], "2024-01-01", "2024-01-31")

    assert len(bars) == 1
    assert bars[0].date == "2024-01-02"
    assert attempts["2330.TW"] == 20
    assert sleeps == [300.0] * 19


def test_market_provider_returns_empty_after_twentieth_rate_limit(monkeypatch) -> None:
    attempts = {"2330.TW": 0}
    sleeps: list[float] = []

    def fetcher(symbol, start, end, timeout):
        attempts[symbol] += 1
        raise YFinanceRateLimitError("Too Many Requests")

    monkeypatch.setattr(provider_module.time, "sleep", lambda seconds: sleeps.append(seconds))

    provider = ResilientMarketDataProvider(
        fetcher=fetcher,
        timeout_seconds=3.0,
        max_retries=2,
        retry_backoff_seconds=0.25,
        batch_size=1,
    )

    bars = provider.fetch_ohlcv(["2330.TW"], "2024-01-01", "2024-01-31")

    assert bars == []
    assert attempts["2330.TW"] == 20
    assert sleeps == [300.0] * 19


def test_execute_run_single_and_batch_deterministic_ids(tmp_path: Path) -> None:
    entries = []
    for symbol in ("2330.TW", "2317.TW"):
        entries.extend(
            [
                OHLCVBar(symbol=symbol, date="2024-01-01", open=10, high=10, low=10, close=10, volume=1000),
                OHLCVBar(symbol=symbol, date="2024-01-02", open=10, high=11, low=10, close=10, volume=1000),
                OHLCVBar(symbol=symbol, date="2024-01-03", open=10, high=12, low=10, close=12, volume=1000),
            ]
        )

    provider = InMemoryMarketDataProvider(entries)
    executor = AtomicBacktestExecutor(market_data_provider=provider)
    runner = DeterministicBatchRunner(execute_run=executor, storage_base=str(tmp_path))

    params = {"short": 2, "long": 3}
    run_id = build_run_id("2330.TW", "ma_cross", "2024-01-01", "2024-01-03", params)

    result = runner.run_grid(
        parameter_sets=[{"strategy_name": "ma_cross", "parameters": params}],
        symbols=["2330.TW", "2317.TW"],
        windows=[("2024-01-01", "2024-01-03")],
    )

    assert result.run_count == 2
    assert result.success_count == 2
    first_record = next(record for record in result.run_records if record.symbol == "2330.TW")
    assert first_record.run_id == run_id
    assert Path(first_record.artifact_path).exists()

    batch_summary_path = tmp_path / "tw_quant" / "batch" / result.batch_id / "batch_summary.csv"
    assert batch_summary_path.exists()
    with batch_summary_path.open("r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    # last row is the BATCH_SUMMARY footer; data rows are all others
    data_rows = [r for r in rows if r["run_id"] != "BATCH_SUMMARY"]
    summary_rows = [r for r in rows if r["run_id"] == "BATCH_SUMMARY"]
    assert len(data_rows) == 2
    assert {row["symbol"] for row in data_rows} == {"2330.TW", "2317.TW"}
    assert all("total_return_pct" in row for row in data_rows)
    assert len(summary_rows) == 1
    assert summary_rows[0]["status"] == "SUMMARY"
    assert summary_rows[0]["total_return_pct"] != ""


def test_daily_selection_output_count_weight_timestamp(tmp_path: Path) -> None:
    as_of = date(2024, 1, 4)
    universe = InMemoryUniverseProvider(
        entries=[
            UniverseEntry(
                symbol="2330.TW",
                exchange="TWSE",
                market="main",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2024, 1, 1),
            ),
            UniverseEntry(
                symbol="2317.TW",
                exchange="TWSE",
                market="main",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2024, 1, 1),
            ),
            UniverseEntry(
                symbol="6488.TW",
                exchange="TPEX",
                market="otc",
                listing_status=ListingStatus.DELISTED,
                updated_at=datetime(2024, 1, 1),
            ),
        ]
    )

    entries = [
        OHLCVBar(symbol="2330.TW", date="2024-01-01", open=10, high=10, low=10, close=10, volume=1000),
        OHLCVBar(symbol="2330.TW", date="2024-01-02", open=10, high=10, low=9, close=9, volume=1000),
        OHLCVBar(symbol="2330.TW", date="2024-01-03", open=9, high=9, low=9, close=9, volume=1000),
        OHLCVBar(symbol="2330.TW", date="2024-01-04", open=9, high=12, low=9, close=12, volume=1000),
        OHLCVBar(symbol="2317.TW", date="2024-01-01", open=10, high=10, low=10, close=10, volume=1000),
        OHLCVBar(symbol="2317.TW", date="2024-01-02", open=10, high=10, low=10, close=9, volume=1000),
        OHLCVBar(symbol="2317.TW", date="2024-01-03", open=9, high=9, low=8, close=8, volume=1000),
        OHLCVBar(symbol="2317.TW", date="2024-01-04", open=8, high=8, low=7, close=7, volume=1000),
    ]
    provider = InMemoryMarketDataProvider(entries)
    runner = DailySelectionRunner(
        universe_provider=universe,
        market_data_provider=provider,
        output_base=str(tmp_path),
    )

    selections = runner.run(
        as_of=as_of,
        strategy_name="ma_cross",
        strategy_parameters={"short": 2, "long": 3},
        lookback_bars=4,
    )

    assert len(selections) >= 1
    assert abs(sum(item.weight for item in selections) - 1.0) < 1e-9
    assert all(item.timestamp == as_of for item in selections)

    json_path = tmp_path / "tw_quant" / "daily_selection" / "2024-01-04" / "ma_cross.json"
    csv_path = tmp_path / "tw_quant" / "daily_selection" / "2024-01-04" / "ma_cross.csv"
    assert json_path.exists()
    assert csv_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["selection_count"] == len(selections)
    assert payload["buy_signal_count"] >= len(selections)

    with csv_path.open("r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == payload["buy_signal_count"]


def test_build_app_context_switches_placeholder_and_active_modes(tmp_path: Path) -> None:
    placeholder = build_app_context(AppConfig())
    assert placeholder.market_data_provider is None
    assert placeholder.universe_provider is None

    csv_file = tmp_path / "universe.csv"
    csv_file.write_text("symbol,name,exchange,market,listing_status\n2330,台積電,TWSE,main,listed\n", encoding="utf-8")

    active = build_app_context(
        AppConfig(
            data=DataConfig(
                wiring_mode="active",
                market_provider="stub_market",
                universe_provider="csv_universe",
                universe_csv_path=str(csv_file),
            )
        )
    )
    assert active.market_data_provider is not None
    assert active.universe_provider is not None
    entries = active.universe_provider.get_universe()
    assert entries[0].name == "台積電"


def test_load_config_includes_pullback_exit_defaults() -> None:
    config = _load_config()

    defaults = config.backtest.strategy_defaults["pullback_trend_compression"].exits
    baseline_defaults = config.backtest.strategy_defaults["ma_bullish_stack"].exits

    assert defaults.stop_loss_pct == 0.6
    assert defaults.take_profit_pct == 1.2
    assert defaults.max_holding_days is None
    assert baseline_defaults.stop_loss_pct == 0.6
    assert baseline_defaults.take_profit_pct == 0.6
    assert baseline_defaults.max_holding_days is None


def test_load_config_includes_pullback_optimized_modules_and_exit_defaults() -> None:
    config = _load_config()
    with open("configs/quant/default.yaml", "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    strategy = raw["strategy_examples"]["pullback_trend_120d_optimized"]
    assert strategy["basic"]["min_bars"] == 200
    assert strategy["liquidity"]["liquidity_amt_ma20_min"] == 30000000
    assert strategy["ma"]["ma_short"] == 20
    assert strategy["ma"]["ma20_slope_lookback"] == 5
    assert strategy["ma"]["ma_mid"] == 120
    assert strategy["pullback"]["high_lookback"] == 80
    assert strategy["entry"]["entry_semantics_mode"] == "legacy"
    assert strategy["entry"]["setup_offset_bars"] == 1
    assert strategy["entry"]["reentry_cooldown_days"] == 30
    assert strategy["entry"]["cooldown_apply_on"] == "any_exit"
    assert strategy["entry"]["position_cash"] == 100000.0
    assert strategy["entry"]["risk_budget_pct"] is None
    assert strategy["entry"]["stop_distance_mode"] == "atr_initial_stop"
    assert strategy["entry"]["fallback_position_cash"] == 100000.0
    assert strategy["volume"]["volume_short_ma"] == 10
    assert strategy["volume"]["volume_contract_enabled"] is True
    assert strategy["volume"]["setup_volume_contract_enabled"] is True
    assert strategy["volume"]["setup_volume_contract_ratio_max"] == 1.0
    assert strategy["volume"]["trigger_volume_check_enabled"] is True
    assert strategy["volume"]["trigger_volume_ratio_warn_max"] == 1.2
    assert strategy["volume"]["trigger_volume_hard_block"] is False
    assert strategy["chip"]["enable_chip_filter"] is False
    assert strategy["chip"]["enable_foreign_buy_filter"] is False
    assert strategy["chip"]["enable_investment_trust_filter"] is False
    assert strategy["chip"]["chip_lookback"] == 20
    assert strategy["margin"]["enable_margin_filter"] is False
    assert strategy["margin"]["margin_lookback"] == 20
    assert strategy["margin"]["margin_growth_limit"] == 0.15
    assert strategy["borrow"]["enable_borrow_filter"] is False
    assert strategy["borrow"]["borrow_lookback"] == 20
    assert strategy["borrow"]["borrow_balance_growth_limit"] == 0.15
    assert strategy["price_contraction"]["price_contract_enabled"] is True
    assert strategy["price_contraction"]["range_short_lookback"] == 5
    assert strategy["price_contraction"]["range_long_lookback"] == 20
    assert strategy["price_contraction"]["range_contract_ratio_max"] == 0.7
    assert strategy["close_strength"]["close_strength_enabled"] is True
    assert strategy["close_strength"]["close_vs_5d_high_min"] == 0.95
    assert strategy["close_strength"]["close_position_5d_min"] is None
    assert strategy["short_momentum"]["short_momentum_enabled"] is True
    assert strategy["short_momentum"]["short_momentum_lookback"] == 5
    assert strategy["exit"]["initial_stop_mode"] == "atr"
    assert strategy["exit"]["atr_stop_mult"] == 2.5
    assert strategy["exit"]["trend_break"]["trend_break_below_ma60_days"] == 3
    assert strategy["exit"]["profit_protection"]["mode"] == "percent_drawdown"
    assert strategy["exit"]["profit_protection"]["atr_trailing_enabled"] is False
    assert strategy["exit"]["profit_protection"]["atr_period"] == 14
    assert strategy["exit"]["profit_protection"]["atr_trail_mult"] == 2.0
    assert strategy["exit"]["profit_protection"]["profit_protect_trigger"] == 0.25
    assert strategy["exit"]["profit_protection"]["profit_protect_pullback"] == 0.18
    assert strategy["exit"]["max_hold_days"] == 140

    assert "pullback_trend_compression" in config.backtest.strategy_defaults


def test_execute_atomic_backtest_run_uses_configured_exit_defaults() -> None:
    provider = InMemoryMarketDataProvider(
        [
            OHLCVBar(symbol="2330.TW", date="2024-01-01", open=1.0, high=1.0, low=1.0, close=1.0, volume=1000),
            OHLCVBar(symbol="2330.TW", date="2024-01-02", open=1.0, high=1.0, low=1.0, close=1.0, volume=1000),
            OHLCVBar(symbol="2330.TW", date="2024-01-03", open=1.0, high=1.0, low=1.0, close=1.0, volume=1000),
            OHLCVBar(symbol="2330.TW", date="2024-01-04", open=2.0, high=2.0, low=2.0, close=2.0, volume=1000),
            OHLCVBar(symbol="2330.TW", date="2024-01-05", open=1.5, high=1.5, low=1.5, close=1.5, volume=1000),
        ]
    )

    result = execute_atomic_backtest_run(
        market_data_provider=provider,
        symbol="2330.TW",
        strategy_name="ma_cross",
        start="2024-01-01",
        end="2024-01-05",
        parameters={"short": 2, "long": 3, "exits": {"stop_loss_pct": 0.25}},
        run_id="run-exit-default",
        initial_cash=1_000_000.0,
        backtest_config=BacktestConfig(),
    )

    assert result.metrics["num_trades"] == 2.0
    assert result.metrics["final_nav"] == 999999.5


def test_atomic_backtest_executor_supports_null_exit_overrides_and_no_exit_fallback() -> None:
    entries = [
        OHLCVBar(symbol="2330.TW", date="2024-01-01", open=1.0, high=1.0, low=1.0, close=1.0, volume=1000),
        OHLCVBar(symbol="2330.TW", date="2024-01-02", open=1.0, high=1.0, low=1.0, close=1.0, volume=1000),
        OHLCVBar(symbol="2330.TW", date="2024-01-03", open=1.0, high=1.0, low=1.0, close=1.0, volume=1000),
        OHLCVBar(symbol="2330.TW", date="2024-01-04", open=2.0, high=2.0, low=2.0, close=2.0, volume=1000),
        OHLCVBar(symbol="2330.TW", date="2024-01-05", open=2.0, high=2.0, low=2.0, close=2.0, volume=1000),
    ]
    provider = InMemoryMarketDataProvider(entries)
    executor = AtomicBacktestExecutor(
        market_data_provider=provider,
        backtest_config=BacktestConfig(
            strategy_defaults={
                "ma_cross": BacktestStrategyDefaults(
                    exits=BacktestExitConfig(stop_loss_pct=0.25)
                )
            }
        ),
    )

    disabled_result = executor(
        symbol="2330.TW",
        strategy_name="ma_cross",
        start="2024-01-01",
        end="2024-01-05",
        parameters={"short": 2, "long": 3, "exits": {"stop_loss_pct": None}},
        run_id="run-no-exit",
        artifact_path=str(Path("artifacts") / "tw_quant" / "batch" / "run-no-exit.json"),
    )

    assert disabled_result.metrics["num_trades"] == 1.0
    assert disabled_result.metrics["final_nav"] == 1_000_000.0


def test_execute_atomic_backtest_run_supports_max_holding_days_override() -> None:
    provider = InMemoryMarketDataProvider(
        [
            OHLCVBar(symbol="2330.TW", date="2024-01-01", open=1.0, high=1.0, low=1.0, close=1.0, volume=1000),
            OHLCVBar(symbol="2330.TW", date="2024-01-02", open=1.0, high=1.0, low=1.0, close=1.0, volume=1000),
            OHLCVBar(symbol="2330.TW", date="2024-01-03", open=1.0, high=1.0, low=1.0, close=1.0, volume=1000),
            OHLCVBar(symbol="2330.TW", date="2024-01-04", open=2.0, high=2.0, low=2.0, close=2.0, volume=1000),
            OHLCVBar(symbol="2330.TW", date="2024-01-05", open=2.0, high=2.0, low=2.0, close=2.0, volume=1000),
            OHLCVBar(symbol="2330.TW", date="2024-01-06", open=2.0, high=2.0, low=2.0, close=2.0, volume=1000),
        ]
    )

    result = execute_atomic_backtest_run(
        market_data_provider=provider,
        symbol="2330.TW",
        strategy_name="ma_cross",
        start="2024-01-01",
        end="2024-01-06",
        parameters={"short": 2, "long": 3, "exits": {"max_holding_days": 2}},
        run_id="run-max-holding",
        initial_cash=1_000_000.0,
        backtest_config=BacktestConfig(),
    )

    assert result.metrics["num_trades"] == 2.0
    assert result.metrics["final_nav"] == 1_000_000.0


def test_daily_selection_runner_progress_bar(monkeypatch, tmp_path):
    # Setup universe with multiple symbols
    universe = InMemoryUniverseProvider([
        UniverseEntry(
            symbol="2330.TW",
            exchange="TWSE",
            market="main",
            listing_status=ListingStatus.LISTED,
            updated_at=datetime(2024, 1, 1),
        ),
        UniverseEntry(
            symbol="2317.TW",
            exchange="TWSE",
            market="main",
            listing_status=ListingStatus.LISTED,
            updated_at=datetime(2024, 1, 1),
        ),
    ])
    entries = [
        OHLCVBar(symbol="2330.TW", date="2024-01-01", open=10, high=10, low=10, close=10, volume=1000),
        OHLCVBar(symbol="2330.TW", date="2024-01-02", open=10, high=10, low=9, close=9, volume=1000),
        OHLCVBar(symbol="2317.TW", date="2024-01-01", open=10, high=10, low=10, close=10, volume=1000),
        OHLCVBar(symbol="2317.TW", date="2024-01-02", open=10, high=10, low=10, close=9, volume=1000),
    ]
    provider = InMemoryMarketDataProvider(entries)
    runner = DailySelectionRunner(
        universe_provider=universe,
        market_data_provider=provider,
        output_base=str(tmp_path),
    )
    # Patch tqdm to track calls
    calls = {}
    class DummyTqdm(list):
        def __init__(self, iterable, desc=None, unit=None, **kwargs):
            super().__init__(iterable)
            calls['started'] = True
        def update(self, n):
            calls['updated'] = calls.get('updated', 0) + n
        def close(self):
            calls['closed'] = True
    monkeypatch.setattr("src.tw_quant.workflows.tqdm", DummyTqdm)
    selections = runner.run(
        as_of="2024-01-02",
        strategy_name="ma_cross",
        strategy_parameters={"short": 2, "long": 3},
        lookback_bars=2,
    )
    assert isinstance(selections, list)
    assert calls.get('started')
    assert calls.get('closed')

# Single-symbol run should not show progress bar

def test_daily_selection_runner_no_progress_bar(monkeypatch, tmp_path):
    universe = InMemoryUniverseProvider([
        UniverseEntry(
            symbol="2330.TW",
            exchange="TWSE",
            market="main",
            listing_status=ListingStatus.LISTED,
            updated_at=datetime(2024, 1, 1),
        ),
    ])
    entries = [
        OHLCVBar(symbol="2330.TW", date="2024-01-01", open=10, high=10, low=10, close=10, volume=1000),
        OHLCVBar(symbol="2330.TW", date="2024-01-02", open=10, high=10, low=9, close=9, volume=1000),
    ]
    provider = InMemoryMarketDataProvider(entries)
    runner = DailySelectionRunner(
        universe_provider=universe,
        market_data_provider=provider,
        output_base=str(tmp_path),
    )
    # Patch tqdm to track calls
    calls = {}
    class DummyTqdm(list):
        def __init__(self, iterable, desc=None, unit=None, **kwargs):
            super().__init__(iterable)
            calls['started'] = True
        def update(self, n):
            calls['updated'] = calls.get('updated', 0) + n
        def close(self):
            calls['closed'] = True
    monkeypatch.setattr("src.tw_quant.workflows.tqdm", DummyTqdm)
    selections = runner.run(
        as_of="2024-01-02",
        strategy_name="ma_cross",
        strategy_parameters={"short": 2, "long": 3},
        lookback_bars=2,
    )
    assert isinstance(selections, list)
    assert not calls.get('started')
    assert not calls.get('updated')
    assert not calls.get('closed')
