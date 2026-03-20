"""Concrete KPI calculation for reporting outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from src.tw_quant.reporting.models import InMemoryReportingInputResolver
from src.tw_quant.schema.models import BacktestResult, FillRecord, PortfolioSnapshot


@dataclass(slots=True)
class _OpenLot:
    side: str
    quantity: float
    price: float
    fee: float


class BacktestMetricsCalculator:
    """Blend result metrics with reporting-side fills and snapshots."""

    def __init__(
        self,
        input_resolver: InMemoryReportingInputResolver | None = None,
    ) -> None:
        self._input_resolver = input_resolver

    def calculate(self, result: BacktestResult) -> dict[str, Any]:
        registered = (
            self._input_resolver.resolve(result.run_id)
            if self._input_resolver is not None
            else None
        )
        fills = list(registered.fills) if registered is not None else []
        snapshots = list(registered.snapshots) if registered is not None else []
        metrics = result.metrics or {}

        gross_traded_notional = self._resolve_metric(
            metrics=metrics,
            key="gross_traded_notional",
            fallback=(self._gross_traded_notional(fills) if fills else None),
        )
        closed_trade_count, win_rate = self._resolve_trade_metrics(metrics, fills)

        final_nav = self._resolve_metric(
            metrics=metrics,
            key="final_nav",
            fallback=(snapshots[-1].nav if snapshots else None),
        )
        total_return = self._resolve_metric(
            metrics=metrics,
            key="total_return",
            fallback=(self._total_return(snapshots) if snapshots else None),
        )
        max_drawdown = self._resolve_metric(
            metrics=metrics,
            key="max_drawdown",
            fallback=(self._max_drawdown(snapshots) if snapshots else None),
        )
        num_trades = self._resolve_metric(
            metrics=metrics,
            key="num_trades",
            fallback=(len(fills) if fills else None),
        )
        turnover = self._resolve_metric(
            metrics=metrics,
            key="turnover",
            fallback=(self._turnover(gross_traded_notional, snapshots) if snapshots else None),
        )

        missing: list[str] = []
        for key, value in (
            ("final_nav", final_nav),
            ("total_return", total_return),
            ("max_drawdown", max_drawdown),
            ("win_rate", win_rate),
            ("turnover", turnover),
            ("num_trades", num_trades),
            ("gross_traded_notional", gross_traded_notional),
            ("closed_trade_count", closed_trade_count),
        ):
            if value is None:
                missing.append(key)

        if missing:
            raise ValueError(
                "Missing reporting inputs for run_id "
                f"{result.run_id!r}; unable to compute: {', '.join(missing)}"
            )

        return {
            "final_nav": float(final_nav),
            "total_return": float(total_return),
            "max_drawdown": float(max_drawdown),
            "win_rate": float(win_rate),
            "turnover": float(turnover),
            "num_trades": int(round(float(num_trades))),
            "gross_traded_notional": float(gross_traded_notional),
            "closed_trade_count": int(round(float(closed_trade_count))),
        }

    def _resolve_trade_metrics(
        self,
        metrics: dict[str, float],
        fills: list[FillRecord],
    ) -> tuple[float | None, float | None]:
        closed_trade_count = self._resolve_metric(
            metrics=metrics,
            key="closed_trade_count",
            fallback=None,
        )
        win_rate = self._resolve_metric(
            metrics=metrics,
            key="win_rate",
            fallback=None,
        )
        if closed_trade_count is not None and win_rate is not None:
            return closed_trade_count, win_rate

        if not fills:
            return closed_trade_count, win_rate

        closed_trade_pnls = self._closed_trade_pnls(fills)
        derived_count = len(closed_trade_pnls)
        derived_win_rate = (
            sum(1 for pnl in closed_trade_pnls if pnl > 0.0) / derived_count
            if derived_count > 0
            else 0.0
        )
        return (
            closed_trade_count if closed_trade_count is not None else float(derived_count),
            win_rate if win_rate is not None else derived_win_rate,
        )

    @staticmethod
    def _resolve_metric(
        metrics: dict[str, float],
        key: str,
        fallback: float | int | None,
    ) -> float | int | None:
        if key in metrics:
            return metrics[key]
        return fallback

    @staticmethod
    def _gross_traded_notional(fills: Iterable[FillRecord]) -> float:
        return sum(abs(fill.quantity * fill.price) for fill in fills)

    @staticmethod
    def _total_return(snapshots: list[PortfolioSnapshot]) -> float:
        if not snapshots:
            return 0.0
        starting_nav = snapshots[0].nav
        denominator = starting_nav if starting_nav != 0.0 else 1.0
        return (snapshots[-1].nav - starting_nav) / denominator

    @staticmethod
    def _max_drawdown(snapshots: list[PortfolioSnapshot]) -> float:
        peak_nav = 0.0
        max_drawdown = 0.0
        for snapshot in snapshots:
            peak_nav = max(peak_nav, snapshot.nav)
            if peak_nav <= 0.0:
                continue
            current = (peak_nav - snapshot.nav) / peak_nav
            max_drawdown = max(max_drawdown, current)
        return max_drawdown

    @staticmethod
    def _turnover(
        gross_traded_notional: float | int | None,
        snapshots: list[PortfolioSnapshot],
    ) -> float | None:
        if gross_traded_notional is None or not snapshots:
            return None
        starting_nav = snapshots[0].nav if snapshots[0].nav != 0.0 else 1.0
        return float(gross_traded_notional) / starting_nav

    def _closed_trade_pnls(self, fills: list[FillRecord]) -> list[float]:
        open_lots: dict[str, list[_OpenLot]] = {}
        closed_pnls: list[float] = []

        for fill in fills:
            lots = open_lots.setdefault(fill.symbol, [])
            remaining = float(fill.quantity)
            close_side = "sell" if fill.side == "buy" else "buy"

            while remaining > 0.0 and lots and lots[0].side == close_side:
                lot = lots[0]
                matched_quantity = min(remaining, lot.quantity)
                open_fee = lot.fee * (matched_quantity / lot.quantity) if lot.quantity else 0.0
                close_fee = fill.fee * (matched_quantity / fill.quantity) if fill.quantity else 0.0

                if lot.side == "buy":
                    pnl = (fill.price - lot.price) * matched_quantity - open_fee - close_fee
                else:
                    pnl = (lot.price - fill.price) * matched_quantity - open_fee - close_fee

                closed_pnls.append(pnl)
                remaining -= matched_quantity
                lot.quantity -= matched_quantity
                lot.fee = max(lot.fee - open_fee, 0.0)
                if lot.quantity <= 0.0:
                    lots.pop(0)

            if remaining > 0.0:
                lots.append(
                    _OpenLot(
                        side=fill.side,
                        quantity=remaining,
                        price=fill.price,
                        fee=fill.fee * (remaining / fill.quantity) if fill.quantity else 0.0,
                    )
                )

        return closed_pnls
