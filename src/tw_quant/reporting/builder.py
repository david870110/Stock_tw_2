"""Concrete report builder for TW quant backtest artifacts."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timezone
from io import StringIO
from typing import Any

from src.tw_quant.reporting.interfaces import MetricsCalculator
from src.tw_quant.reporting.metrics import BacktestMetricsCalculator
from src.tw_quant.reporting.models import (
    SCHEMA_VERSION,
    InMemoryReportingInputResolver,
    SupplementalReportingInputs,
)
from src.tw_quant.schema.models import BacktestResult, FillRecord, PortfolioSnapshot, ReportArtifact
from src.tw_quant.storage.interfaces import ArtifactStore


class ArtifactReportBuilder:
    """Build and persist inspectable report artifacts for a backtest run."""

    def __init__(
        self,
        artifact_store: ArtifactStore,
        input_resolver: InMemoryReportingInputResolver | None = None,
        metrics_calculator: MetricsCalculator | None = None,
    ) -> None:
        self._artifact_store = artifact_store
        self._input_resolver = input_resolver or InMemoryReportingInputResolver()
        self._metrics_calculator = metrics_calculator or BacktestMetricsCalculator(
            self._input_resolver
        )

    def build(self, result: BacktestResult) -> list[ReportArtifact]:
        supplemental = self._require_inputs(result.run_id)
        fills = list(supplemental.fills)
        snapshots = list(supplemental.snapshots)
        created_at = self._serialize_value(
            supplemental.created_at
            if supplemental.created_at is not None
            else datetime.now(timezone.utc).replace(microsecond=0)
        )

        kpis = self._metrics_calculator.calculate(result)
        trades_rows = self._build_trade_rows(result, fills)
        equity_rows = self._build_equity_rows(result, snapshots)
        drawdown_rows = self._build_drawdown_rows(result, snapshots)

        artifact_specs = [
            {
                "report_type": "summary_json",
                "filename": "summary.json",
                "format": "json",
                "row_count": 1,
                "generated_from": ["result_metrics", "fills", "snapshots", "derived"],
            },
            {
                "report_type": "summary_csv",
                "filename": "summary.csv",
                "format": "csv",
                "row_count": 1,
                "generated_from": ["result_metrics", "fills", "snapshots", "derived"],
            },
            {
                "report_type": "trades_json",
                "filename": "trades.json",
                "format": "json",
                "row_count": len(trades_rows),
                "generated_from": ["fills", "derived"],
            },
            {
                "report_type": "trades_csv",
                "filename": "trades.csv",
                "format": "csv",
                "row_count": len(trades_rows),
                "generated_from": ["fills", "derived"],
            },
            {
                "report_type": "equity_curve_csv",
                "filename": "equity_curve.csv",
                "format": "csv",
                "row_count": len(equity_rows),
                "generated_from": ["snapshots"],
            },
            {
                "report_type": "drawdown_csv",
                "filename": "drawdown.csv",
                "format": "csv",
                "row_count": len(drawdown_rows),
                "generated_from": ["snapshots", "derived"],
            },
            {
                "report_type": "strategy_metrics_json",
                "filename": "strategy_metrics.json",
                "format": "json",
                "row_count": 1,
                "generated_from": ["result_metrics", "fills", "snapshots", "derived"],
            },
            {
                "report_type": "report_markdown",
                "filename": "report.md",
                "format": "markdown",
                "generated_from": ["result_metrics", "fills", "snapshots", "derived"],
            },
        ]

        artifacts = [
            ReportArtifact(
                artifact_id=f"{result.run_id}:{spec['report_type']}",
                report_type=spec["report_type"],
                path=self._build_artifact_path(supplemental, spec["filename"]),
                created_at=created_at,
                metadata=self._build_metadata(result, spec),
            )
            for spec in artifact_specs
        ]

        artifact_inventory = [self._artifact_manifest(artifact) for artifact in artifacts]
        counts = {
            "artifacts": len(artifacts),
            "trades": len(trades_rows),
            "equity_points": len(equity_rows),
            "closed_trades": kpis["closed_trade_count"],
        }

        summary_json_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": result.run_id,
            "strategy_name": result.strategy_name,
            "start": self._serialize_value(result.start),
            "end": self._serialize_value(result.end),
            "kpis": kpis,
            "counts": counts,
            "artifacts": artifact_inventory,
        }

        summary_csv_row = {
            "schema_version": SCHEMA_VERSION,
            "run_id": result.run_id,
            "strategy_name": result.strategy_name,
            "start": self._serialize_value(result.start),
            "end": self._serialize_value(result.end),
            "final_nav": kpis["final_nav"],
            "total_return": kpis["total_return"],
            "max_drawdown": kpis["max_drawdown"],
            "win_rate": kpis["win_rate"],
            "turnover": kpis["turnover"],
            "num_trades": kpis["num_trades"],
            "gross_traded_notional": kpis["gross_traded_notional"],
            "closed_trade_count": kpis["closed_trade_count"],
            "artifacts": "|".join(
                f"{artifact.report_type}:{artifact.path}" for artifact in artifacts
            ),
            "counts_artifacts": counts["artifacts"],
            "counts_trades": counts["trades"],
            "counts_equity_points": counts["equity_points"],
            "counts_closed_trades": counts["closed_trades"],
        }

        strategy_metrics_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": result.run_id,
            "strategies": [
                {
                    "strategy_name": result.strategy_name,
                    "kpis": kpis,
                }
            ],
        }

        markdown_report = self._build_markdown_report(
            result=result,
            kpis=kpis,
            artifacts=artifacts,
        )

        content_by_type = {
            "summary_json": self._json_bytes(summary_json_payload),
            "summary_csv": self._csv_bytes([summary_csv_row]),
            "trades_json": self._json_bytes(trades_rows),
            "trades_csv": self._csv_bytes(trades_rows),
            "equity_curve_csv": self._csv_bytes(equity_rows),
            "drawdown_csv": self._csv_bytes(drawdown_rows),
            "strategy_metrics_json": self._json_bytes(strategy_metrics_payload),
            "report_markdown": markdown_report.encode("utf-8"),
        }

        for artifact in artifacts:
            self._artifact_store.save_artifact(artifact, content_by_type[artifact.report_type])

        return artifacts

    def _require_inputs(self, run_id: str) -> SupplementalReportingInputs:
        supplemental = self._input_resolver.resolve(run_id)
        if supplemental is None:
            raise ValueError(f"Missing supplemental reporting inputs for run_id {run_id!r}")

        missing: list[str] = []
        if not supplemental.fills:
            missing.append("fills")
        if not supplemental.snapshots:
            missing.append("snapshots")
        if missing:
            raise ValueError(
                f"Missing supplemental reporting inputs for run_id {run_id!r}: {', '.join(missing)}"
            )
        return supplemental

    @staticmethod
    def _build_trade_rows(
        result: BacktestResult,
        fills: list[FillRecord],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for index, fill in enumerate(fills, start=1):
            gross_notional = abs(fill.quantity * fill.price)
            signed_notional = gross_notional if fill.side == "sell" else -gross_notional
            rows.append(
                {
                    "run_id": result.run_id,
                    "strategy_name": result.strategy_name,
                    "trade_index": index,
                    "symbol": fill.symbol,
                    "timestamp": ArtifactReportBuilder._serialize_value(fill.timestamp),
                    "side": fill.side,
                    "quantity": fill.quantity,
                    "price": fill.price,
                    "fee": fill.fee,
                    "gross_notional": gross_notional,
                    "signed_notional": signed_notional,
                }
            )
        return rows

    @staticmethod
    def _build_equity_rows(
        result: BacktestResult,
        snapshots: list[PortfolioSnapshot],
    ) -> list[dict[str, Any]]:
        return [
            {
                "run_id": result.run_id,
                "strategy_name": result.strategy_name,
                "timestamp": ArtifactReportBuilder._serialize_value(snapshot.timestamp),
                "nav": snapshot.nav,
                "cash": snapshot.cash,
                "market_value": snapshot.nav - snapshot.cash,
            }
            for snapshot in snapshots
        ]

    @staticmethod
    def _build_drawdown_rows(
        result: BacktestResult,
        snapshots: list[PortfolioSnapshot],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        peak_nav = 0.0
        for snapshot in snapshots:
            peak_nav = max(peak_nav, snapshot.nav)
            drawdown_amount = max(peak_nav - snapshot.nav, 0.0)
            drawdown_ratio = (drawdown_amount / peak_nav) if peak_nav > 0.0 else 0.0
            rows.append(
                {
                    "run_id": result.run_id,
                    "strategy_name": result.strategy_name,
                    "timestamp": ArtifactReportBuilder._serialize_value(snapshot.timestamp),
                    "nav": snapshot.nav,
                    "peak_nav": peak_nav,
                    "drawdown_amount": drawdown_amount,
                    "drawdown_ratio": drawdown_ratio,
                }
            )
        return rows

    @staticmethod
    def _build_metadata(result: BacktestResult, spec: dict[str, Any]) -> dict[str, Any]:
        metadata = {
            "run_id": result.run_id,
            "strategy_name": result.strategy_name,
            "format": spec["format"],
            "schema_version": SCHEMA_VERSION,
            "generated_from": list(spec["generated_from"]),
        }
        if "row_count" in spec:
            metadata["row_count"] = spec["row_count"]
        return metadata

    @staticmethod
    def _build_artifact_path(
        supplemental: SupplementalReportingInputs,
        filename: str,
    ) -> str:
        if supplemental.path_stem:
            return f"{supplemental.path_stem}_{filename}"
        if supplemental.base_location:
            return f"{supplemental.base_location.rstrip('/\\')}/{filename}"
        return filename

    @staticmethod
    def _artifact_manifest(artifact: ReportArtifact) -> dict[str, Any]:
        return {
            "artifact_id": artifact.artifact_id,
            "report_type": artifact.report_type,
            "path": artifact.path,
            "created_at": ArtifactReportBuilder._serialize_value(artifact.created_at),
            "metadata": dict(artifact.metadata),
        }

    @staticmethod
    def _json_bytes(payload: Any) -> bytes:
        return json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8")

    @staticmethod
    def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
        if not rows:
            return b""
        buffer = StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue().encode("utf-8")

    @staticmethod
    def _build_markdown_report(
        result: BacktestResult,
        kpis: dict[str, Any],
        artifacts: list[ReportArtifact],
    ) -> str:
        lines = [
            "# Backtest Report",
            "",
            f"Run ID: {result.run_id}",
            f"Strategy: {result.strategy_name}",
            f"Window: {ArtifactReportBuilder._serialize_value(result.start)} to {ArtifactReportBuilder._serialize_value(result.end)}",
            "",
            "## KPIs",
        ]
        for key, value in kpis.items():
            lines.append(f"- {key}: {value}")
        lines.extend([
            "",
            "## Artifact Inventory",
        ])
        for artifact in artifacts:
            lines.append(f"- {artifact.report_type}: {artifact.path}")
        lines.extend([
            "",
            "Note: Reporting can operate when equity_curve_ref is absent.",
        ])
        return "\n".join(lines)

    @staticmethod
    def _serialize_value(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return value
