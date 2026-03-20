"""Normalization result models for non-throwing canonical mapping boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar


TRecord = TypeVar("TRecord")


@dataclass(slots=True, frozen=True)
class NormalizationError:
    """Describes one non-fatal normalization failure for an input row."""

    row_index: int
    code: str
    message: str
    field: str = ""
    value: str = ""


@dataclass(slots=True)
class BoundaryValidationResult(Generic[TRecord]):
    """Boundary output that always returns records and collected errors."""

    records: list[TRecord] = field(default_factory=list)
    errors: list[NormalizationError] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class AliasMap:
    """Canonical field aliases used during source-to-schema mapping."""

    canonical: str
    aliases: tuple[str, ...]
