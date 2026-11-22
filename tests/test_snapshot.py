"""Pillanatkép-építés: frissesség, kereszt-ellenőrzés, hiányok (ugyanaz élőben és visszajátszásban)."""
from decimal import Decimal

from btcpaper.models import Quote, RefPrice
from btcpaper.snapshot import RawData, build_snapshot
from btcpaper.timeutil import D1, H1, MIN
from tests.helpers import T0, candle, cfg_with

CFG = cfg_with(data__lookback_4h_bars=10, data__lookback_1d_bars=5)
NOW = T0 + 10 * D1 + 5 * MIN + 30       # okt. 11. 00:05:30


def raw(now=NOW, price=100000, kprice=None, qtime=None, ktime=None, h1_drop=(), h1_dup=False, m1_drop=(),
        d1_drop=()):
    h1 = [candle(t, price, price + 10, price - 10, price) for t in range(T0, int(now) - H1 + 1, H1)
          if (t + H1 + 10 <= now) and t not in h1_drop]
    if h1_dup:
        h1.append(h1[-1])
    d1 = [candle(t, price, price + 10, price - 10, price) for t in range(T0 - 20 * D1, int(now), D1)
          if t + D1 + 10 <= now and t not in d1_drop]
    m1 = [candle(t, price, price + 1, price - 1, price) for t in range(int(now) // 60 * 60 - 600, int(now), MIN)
          if t not in m1_drop]
    q = Quote(Decimal(price), Decimal(price), Decimal(price), qtime if qtime is not None else now - 2)
    r = RefPrice(Decimal(kprice if kprice is not None else price), ktime if ktime is not None else now - 20)
    return RawData(m1=m1, h1=h1, d1=d1, quote=q, ref=r, clock_offset=0.5)


def snap(**kw):
    return build_snapshot(CFG, NOW, "x", int(NOW) // 60 * 60 - 600, raw(**kw))


def test_clean_snapshot_has_no_issues():
    s = snap()
    assert s.issues == []
    assert len(s.h4) == 10 and len(s.d1) == 5
    assert s.h4[-1].start + 4 * H1 == T0 + 10 * D1           # az utolsó lezárt 4H gyertya
    assert s.m1_window_end == (int(NOW) - 10) // 60 * 60


def test_crosscheck_threshold_boundary():
    assert not any("Kereszt" in i for i in snap(kprice=Decimal(100000) / Decimal("1.0049")).issues)
    assert any("Kereszt" in i for i in snap(kprice=Decimal(100000) / Decimal("1.0051")).issues)


def test_stale_data_over_3_minutes_blocks():
    assert snap(qtime=NOW - 179).issues == []
    assert any("régi" in i for i in snap(qtime=NOW - 181).issues)
    assert any("Kraken ár régi" in i for i in snap(ktime=NOW - 200).issues)


def test_missing_kraken_blocks_trading():
    r = raw()
    r.ref = None
    s = build_snapshot(CFG, NOW, "x", int(NOW) // 60 * 60 - 600, r)
    assert any("Kereszt-ellenőrzés nem végezhető" in i for i in s.issues)


def test_duplicate_h1_blocks():
    assert any("duplik" in i for i in snap(h1_dup=True).issues)


def test_recent_h1_gap_blocks_old_gap_is_noted():
    recent = T0 + 10 * D1 - 3 * H1
    s = snap(h1_drop=(recent,))
    assert any("1H hiány" in i or "4H hiányos" in i for i in s.issues)
    old = T0 + 2 * H1
    s2 = snap(h1_drop=(old,))
    assert s2.issues == [] and any("régi hiány" in n for n in s2.notes)


def test_missing_latest_closed_h1_blocks():
    last = T0 + 10 * D1 - H1
    assert any("1H hiány" in i or "4H" in i for i in snap(h1_drop=(last,)).issues)


def test_missing_last_daily_blocks():
    assert any("1D utolsó" in i for i in snap(d1_drop=(T0 + 9 * D1,)).issues)


def test_m1_duplicates_mark_m1_unusable():
    r = raw()
    r.m1.append(r.m1[-3])
    s = build_snapshot(CFG, NOW, "x", int(NOW) // 60 * 60 - 600, r)
    assert s.m1_issue and any("1m" in i for i in s.issues)


def test_fetch_error_is_issue():
    r = raw()
    r.h1 = None
    r.errors.append("h1 letöltés hiba: timeout")
    s = build_snapshot(CFG, NOW, "x", int(NOW) // 60 * 60 - 600, r)
    assert any("h1 letöltés hiba" in i for i in s.issues)


def test_clock_skew_blocks():
    r = raw()
    r.clock_offset = 31.0
    s = build_snapshot(CFG, NOW, "x", int(NOW) // 60 * 60 - 600, r)
    assert any("Óraeltérés" in i for i in s.issues)
