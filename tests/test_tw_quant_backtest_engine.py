"""Tests for backtest engine concrete implementations."""

from datetime import date

import pytest

from src.tw_quant.backtest.engine import (
    InMemoryPortfolioBook,
    SimpleExecutionModel,
    SymbolBacktestEngine,
)
from src.tw_quant.schema.models import OHLCVBar, OrderIntent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bar(symbol: str, close: float, dt: date = date(2024, 1, 1)) -> OHLCVBar:
    return OHLCVBar(
        symbol=symbol,
        date=dt,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000.0,
    )


def _make_intent(symbol: str, side: str, qty: float, dt: date = date(2024, 1, 1)) -> OrderIntent:
    return OrderIntent(symbol=symbol, timestamp=dt, side=side, quantity=qty)


# ---------------------------------------------------------------------------
# Test 1: SimpleExecutionModel fills at close price
# ---------------------------------------------------------------------------

def test_simple_execution_model_single_intent():
    dt = date(2024, 1, 1)
    bar = _make_bar("TEST", 100.0, dt)

    def provider(symbol, timestamp):
        return bar

    model = SimpleExecutionModel(data_provider=provider)
    intent = _make_intent("TEST", "buy", 10.0, dt)
    fills = model.execute([intent], dt)

    assert len(fills) == 1
    fill = fills[0]
    assert fill.symbol == "TEST"
    assert fill.price == 100.0
    assert fill.quantity == 10.0
    assert fill.side == "buy"
    assert fill.fee == 0.0


# ---------------------------------------------------------------------------
# Test 2: None bar produces no fill
# ---------------------------------------------------------------------------

def test_simple_execution_model_no_bar_produces_no_fill():
    def provider(symbol, timestamp):
        return None

    model = SimpleExecutionModel(data_provider=provider)
    intent = _make_intent("MISSING", "buy", 5.0)
    fills = model.execute([intent], date(2024, 1, 1))

    assert fills == []


# ---------------------------------------------------------------------------
# Test 3: InMemoryPortfolioBook NAV after buy
# ---------------------------------------------------------------------------

def test_in_memory_portfolio_book_nav_after_buy():
    book = InMemoryPortfolioBook(initial_cash=10_000.0)

    from src.tw_quant.schema.models import FillRecord

    fill = FillRecord(
        symbol="TEST",
        timestamp=date(2024, 1, 1),
        side="buy",
        quantity=10.0,
        price=100.0,
        fee=0.0,
    )
    book.apply_fills([fill])
    snap = book.snapshot(date(2024, 1, 1))

    assert snap.cash == pytest.approx(9_000.0)
    assert snap.holdings == {"TEST": 10.0}
    assert snap.nav == pytest.approx(10_000.0)


# ---------------------------------------------------------------------------
# Test 4: InMemoryPortfolioBook initial snapshot (no fills)
# ---------------------------------------------------------------------------

def test_in_memory_portfolio_book_initial_snapshot():
    book = InMemoryPortfolioBook(initial_cash=5_000.0)
    snap = book.snapshot(date(2024, 1, 1))

    assert snap.cash == pytest.approx(5_000.0)
    assert snap.holdings == {}
    assert snap.nav == pytest.approx(5_000.0)


# ---------------------------------------------------------------------------
# Test 5: SymbolBacktestEngine three-date window
# ---------------------------------------------------------------------------

def test_symbol_backtest_engine_three_date_window():
    start = date(2024, 1, 1)
    end = date(2024, 1, 3)
    symbol = "AAA"

    bars = {
        date(2024, 1, 1): _make_bar(symbol, 50.0, date(2024, 1, 1)),
        date(2024, 1, 2): _make_bar(symbol, 55.0, date(2024, 1, 2)),
        date(2024, 1, 3): _make_bar(symbol, 60.0, date(2024, 1, 3)),
    }

    def provider(sym, dt):
        from datetime import datetime
        key = dt.date() if isinstance(dt, datetime) else dt
        return bars.get(key)

    # Signal: buy 1 unit only on day 1
    def signal_source(sym, dt):
        from datetime import datetime
        key = dt.date() if isinstance(dt, datetime) else dt
        if key == date(2024, 1, 1):
            return [OrderIntent(symbol=sym, timestamp=dt, side="buy", quantity=1.0)]
        return []

    book = InMemoryPortfolioBook(initial_cash=10_000.0)
    execution_model = SimpleExecutionModel(data_provider=provider)

    engine = SymbolBacktestEngine(
        symbol=symbol,
        data_provider=provider,
        execution_model=execution_model,
        portfolio_book=book,
        signal_source=signal_source,
        run_id="test-run-001",
        strategy_name="test_strategy",
    )

    result = engine.run(start, end)

    assert result.run_id == "test-run-001"
    assert result.strategy_name == "test_strategy"
    assert result.metrics["final_nav"] > 0
    assert result.metrics["num_trades"] >= 0
    assert result.equity_curve_ref is None


def test_symbol_backtest_engine_blocks_reentry_within_cooldown_days():
    start = date(2024, 1, 1)
    end = date(2024, 1, 10)
    symbol = "AAA"

    bars = {
        date(2024, 1, day): _make_bar(symbol, 50.0 + day, date(2024, 1, day))
        for day in range(1, 11)
    }

    def provider(sym, dt):
        return bars.get(dt)

    def signal_source(sym, dt):
        return [OrderIntent(symbol=sym, timestamp=dt, side="buy", quantity=1.0)]

    engine = SymbolBacktestEngine(
        symbol=symbol,
        data_provider=provider,
        execution_model=SimpleExecutionModel(data_provider=provider),
        portfolio_book=InMemoryPortfolioBook(initial_cash=10_000.0),
        signal_source=signal_source,
        run_id="test-run-cooldown-001",
        strategy_name="test_strategy",
        reentry_cooldown_days=30,
    )

    result = engine.run(start, end)

    assert result.metrics["num_trades"] == 1.0
    assert len(result.trades) == 1
    assert result.trades[0]["entry_date"] == "2024-01-01"
