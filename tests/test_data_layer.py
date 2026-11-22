"""Adatréteg: lapozás, hiány/duplikátum, lezártság, 4H összevonás, HTTP újrapróbálás."""
import pytest
import requests

from btcpaper.candles import aggregate_4h, check_series, closed_only
from btcpaper.http_client import HttpClient, HttpError
from btcpaper.sources import coinbase_windows
from btcpaper.timeutil import H1, H4, MIN, parse_iso, iso
from tests.helpers import T0, candle


def test_coinbase_windows_cover_range_without_overlap_and_max_300():
    start, end = T0, T0 + 1000 * MIN
    w = coinbase_windows(60, start, end)
    covered = []
    for a, b in w:
        n = (b - a) // 60 + 1
        assert 1 <= n <= 300
        covered.extend(range(a, b + 1, 60))
    assert covered == list(range(start, end + 1, 60))       # minden perc pontosan egyszer
    assert len(w) == 4


def test_coinbase_windows_reject_unsupported_granularity():
    with pytest.raises(ValueError):
        coinbase_windows(14400, T0, T0 + H4)


def test_check_series_finds_gaps_duplicates_bad():
    cs = [candle(T0, 1, 2, 0.5, 1.5), candle(T0 + 60, 1, 2, 0.5, 1.5), candle(T0 + 60, 1, 2, 0.5, 1.5),
          candle(T0 + 240, 1, 2, 0.5, 1.5), candle(T0 + 300, 1, 0.9, 0.5, 1.5), candle(T0 + 330, 1, 2, 0.5, 1)]
    chk = check_series(cs, 60)
    assert chk.duplicates == [T0 + 60]
    assert chk.gaps == [T0 + 120, T0 + 180]
    assert chk.bad == [T0 + 300]                 # high < open
    assert chk.misaligned == [T0 + 330]
    assert not chk.clean
    assert [c.start for c in chk.candles] == [T0, T0 + 60, T0 + 240, T0 + 300]


def test_closed_only_uses_end_plus_grace():
    cs = [candle(T0, 1, 1, 1, 1), candle(T0 + 60, 1, 1, 1, 1)]
    assert [c.start for c in closed_only(cs, 60, T0 + 69, 10)] == []
    assert [c.start for c in closed_only(cs, 60, T0 + 70, 10)] == [T0]
    assert [c.start for c in closed_only(cs, 60, T0 + 130, 10)] == [T0, T0 + 60]


def test_aggregate_4h_values_and_incomplete_and_open_bucket():
    h1 = [candle(T0 + i * H1, 10 + i, 20 + i, 5 + i, 11 + i, 1) for i in range(4)]       # teljes 4H
    h1 += [candle(T0 + H4 + i * H1, 1, 2, 0.5, 1.5) for i in (0, 1, 3)]                  # hiányos 4H
    h1 += [candle(T0 + 2 * H4, 1, 2, 0.5, 1.5)]                                          # még nyitott 4H
    bars, incomplete = aggregate_4h(h1, now=T0 + 2 * H4 + H1 + 20, grace=10)
    assert [b.start for b in bars] == [T0, T0 + H4]
    b = bars[0]
    assert (b.open, b.high, b.low, b.close, b.volume) == (10, 23, 5, 14, 4)
    assert incomplete == [T0 + H4]


def test_parse_iso_nanoseconds():
    assert parse_iso("2026-11-22T12:05:02.656894808Z") == pytest.approx(1795349102.656894)
    assert iso(1790812800) == "2026-10-01T00:00:00Z"


class FakeResp:
    def __init__(self, status, payload=None, text="", headers=None):
        self.status_code = status
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self, **kw):
        return self._payload


class FakeSession:
    def __init__(self, seq):
        self.seq = list(seq)
        self.headers = {}
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        item = self.seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_client(seq, **kw):
    sleeps = []
    s = FakeSession(seq)
    c = HttpClient(session=s, sleep=sleeps.append, clock=lambda: 0.0, min_interval=0, backoff_base=1.0, **kw)
    return c, s, sleeps


def test_http_retries_with_exponential_backoff_then_succeeds():
    c, s, sleeps = make_client([requests.Timeout("t"), FakeResp(503), FakeResp(429), FakeResp(200, {"ok": 1})],
                               max_retries=5)
    assert c.get_json("u") == {"ok": 1}
    assert s.calls == 4
    assert sleeps == [1.0, 2.0, 4.0]


def test_http_respects_retry_after():
    c, s, sleeps = make_client([FakeResp(429, headers={"Retry-After": "7"}), FakeResp(200, [1])])
    assert c.get_json("u") == [1]
    assert sleeps == [7.0]


def test_http_gives_up_after_max_retries():
    c, s, sleeps = make_client([FakeResp(500)] * 3, max_retries=2)
    with pytest.raises(HttpError):
        c.get_json("u")
    assert s.calls == 3 and sleeps == [1.0, 2.0]


def test_http_non_retryable_fails_immediately():
    c, s, sleeps = make_client([FakeResp(451, text="blocked")], max_retries=5)
    with pytest.raises(HttpError) as e:
        c.get_json("u")
    assert e.value.status == 451 and s.calls == 1 and sleeps == []


def test_http_throttle_enforces_min_interval():
    t = {"now": 0.0}
    sleeps = []

    def sleep(x):
        sleeps.append(x)
        t["now"] += x

    s = FakeSession([FakeResp(200, 1), FakeResp(200, 2)])
    c = HttpClient(session=s, sleep=sleep, clock=lambda: t["now"], min_interval=0.5)
    c.get_json("a")
    c.get_json("b")
    assert sleeps == [0.5]
