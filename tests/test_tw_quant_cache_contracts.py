"""Contract tests for local cache layer scaffolding."""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta

import pytest

from src.tw_quant.storage import (
    CacheEnvelope,
    CacheVersionMetadata,
    FileSafeLocalCache,
    InMemoryLocalCache,
    build_deterministic_cache_key,
)
from src.tw_quant.storage.cache.interfaces import LocalCache


def _assert_has_method(cls: type, method_name: str) -> None:
    assert hasattr(cls, method_name)
    method = getattr(cls, method_name)
    assert callable(method)
    signature = inspect.signature(method)
    assert "self" in signature.parameters


def _sample_envelope(*, key: str, expires_at: datetime | None = None) -> CacheEnvelope:
    return CacheEnvelope(
        key=key,
        payload={"rows": [1, 2]},
        version=CacheVersionMetadata(schema_name="ohlcv", schema_version="1.0.0"),
        created_at=datetime(2026, 3, 11, 10, 0, 0),
        expires_at=expires_at,
    )


def test_protocol_local_cache_shape() -> None:
    _assert_has_method(LocalCache, "read")
    _assert_has_method(LocalCache, "write")
    _assert_has_method(LocalCache, "delete")


def test_deterministic_cache_key_sorts_parts_by_name() -> None:
    key = build_deterministic_cache_key(
        namespace="twq",
        topic="daily_ohlcv",
        parts={"end": "2024-01-31", "symbol": "2330.TW", "start": "2024-01-01"},
    )
    assert key.parts == (
        ("end", "2024-01-31"),
        ("start", "2024-01-01"),
        ("symbol", "2330.TW"),
    )


def test_deterministic_cache_key_value_schema() -> None:
    key = build_deterministic_cache_key(
        namespace="twq",
        topic="daily_ohlcv",
        parts={"symbol": "2330.TW", "start": "2024-01-01"},
    )
    assert key.value == "twq:daily_ohlcv:start=2024-01-01|symbol=2330.TW"


def test_deterministic_cache_key_without_parts() -> None:
    key = build_deterministic_cache_key(namespace="twq", topic="meta")
    assert key.value == "twq:meta"


def test_version_metadata_defaults_key_version() -> None:
    metadata = CacheVersionMetadata(schema_name="bars", schema_version="2.0.0")
    assert metadata.key_version == "v1"


def test_cache_models_are_frozen() -> None:
    envelope = _sample_envelope(key="twq:daily")
    with pytest.raises(Exception):
        envelope.key = "other"  # type: ignore[misc]


def test_inmemory_local_cache_read_miss_for_missing_key() -> None:
    cache = InMemoryLocalCache()
    result = cache.read("missing")
    assert result.outcome == "miss"
    assert result.envelope is None


def test_inmemory_local_cache_write_then_read_hit() -> None:
    cache = InMemoryLocalCache()
    envelope = _sample_envelope(key="twq:daily:symbol=2330.TW")

    write_result = cache.write(envelope)
    read_result = cache.read(envelope.key)

    assert write_result.written is True
    assert write_result.replaced_existing is False
    assert read_result.outcome == "hit"
    assert read_result.envelope == envelope


def test_inmemory_local_cache_write_reports_replaced_existing() -> None:
    cache = InMemoryLocalCache()
    key = "twq:daily:symbol=2330.TW"

    cache.write(_sample_envelope(key=key))
    second_write = cache.write(_sample_envelope(key=key))

    assert second_write.written is True
    assert second_write.replaced_existing is True


def test_inmemory_local_cache_expired_boundary_returns_expired() -> None:
    cache = InMemoryLocalCache()
    expires_at = datetime(2026, 3, 11, 11, 0, 0)
    envelope = _sample_envelope(key="twq:daily:symbol=2330.TW", expires_at=expires_at)
    cache.write(envelope)

    result = cache.read(envelope.key, now=expires_at + timedelta(seconds=1))
    assert result.outcome == "expired"
    assert result.envelope is None


def test_inmemory_local_cache_delete_boundary() -> None:
    cache = InMemoryLocalCache()
    key = "twq:daily:symbol=2330.TW"
    cache.write(_sample_envelope(key=key))

    assert cache.delete(key) is True
    assert cache.delete(key) is False


def test_filesafe_local_cache_creates_root_dir_and_behaves_like_stub(tmp_path) -> None:
    root_dir = tmp_path / "cache"
    cache = FileSafeLocalCache(root_dir)
    envelope = _sample_envelope(key="twq:daily:symbol=2317.TW")

    assert root_dir.exists()
    write_result = cache.write(envelope)
    read_result = cache.read(envelope.key)

    assert write_result.written is True
    assert read_result.outcome == "hit"


def test_storage_package_exports_cache_symbols() -> None:
    import src.tw_quant.storage as storage_pkg

    assert hasattr(storage_pkg, "CacheVersionMetadata")
    assert hasattr(storage_pkg, "CacheEnvelope")
    assert hasattr(storage_pkg, "build_deterministic_cache_key")
    assert hasattr(storage_pkg, "InMemoryLocalCache")
    assert hasattr(storage_pkg, "FileSafeLocalCache")
