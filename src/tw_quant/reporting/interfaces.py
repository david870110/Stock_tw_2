"""Reporting contracts for metrics and artifact generation."""

from typing import Any, Protocol

from src.tw_quant.schema.models import BacktestResult, ReportArtifact


class MetricsCalculator(Protocol):
    def calculate(self, result: BacktestResult) -> dict[str, Any]:
        """Calculate metrics dictionary from a backtest result."""


class ReportBuilder(Protocol):
    def build(self, result: BacktestResult) -> list[ReportArtifact]:
        """Build report artifacts from backtest output."""
