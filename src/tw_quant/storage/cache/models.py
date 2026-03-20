"""Cache contract models for deterministic local cache boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping


@dataclass(slots=True, frozen=True)
class CacheVersionMetadata:
    """Version metadata attached to cache entries and key contracts."""

    schema_name: str
    schema_version: str
    key_version: str = "v1"


@dataclass(slots=True, frozen=True)
class DeterministicCacheKey:
    """Deterministic key contract built from namespace, topic, and sorted parts."""

    namespace: str
    topic: str
    parts: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def value(self) -> str:
        base = f"{self.namespace}:{self.topic}"
        if not self.parts:
            return base
        serialized_parts = "|".join(f"{name}={value}" for name, value in self.parts)
        return f"{base}:{serialized_parts}"


@dataclass(slots=True, frozen=True)
class CacheEnvelope:
    """Serialized cache entry boundary with payload and metadata."""

    key: str
    payload: Mapping[str, Any]
    version: CacheVersionMetadata
    created_at: datetime
    expires_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class CacheReadResult:
    """Read boundary result for local cache operations."""

    key: str
    outcome: Literal["hit", "miss", "expired"]
    envelope: CacheEnvelope | None


@dataclass(slots=True, frozen=True)
class CacheWriteResult:
    """Write boundary result for local cache operations."""

    key: str
    written: bool
    replaced_existing: bool


def build_deterministic_cache_key(
    namespace: str,
    topic: str,
    parts: Mapping[str, Any] | None = None,
) -> DeterministicCacheKey:
    """Build a deterministic key object by sorting part names lexicographically."""

    normalized_parts: tuple[tuple[str, str], ...] = ()
    if parts:
        normalized_parts = tuple((name, str(parts[name])) for name in sorted(parts))

    return DeterministicCacheKey(namespace=namespace, topic=topic, parts=normalized_parts)
