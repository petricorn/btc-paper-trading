"""Technikai indikátorok, saját, függőség nélküli implementáció (Wilder-féle simítás ahol szokásos).

Minden függvény ugyanolyan hosszú listát ad vissza, mint a bemenet; ahol még nincs elég adat,
ott None az érték. Az indikátorok float-tal számolnak (a könyvelés Decimal-lal).
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

Num = Optional[float]


def sma(x: Sequence[float], n: int) -> list[Num]:
    out: list[Num] = [None] * len(x)
    if n <= 0:
        raise ValueError("n > 0")
    for i in range(n - 1, len(x)):
        out[i] = math.fsum(x[i - n + 1:i + 1]) / n
    return out


def ema(x: Sequence[float], n: int) -> list[Num]:
    """EMA: az első érték az első n elem egyszerű átlaga, utána alpha = 2/(n+1)."""
    out: list[Num] = [None] * len(x)
    if len(x) < n:
        return out
    alpha = 2.0 / (n + 1)
    v = math.fsum(x[:n]) / n
    out[n - 1] = v
    for i in range(n, len(x)):
        v = alpha * x[i] + (1 - alpha) * v
        out[i] = v
    return out


def rsi(close: Sequence[float], n: int = 14) -> list[Num]:
    """Wilder RSI. Első érték az n-edik változás után (index n)."""
    out: list[Num] = [None] * len(close)
    if len(close) <= n:
        return out
    gains = [max(close[i] - close[i - 1], 0.0) for i in range(1, len(close))]
    losses = [max(close[i - 1] - close[i], 0.0) for i in range(1, len(close))]
    ag = math.fsum(gains[:n]) / n
    al = math.fsum(losses[:n]) / n

    def val(g, l):
        if l == 0:
            return 100.0 if g > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + g / l)

    out[n] = val(ag, al)
    for i in range(n + 1, len(close)):
        ag = (ag * (n - 1) + gains[i - 1]) / n
        al = (al * (n - 1) + losses[i - 1]) / n
        out[i] = val(ag, al)
    return out


def true_range(high: Sequence[float], low: Sequence[float], close: Sequence[float]) -> list[float]:
    tr = []
    for i in range(len(close)):
        if i == 0:
            tr.append(high[0] - low[0])
        else:
            pc = close[i - 1]
            tr.append(max(high[i] - low[i], abs(high[i] - pc), abs(low[i] - pc)))
    return tr


def atr(high, low, close, n: int = 14) -> list[Num]:
    """Wilder ATR: első érték az első n TR átlaga (index n-1), utána (előző*(n-1)+TR)/n."""
    out: list[Num] = [None] * len(close)
    if len(close) < n:
        return out
    tr = true_range(high, low, close)
    v = math.fsum(tr[:n]) / n
    out[n - 1] = v
    for i in range(n, len(close)):
        v = (v * (n - 1) + tr[i]) / n
        out[i] = v
    return out


def adx(high, low, close, n: int = 14) -> list[Num]:
    """Wilder ADX. +DM/-DM/TR Wilder-összeggel simítva; első DX az n-edik indexen,
    első ADX a 2n-1 indexen (az első n DX átlaga)."""
    L = len(close)
    out: list[Num] = [None] * L
    if L < 2 * n:
        return out
    pdm = [0.0] * L
    mdm = [0.0] * L
    tr = [0.0] * L
    for i in range(1, L):
        up = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        pdm[i] = up if (up > down and up > 0) else 0.0
        mdm[i] = down if (down > up and down > 0) else 0.0
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    str_ = math.fsum(tr[1:n + 1])
    sp = math.fsum(pdm[1:n + 1])
    sm = math.fsum(mdm[1:n + 1])
    dx: list[Num] = [None] * L

    def calc_dx(spv, smv, trv):
        if trv == 0:
            return 0.0
        pdi = 100.0 * spv / trv
        mdi = 100.0 * smv / trv
        s = pdi + mdi
        return 0.0 if s == 0 else 100.0 * abs(pdi - mdi) / s

    dx[n] = calc_dx(sp, sm, str_)
    for i in range(n + 1, L):
        str_ = str_ - str_ / n + tr[i]
        sp = sp - sp / n + pdm[i]
        sm = sm - sm / n + mdm[i]
        dx[i] = calc_dx(sp, sm, str_)
    first = 2 * n - 1
    v = math.fsum(dx[n:first + 1]) / n
    out[first] = v
    for i in range(first + 1, L):
        v = (v * (n - 1) + dx[i]) / n
        out[i] = v
    return out


def bollinger(close: Sequence[float], n: int = 20, k: float = 2.0) -> tuple[list[Num], list[Num], list[Num]]:
    """Bollinger-szalag: közép = SMA(n), szórás = populációs szórás (Bollinger eredeti definíciója)."""
    mid = sma(close, n)
    up: list[Num] = [None] * len(close)
    lo: list[Num] = [None] * len(close)
    for i in range(n - 1, len(close)):
        w = close[i - n + 1:i + 1]
        m = mid[i]
        var = math.fsum((v - m) ** 2 for v in w) / n
        sd = math.sqrt(var)
        up[i] = m + k * sd
        lo[i] = m - k * sd
    return mid, up, lo
