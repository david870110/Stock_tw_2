"""System-level MVP validation harness for TW quant workflow contracts."""

from __future__ import annotations

from datetime import date

import pytest

from src.tw_quant.batch.runner import DeterministicBatchRunner
from src.tw_quant.config.models import AppConfig
from src.tw_quant.reporting import (
    ArtifactReportBuilder,
    BacktestMetricsCalculator,
    InMemoryReportingInputResolver,
    SupplementalReportingInputs,
)
from src.tw_quant.schema.models import BacktestResult, FillRecord, PortfolioSnapshot
from src.tw_quant.storage import InMemoryArtifactStore
from src.tw_quant.wiring.container import AppContext, build_app_context


pytestmark = pytest.mark.tw_mvp


def _ok_executor(symbol, strategy_name, start, end, parameters, run_id, artifact_path):
    return BacktestResult(
        run_id=run_id,
        strategy_name=strategy_name,
        start=start,
        end=end,
        metrics={
            "final_nav": 1_050_000.0,
            "total_return": 0.05,
            "max_drawdown": 0.02,
            "win_rate": 0.5,
            "turnover": 0.2,
            "num_trades": 2.0,
            "gross_traded_notional": 200_000.0,
            "closed_trade_count": 1.0,
        },
    )


def test_symbol_rule_accepts_tw_and_two_suffixes() -> None:
    runner = DeterministicBatchRunner(execute_run=_ok_executor)

    ok_result = runner.run_grid(
        parameter_sets=[{"strategy_name": "demo", "parameters": {"k": 1}}],
        symbols=["2330.TW"],
        windows=[("2024-01-01", "2024-01-31")],
    )
    assert ok_result.success_count == 1

    two_result = runner.run_grid(
        parameter_sets=[{"strategy_name": "demo", "parameters": {"k": 1}}],
        symbols=["2330.TWO"],
        windows=[("2024-01-01", "2024-01-31")],
    )
    assert two_result.success_count == 1


def test_window_validation_rejects_start_after_end() -> None:
    runner = DeterministicBatchRunner(execute_run=_ok_executor)

    with pytest.raises(ValueError, match="start must be <= end"):
        runner.run_grid(
            parameter_sets=[{"strategy_name": "demo", "parameters": {"k": 1}}],
            symbols=["2330.TW"],
            windows=[("2024-02-01", "2024-01-31")],
        )


def test_app_context_contract_uses_placeholder_dependencies() -> None:
    context = build_app_context(AppConfig())

    assert isinstance(context, AppContext)
    assert context.market_data_provider is None
    assert context.fundamental_data_provider is None
    assert context.corporate_action_provider is None
    assert context.raw_data_store is None
    assert context.canonical_data_store is None
    assert context.artifact_store is None
    assert context.metrics_calculator is None
    assert context.report_builder is None
    assert context.batch_runner is None


def test_missing_app_context_dependency_behavior_is_explicit_attribute_error() -> None:
    context = build_app_context(AppConfig())

    with pytest.raises(AttributeError, match="fetch_ohlcv"):
        context.market_data_provider.fetch_ohlcv(  # type: ignore[union-attr]
            ["2330.TW"],
            "2024-01-01",
            "2024-01-31",
        )


def test_batch_result_contract_exposes_deterministic_workflow_metadata() -> None:
    runner = DeterministicBatchRunner(execute_run=_ok_executor, storage_base="/tmp")

    result = runner.run_grid(
        parameter_sets=[{"strategy_name": "demo", "parameters": {"k": 1}}],
        symbols=["2330.TW"],
        windows=[("2024-01-01", "2024-01-31")],
        batch_label="mvp",
    )

    assert result.run_count == 1
    assert result.success_count == 1
    assert result.failed_count == 0
    assert result.batch_id.startswith("batch_")
    assert result.metadata["batch_label"] == "mvp"
    assert result.metadata["storage_base"] == "/tmp"
    assert result.metadata["planned_runs"] == 1
    assert len(result.run_records) == 1

    record = result.run_records[0]
    assert record.status == "SUCCESS"
    assert record.run_id.startswith("run_")
    assert record.symbol == "2330.TW"
    assert record.strategy_name == "demo"
    assert record.artifact_path.endswith(f"{record.run_id}.json")


def test_batch_failure_contract_retains_error_record_without_aborting_batch() -> None:
    def flaky_executor(symbol, strategy_name, start, end, parameters, run_id, artifact_path):
        if symbol == "2317.TW":
            raise RuntimeError("simulated failure")
        return _ok_executor(symbol, strategy_name, start, end, parameters, run_id, artifact_path)

    runner = DeterministicBatchRunner(execute_run=flaky_executor)

    result = runner.run_grid(
        parameter_sets=[{"strategy_name": "demo", "parameters": {"k": 1}}],
        symbols=["2330.TW", "2317.TW"],
        windows=[("2024-01-01", "2024-01-31")],
    )

    assert result.run_count == 2
    assert result.success_count == 1
    assert result.failed_count == 1
    assert len(result.results) == 1
    assert len(result.run_records) == 2

    failed = next(item for item in result.run_records if item.status == "FAILED")
    assert failed.symbol == "2317.TW"
    assert failed.error_message == "simulated failure"


def test_reporting_builder_accepts_backtest_result_shape_from_batch_workflow() -> None:
    runner = DeterministicBatchRunner(execute_run=_ok_executor)
    batch = runner.run_grid(
        parameter_sets=[{"strategy_name": "demo", "parameters": {"k": 1}}],
        symbols=["2330.TW"],
        windows=[("2024-01-01", "2024-01-31")],
    )
    result = batch.results[0]

    resolver = InMemoryReportingInputResolver()
    resolver.register(
        result.run_id,
        SupplementalReportingInputs(
            fills=[
                FillRecord(
                    symbol="2330.TW",
                    timestamp=date(2024, 1, 1),
                    side="buy",
                    quantity=1.0,
                    price=100.0,
                    fee=0.0,
                ),
                FillRecord(
                    symbol="2330.TW",
                    timestamp=date(2024, 1, 2),
                    side="sell",
                    quantity=1.0,
                    price=110.0,
                    fee=0.0,
                ),
            ],
            snapshots=[
                PortfolioSnapshot(timestamp=date(2024, 1, 1), cash=900_000.0, nav=1_000_000.0),
                PortfolioSnapshot(timestamp=date(2024, 1, 2), cash=1_010_000.0, nav=1_050_000.0),
            ],
            base_location="/reports",
        ),
    )

    store = InMemoryArtifactStore()
    builder = ArtifactReportBuilder(
        artifact_store=store,
        input_resolver=resolver,
        metrics_calculator=BacktestMetricsCalculator(resolver),
    )

    artifacts = builder.build(result)
    assert len(artifacts) == 8
    assert {item.report_type for item in artifacts} == {
        "summary_json",
        "summary_csv",
        "trades_json",
        "trades_csv",
        "equity_curve_csv",
        "drawdown_csv",
        "strategy_metrics_json",
        "report_markdown",
    }
    assert len(store.list_saved_artifacts()) == 8