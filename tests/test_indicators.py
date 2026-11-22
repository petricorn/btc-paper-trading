"""Indikátorok: ismert referenciaértékek és kézzel kiszámolt példák."""
import math
import statistics

import pytest

from btcpaper import indicators as ind

# StockCharts "RSI" oktatóanyag (Wilder, 14) példaadata és közölt RSI értékei
SC_CLOSE = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28,
            46.28, 46.00, 46.03, 46.41, 46.22, 45.64, 46.21, 46.25, 45.71, 46.45, 45.78, 45.35, 44.03, 44.18,
            44.22, 44.57, 43.42, 42.66, 43.13]
SC_RSI = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93, 63.26, 56.06, 62.38, 54.71, 50.42, 39.99, 41.46,
          41.87, 45.46, 37.30, 33.08, 37.77]


def test_rsi_close_to_stockcharts_published_values():
    """A közölt táblázat kerekített kezdőátlagokkal készült; az eltérés <= 0,07 és csökkenő."""
    r = ind.rsi(SC_CLOSE, 14)
    assert all(v is None for v in r[:14])
    got = r[14:]
    assert len(got) == len(SC_RSI)
    for g, e in zip(got, SC_RSI):
        assert g == pytest.approx(e, abs=0.08)
    assert abs(got[-1] - SC_RSI[-1]) < 0.03


def _pandas_wilder(values, n):
    """Független referencia: pandas ewm(alpha=1/n) az első n elem átlagával indítva."""
    import pandas as pd
    s = pd.Series(values[n - 1:], dtype="float64")
    s.iloc[0] = sum(values[:n]) / n
    return [None] * (n - 1) + list(s.ewm(alpha=1 / n, adjust=False).mean())


def test_rsi_and_atr_match_independent_pandas_reference():
    import random
    rng = random.Random(3)
    close = [100.0]
    for _ in range(400):
        close.append(close[-1] * (1 + rng.gauss(0, 0.01)))
    high = [c * (1 + abs(rng.gauss(0, 0.005))) for c in close]
    low = [c * (1 - abs(rng.gauss(0, 0.005))) for c in close]
    n = 14
    gains = [max(close[i] - close[i - 1], 0) for i in range(1, len(close))]
    losses = [max(close[i - 1] - close[i], 0) for i in range(1, len(close))]
    ag, al = _pandas_wilder(gains, n), _pandas_wilder(losses, n)
    ref_rsi = [None] + [None if g is None else 100 - 100 / (1 + g / l) for g, l in zip(ag, al)]
    mine = ind.rsi(close, n)
    for a, b in zip(mine, ref_rsi):
        assert (a is None and b is None) or a == pytest.approx(b, rel=1e-9)
    tr = ind.true_range(high, low, close)
    ref_atr = _pandas_wilder(tr, n)
    for a, b in zip(ind.atr(high, low, close, n), ref_atr):
        assert (a is None and b is None) or a == pytest.approx(b, rel=1e-9)


def test_rsi_edge_cases():
    assert ind.rsi([1, 2, 3, 4, 5, 6], 3)[-1] == 100.0          # csak emelkedés
    assert ind.rsi([6, 5, 4, 3, 2, 1], 3)[-1] == 0.0            # csak esés
    assert ind.rsi([5, 5, 5, 5, 5], 3)[-1] == 50.0              # nincs mozgás
    assert ind.rsi([1, 2], 3) == [None, None]


def test_sma_and_ema_hand_computed():
    x = list(range(1, 11))
    s = ind.sma(x, 3)
    assert s[:2] == [None, None] and s[2] == 2 and s[-1] == 9
    e = ind.ema(x, 3)        # seed = 2, alpha = 0.5 → lineáris sorozaton x-1
    assert e[:2] == [None, None]
    assert e[2:] == pytest.approx([2, 3, 4, 5, 6, 7, 8, 9])
    e2 = ind.ema([10, 10, 10, 20], 3)
    assert e2[-1] == pytest.approx(15.0)


def test_atr_hand_computed():
    h = [10, 11, 12, 11, 15]
    l = [8, 9, 9, 7, 14]
    c = [9, 10, 11, 8, 14.5]
    a = ind.atr(h, l, c, 3)
    assert a[:2] == [None, None]
    assert a[2] == pytest.approx(7 / 3)
    assert a[3] == pytest.approx(26 / 9)
    assert a[4] == pytest.approx(115 / 27)       # gap: TR = |high - előző záró| = 7


def test_adx_hand_computed():
    h = [10, 12, 13, 12, 11]
    l = [8, 9, 10, 8, 7]
    c = [9, 11, 12, 9, 8]
    a = ind.adx(h, l, c, 2)
    assert a[:3] == [None, None, None]
    assert a[3] == pytest.approx(400 / 7)
    assert a[4] == pytest.approx(7900 / 154)


def test_adx_trend_vs_range():
    up = [100 + i for i in range(80)]
    a_up = ind.adx([v + 1 for v in up], [v - 1 for v in up], up, 14)[-1]
    side = [100 + (1 if i % 2 else -1) for i in range(80)]
    a_side = ind.adx([v + 1 for v in side], [v - 1 for v in side], side, 14)[-1]
    assert a_up > 50 and a_side < 20


def test_bollinger_population_std():
    x = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    mid, up, lo = ind.bollinger(x, 5, 2.0)
    w = x[-5:]
    sd = statistics.pstdev(w)
    assert mid[-1] == pytest.approx(8)
    assert up[-1] == pytest.approx(8 + 2 * sd)
    assert lo[-1] == pytest.approx(8 - 2 * sd)
    assert mid[3] is None


def test_true_range_first_bar():
    assert ind.true_range([5], [3], [4]) == [2]
