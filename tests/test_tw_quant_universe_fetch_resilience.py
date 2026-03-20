from __future__ import annotations

from http.client import IncompleteRead

from src.tw_quant.wiring import container


class _FakeResponse:
    def __init__(self, chunks: list[bytes], *, raise_incomplete_once: bool = False) -> None:
        self._chunks = list(chunks)
        self._raise_incomplete_once = raise_incomplete_once

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, amt: int = -1) -> bytes:
        if self._raise_incomplete_once:
            self._raise_incomplete_once = False
            partial = self._chunks.pop(0) if self._chunks else b""
            raise IncompleteRead(partial=partial, expected=1)
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


def test_fetch_universe_rows_reads_in_chunks(monkeypatch) -> None:
    payload = b'[{"\\u516c\\u53f8\\u4ee3\\u865f": "2330"}]'
    fake_response = _FakeResponse([payload[:7], payload[7:14], payload[14:], b""])

    monkeypatch.setattr(container, "urlopen", lambda *_args, **_kwargs: fake_response)

    rows = container._fetch_universe_rows("https://example.com/universe", timeout=3.0)

    assert rows == [{"公司代號": "2330"}]


def test_fetch_universe_rows_tolerates_incomplete_read(monkeypatch) -> None:
    partial_payload = b'[{"\\u516c\\u53f8\\u4ee3\\u865f":"2330"}]'
    fake_response = _FakeResponse([partial_payload, b""], raise_incomplete_once=True)

    monkeypatch.setattr(container, "urlopen", lambda *_args, **_kwargs: fake_response)

    rows = container._fetch_universe_rows("https://example.com/universe", timeout=3.0)

    assert rows == [{"公司代號": "2330"}]


def test_fetch_universe_rows_uses_partial_json_array_when_truncated(monkeypatch) -> None:
    truncated_payload = b'[{"\\u516c\\u53f8\\u4ee3\\u865f":"2330"},{"\\u516c\\u53f8\\u4ee3\\u865f":"23'
    fake_response = _FakeResponse([truncated_payload, b""])

    monkeypatch.setattr(container, "urlopen", lambda *_args, **_kwargs: fake_response)

    rows = container._fetch_universe_rows("https://example.com/universe", timeout=3.0)

    assert rows == [{"公司代號": "2330"}]


def test_fetch_tpex_rows_with_fallback_merges_and_deduplicates(monkeypatch) -> None:
    payload_by_url = {
        "https://primary.example/tpex": [
            {"SecuritiesCode": "6488", "Name": "A"},
            {"SecuritiesCode": "1234", "Name": "B"},
        ],
        "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes": [
            {"SecuritiesCode": "6488", "Name": "A-dup"},
            {"SecuritiesCode": "3324", "Name": "C"},
        ],
    }

    def fake_fetch(url: str, timeout: float):
        if url in payload_by_url:
            return payload_by_url[url]
        raise RuntimeError("missing")

    monkeypatch.setattr(container, "_fetch_universe_rows", fake_fetch)

    rows = container._fetch_tpex_rows_with_fallback(
        primary_url="https://primary.example/tpex",
        timeout=3.0,
    )

    symbols = [row["symbol"] for row in rows]
    assert symbols == ["6488", "1234", "3324"]


def test_fetch_tpex_rows_with_fallback_raises_when_all_candidates_fail(monkeypatch) -> None:
    def fake_fetch(_url: str, _timeout: float):
        raise RuntimeError("network down")

    monkeypatch.setattr(container, "_fetch_universe_rows", fake_fetch)

    try:
        container._fetch_tpex_rows_with_fallback(primary_url="https://primary.example/tpex", timeout=3.0)
    except RuntimeError as exc:
        assert "network down" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
