"""In-memory and file-safe local cache stubs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.tw_quant.storage.cache.models import CacheEnvelope, CacheReadResult, CacheWriteResult


class InMemoryLocalCache:
    """Thread-unsafe deterministic local cache stub for contract testing."""

    def __init__(self) -> None:
        self._entries: dict[str, CacheEnvelope] = {}

    def read(self, key: str, *, now: datetime | None = None) -> CacheReadResult:
        entry = self._entries.get(key)
        if entry is None:
            return CacheReadResult(key=key, outcome="miss", envelope=None)

        reference_time = now or datetime.utcnow()
        if entry.expires_at is not None and reference_time >= entry.expires_at:
            return CacheReadResult(key=key, outcome="expired", envelope=None)

        return CacheReadResult(key=key, outcome="hit", envelope=entry)

    def write(self, envelope: CacheEnvelope) -> CacheWriteResult:
        replaced_existing = envelope.key in self._entries
        self._entries[envelope.key] = envelope
        return CacheWriteResult(
            key=envelope.key,
            written=True,
            replaced_existing=replaced_existing,
        )

    def delete(self, key: str) -> bool:
        if key in self._entries:
            del self._entries[key]
            return True
        return False


class FileSafeLocalCache(InMemoryLocalCache):
    """File-backed scaffold placeholder that currently delegates to memory only."""

    def __init__(self, root_dir: str | Path) -> None:
        super().__init__()
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
