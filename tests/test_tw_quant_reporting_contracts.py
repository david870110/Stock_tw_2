"""Contract tests for reporting outputs and artifact persistence."""

from __future__ import annotations

import csv
import json
from io import StringIO

import pytest

from src.tw_quant.reporting import (
    ArtifactReportBuilder,
    BacktestMetricsCalculator,
    InMemoryReportingInputResolver,
    SupplementalReportingInputs,
)
from src.tw_quant.schema.models import BacktestResult, FillRecord, PortfolioSnapshot
from src.tw_quant.storage import InMemoryArtifactStore


def _sample_result() -> BacktestResult:
    return BacktestResult(
        run_id="run-report-001",
        strategy_name="swing_demo",
        start="2024-01-01",
        end="2024-01-03",
        metrics={
            "final_nav": 10000.0,
            "total_return": 0.0,
            "num_trades": 3.0,
        },
        equity_curve_ref=None,
    )


def _sample_inputs() -> SupplementalReportingInputs:
    return SupplementalReportingInputs(
        fills=[
            FillRecord(
                symbol="2330.TW",
                timestamp="2024-01-01",
                side="buy",
                quantity=10.0,
                price=100.0,
                fee=0.0,
            ),
            FillRecord(
                symbol="2330.TW",
                timestamp="2024-01-02",
                side="sell",
                quantity=5.0,
                price=110.0,
                fee=0.0,
            ),
            FillRecord(
                symbol="2330.TW",
                timestamp="2024-01-03",
                side="sell",
                quantity=5.0,
                price=90.0,
                fee=0.0,
            ),
        ],
        snapshots=[
            PortfolioSnapshot(timestamp="2024-01-01", cash=9000.0, nav=10000.0),
            PortfolioSnapshot(timestamp="2024-01-02", cash=9550.0, nav=10100.0),
            PortfolioSnapshot(timestamp="2024-01-03", cash=10000.0, nav=10000.0),
        ],
        base_location="/artifacts/run-report-001",
        created_at="2026-03-12T10:00:00+00:00",
    )


class CountingMetricsCalculator:
    def __init__(self, calculator: BacktestMetricsCalculator) -> None:
        self._calculator = calculator
        self.calls = 0

    def calculate(self, result: BacktestResult) -> dict[str, object]:
        self.calls += 1
        return self._calculator.calculate(result)


@pytest.fixture
def reporting_bundle() -> dict[str, object]:
    result = _sample_result()
    resolver = InMemoryReportingInputResolver()
    resolver.register(result.run_id, _sample_inputs())
    store = InMemoryArtifactStore()
    counting_calculator = CountingMetricsCalculator(BacktestMetricsCalculator(resolver))
    builder = ArtifactReportBuilder(
        artifact_store=store,
        input_resolver=resolver,
        metrics_calculator=counting_calculator,
    )
    artifacts = builder.build(result)
    return {
        "result": result,
        "resolver": resolver,
        "store": store,
        "artifacts": artifacts,
        "counting_calculator": counting_calculator,
    }


def _artifact_text(reporting_bundle: dict[str, object], report_type: str) -> str:
    store = reporting_bundle["store"]
    artifacts = reporting_bundle["artifacts"]
    artifact = next(item for item in artifacts if item.report_type == report_type)
    content = store.load_artifact(artifact.artifact_id)
    assert content is not None
    return content.decode("utf-8")


def _csv_rows(content: str) -> list[dict[str, str]]:
    return list(csv.DictReader(StringIO(content)))


def test_metrics_calculator_returns_required_normalized_kpis() -> None:
    result = _sample_result()
    resolver = InMemoryReportingInputResolver()
    resolver.register(result.run_id, _sample_inputs())

    metrics = BacktestMetricsCalculator(resolver).calculate(result)

    assert set(metrics.keys()) == {
        "final_nav",
        "total_return",
        "max_drawdown",
        "win_rate",
        "turnover",
        "num_trades",
        "gross_traded_notional",
        "closed_trade_count",
    }
    assert metrics["final_nav"] == pytest.approx(10000.0)
    assert metrics["total_return"] == pytest.approx(0.0)
    assert metrics["max_drawdown"] == pytest.approx(100.0 / 10100.0)
    assert metrics["win_rate"] == pytest.approx(0.5)
    assert metrics["turnover"] == pytest.approx(0.2)
    assert metrics["num_trades"] == 3
    assert metrics["gross_traded_notional"] == pytest.approx(2000.0)
    assert metrics["closed_trade_count"] == 2


def test_report_builder_persists_all_required_artifacts_and_calls_metrics_once(
    reporting_bundle: dict[str, object],
) -> None:
    artifacts = reporting_bundle["artifacts"]
    store = reporting_bundle["store"]
    counting_calculator = reporting_bundle["counting_calculator"]

    assert [artifact.report_type for artifact in artifacts] == [
        "summary_json",
        "summary_csv",
        "trades_json",
        "trades_csv",
        "equity_curve_csv",
        "drawdown_csv",
        "strategy_metrics_json",
        "report_markdown",
    ]
    assert counting_calculator.calls == 1
    assert len(store.list_saved_artifacts()) == 8

    for artifact in artifacts:
        loaded = store.load_artifact(artifact.artifact_id)
        assert loaded is not None
        assert artifact.metadata["run_id"] == "run-report-001"
        assert artifact.metadata["strategy_name"] == "swing_demo"
        assert artifact.metadata["schema_version"] == 0.1
        assert "generated_from" in artifact.metadata


