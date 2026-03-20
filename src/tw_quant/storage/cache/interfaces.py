"""Interfaces for local cache storage boundaries."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.tw_quant.storage.cache.models import CacheEnvelope, CacheReadResult, CacheWriteResult


class LocalCache(Protocol):
    """Contract for local cache read/write/delete operations."""

    def read(self, key: str, *, now: datetime | None = None) -> CacheReadResult:
        """Read a cache entry and report hit/miss/expired outcome."""

    def write(self, envelope: CacheEnvelope) -> CacheWriteResult:
        """Write a cache envelope and report replacement status."""

    def delete(self, key: str) -> bool:
        """Delete an entry by key and return True when removed."""
