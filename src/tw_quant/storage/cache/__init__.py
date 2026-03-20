"""Local cache layer contracts and stubs."""

from src.tw_quant.storage.cache.interfaces import LocalCache
from src.tw_quant.storage.cache.models import (
    CacheEnvelope,
    CacheReadResult,
    CacheVersionMetadata,
    CacheWriteResult,
    DeterministicCacheKey,
    build_deterministic_cache_key,
)
from src.tw_quant.storage.cache.stubs import FileSafeLocalCache, InMemoryLocalCache

__all__ = [
    "CacheVersionMetadata",
    "DeterministicCacheKey",
    "CacheEnvelope",
    "CacheReadResult",
    "CacheWriteResult",
    "build_deterministic_cache_key",
    "LocalCache",
    "InMemoryLocalCache",
    "FileSafeLocalCache",
]
