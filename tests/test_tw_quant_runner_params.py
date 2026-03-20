"""Tests for backtest parameter parsing normalization in runner."""

from __future__ import annotations

from src.tw_quant.runner import _parse_backtest_params


def test_parse_backtest_params_repairs_malformed_exit_pairs() -> None:
    parsed = _parse_backtest_params(
        "{exits:{stop_loss_pct:0.6,take_profit_pct:1.2,max_holding_days:360}}"
    )

    exits = parsed.get("exits")
    assert isinstance(exits, dict)
    assert exits == {
        "stop_loss_pct": 0.6,
        "take_profit_pct": 1.2,
        "max_holding_days": 360,
    }


def test_parse_backtest_params_keeps_regular_json_unchanged() -> None:
    parsed = _parse_backtest_params(
        '{"exits":{"stop_loss_pct":0.6,"take_profit_pct":1.2,"max_holding_days":360}}'
    )

    exits = parsed.get("exits")
    assert isinstance(exits, dict)
    assert exits["stop_loss_pct"] == 0.6
    assert exits["take_profit_pct"] == 1.2
    assert exits["max_holding_days"] == 360