def test_summary_artifacts_follow_required_shape(
    reporting_bundle: dict[str, object],
) -> None:
    summary_json = json.loads(_artifact_text(reporting_bundle, "summary_json"))
    summary_csv_rows = _csv_rows(_artifact_text(reporting_bundle, "summary_csv"))

    assert set(summary_json.keys()) == {
        "schema_version",
        "run_id",
        "strategy_name",
        "start",
        "end",
        "kpis",
        "counts",
        "artifacts",
    }
    assert summary_json["schema_version"] == 0.1
    assert summary_json["run_id"] == "run-report-001"
    assert len(summary_json["artifacts"]) == 8

    assert len(summary_csv_rows) == 1
    row = summary_csv_rows[0]
    assert row["run_id"] == "run-report-001"
    assert row["strategy_name"] == "swing_demo"
    assert row["counts_artifacts"] == "8"
    assert "summary_json:/artifacts/run-report-001/summary.json" in row["artifacts"]


def test_trades_artifacts_follow_required_shape(
    reporting_bundle: dict[str, object],
) -> None:
    trades_json = json.loads(_artifact_text(reporting_bundle, "trades_json"))
    trades_csv_rows = _csv_rows(_artifact_text(reporting_bundle, "trades_csv"))

    assert len(trades_json) == 3
    assert set(trades_json[0].keys()) == {
        "run_id",
        "strategy_name",
        "trade_index",
        "symbol",
        "timestamp",
        "side",
        "quantity",
        "price",
        "fee",
        "gross_notional",
        "signed_notional",
    }
    assert trades_json[0]["signed_notional"] == pytest.approx(-1000.0)
    assert trades_json[1]["signed_notional"] == pytest.approx(550.0)

    assert len(trades_csv_rows) == 3
    assert trades_csv_rows[2]["trade_index"] == "3"
    assert trades_csv_rows[2]["side"] == "sell"


def test_equity_curve_artifact_supports_missing_equity_curve_ref(
    reporting_bundle: dict[str, object],
) -> None:
    result = reporting_bundle["result"]
    equity_rows = _csv_rows(_artifact_text(reporting_bundle, "equity_curve_csv"))
    markdown = _artifact_text(reporting_bundle, "report_markdown")

    assert result.equity_curve_ref is None
    assert len(equity_rows) == 3
    assert set(equity_rows[0].keys()) == {
        "run_id",
        "strategy_name",
        "timestamp",
        "nav",
        "cash",
        "market_value",
    }
    assert markdown.endswith("Note: Reporting can operate when equity_curve_ref is absent.")


def test_drawdown_artifact_follows_required_shape(
    reporting_bundle: dict[str, object],
) -> None:
    drawdown_rows = _csv_rows(_artifact_text(reporting_bundle, "drawdown_csv"))

    assert len(drawdown_rows) == 3
    assert set(drawdown_rows[0].keys()) == {
        "run_id",
        "strategy_name",
        "timestamp",
        "nav",
        "peak_nav",
        "drawdown_amount",
        "drawdown_ratio",
    }
    assert drawdown_rows[1]["peak_nav"] == "10100.0"
    assert drawdown_rows[2]["drawdown_amount"] == "100.0"


def test_strategy_metrics_artifact_follows_required_shape(
    reporting_bundle: dict[str, object],
) -> None:
    strategy_metrics = json.loads(_artifact_text(reporting_bundle, "strategy_metrics_json"))

    assert set(strategy_metrics.keys()) == {"schema_version", "run_id", "strategies"}
    assert strategy_metrics["schema_version"] == 0.1
    assert strategy_metrics["run_id"] == "run-report-001"
    assert len(strategy_metrics["strategies"]) == 1
    strategy_entry = strategy_metrics["strategies"][0]
    assert strategy_entry["strategy_name"] == "swing_demo"
    assert set(strategy_entry["kpis"].keys()) == {
        "final_nav",
        "total_return",
        "max_drawdown",
        "win_rate",
        "turnover",
        "num_trades",
        "gross_traded_notional",
        "closed_trade_count",
    }


def test_missing_input_failure_behavior_is_explicit() -> None:
    result = BacktestResult(
        run_id="run-missing-001",
        strategy_name="broken_report",
        start="2024-01-01",
        end="2024-01-02",
        metrics={},
    )
    resolver = InMemoryReportingInputResolver()
    store = InMemoryArtifactStore()
    builder = ArtifactReportBuilder(store, resolver, BacktestMetricsCalculator(resolver))

    with pytest.raises(ValueError, match="Missing supplemental reporting inputs"):
        builder.build(result)
