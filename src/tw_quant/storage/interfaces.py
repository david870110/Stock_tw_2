"""Storage contracts for raw, canonical, and artifact persistence."""

from typing import Any, Protocol, Sequence

from src.tw_quant.core.types import DateLike, Symbol
from src.tw_quant.schema.models import FundamentalPoint, OHLCVBar, ReportArtifact


class RawDataStore(Protocol):
    def save_raw(self, namespace: str, key: str, payload: dict[str, Any]) -> None:
        """Persist vendor-native payloads for reproducibility."""

    def load_raw(self, namespace: str, key: str) -> dict[str, Any] | None:
        """Load vendor-native payloads if present."""


class CanonicalDataStore(Protocol):
    def save_ohlcv(self, bars: Sequence[OHLCVBar]) -> None:
        """Persist canonical OHLCV bars."""

    def load_ohlcv(
        self, symbols: Sequence[Symbol], start: DateLike, end: DateLike
    ) -> list[OHLCVBar]:
        """Load canonical OHLCV bars."""

    def save_fundamentals(self, points: Sequence[FundamentalPoint]) -> None:
        """Persist canonical fundamentals."""

    def load_fundamentals(
        self, symbols: Sequence[Symbol], start: DateLike, end: DateLike
    ) -> list[FundamentalPoint]:
        """Load canonical fundamentals."""


class ArtifactStore(Protocol):
    def save_artifact(self, artifact: ReportArtifact, content: bytes) -> None:
        """Persist report artifacts and supplementary outputs."""

    def load_artifact(self, artifact_id: str) -> bytes | None:
        """Load artifact content by identifier."""
