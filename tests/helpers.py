"""Teszt-segédek: config felülírás, szintetikus gyertyák, kézzel épített pillanatkép."""
from __future__ import annotations

import copy
import random
from decimal import Decimal
from pathlib import Path

from btcpaper.config import config_from_dict, load_config
from btcpaper.engine import Engine
from btcpaper.models import Candle, Quote, RefPrice
from btcpaper.num import D
from btcpaper.snapshot import Snapshot
from btcpaper.state import new_state
from btcpaper.strategies import Evaluation
from btcpaper.timeutil import H1, H4, MIN, D1

ROOT = Path(__file__).resolve().parents[1]
BASE_RAW = load_config(ROOT / "config.yaml").raw
T0 = 1_790_812_800          # 2026-10-01 00:00:00 UTC


def cfg_with(**overrides):
    """overrides: 'risk.risk_per_trade'='0.02' formájú kulcsok (pontokkal)."""
    raw = copy.deepcopy(BASE_RAW)
    for path, val in overrides.items():
        node = raw
        parts = path.split("__")
        for p in parts[:-1]:
            node = node[p]
        node[parts[-1]] = val
    return config_from_dict(raw)


def candle(start, o, h, l, c, v=1):
    return Candle(start=start, open=D(o), high=D(h), low=D(l), close=D(c), volume=D(v))


def flat_h4(end_close_time: int, n: int = 40, price=100000, rng=1000):
    """n db 4H gyertya, mindegyik high-low = rng, záró = price → ATR14 = rng (pontosan)."""
    first = end_close_time - n * H4
    p = D(price)
    half = D(rng) / 2
    return [candle(first + i * H4, p, p + half, p - half, p) for i in range(n)]


def flat_d1(end_close_time: int, n: int = 30, price=100000):
    first = end_close_time - n * D1
    p = D(price)
    return [candle(first + i * D1, p, p + 500, p - 500, p) for i in range(n)]


def m1_flat(start: int, end: int, price=100000, spread=10):
    p = D(price)
    return {t: candle(t, p, p + spread, p - spread, p) for t in range(start, end, MIN)}


def make_snap(now, run_id=None, m1=None, h4=None, d1=None, bid=100000, ask=None, issues=None, grace=10):
    ask = bid if ask is None else ask
    q = Quote(bid=D(bid), ask=D(ask), last=D(bid), time=now - 1)
    window_end = ((int(now) - grace) // MIN) * MIN
    return Snapshot(now=now, run_id=run_id or f"t-{int(now)}", m1=m1 if m1 is not None else {},
                    m1_window_end=window_end, h4=h4 or [], d1=d1 or [], quote=q, ref=RefPrice(D(bid), now - 1),
                    issues=list(issues or []), notes=[], metrics={})


class StubStrategy:
    """Kézzel vezérelt stratégia a motor-tesztekhez: a megadott gyertyáknál ad jelzést."""
    timeframe = "4h"

    def __init__(self, entries=(), exits=()):
        self.entries = set(entries)
        self.exits = set(exits)

    def evaluate(self, ctx):
        if not ctx.h4:
            return None
        b = ctx.h4[-1]
        close_time = b.start + H4
        return Evaluation(bar_start=b.start, bar_close_time=close_time, close=b.close,
                          entry=close_time in self.entries, exit=close_time in self.exits, values={"stub": True})


def engine_with_stub(cfg, name="P1", **kw):
    eng = Engine(cfg)
    stub = StubStrategy(**kw)
    eng.strategies[name] = stub
    # a többi stratégia ne adjon jelzést
    for other in ("P1", "P2", "P3"):
        if other != name:
            eng.strategies[other] = StubStrategy()
    return eng, stub


def fresh_state(cfg, start=T0):
    st = new_state(cfg, start)
    # a mércék ne zavarjanak: legyenek "már megvéve" állapotban, ha a teszt nem róluk szól
    return st


def synthetic_m1(start: int, days: int, seed: int = 7, price: float = 60000.0, vol: float = 0.0012,
                 drift: float = 0.00002, flip: int = 4000):
    """Szintetikus 1 perces random walk (csak tesztekhez – NEM valódi piaci adat)."""
    rng = random.Random(seed)
    out = []
    p = price
    for i in range(days * 1440):
        o = p
        d = drift * (1 if (i // flip) % 2 == 0 else -1)
        c = o * (1 + d + rng.gauss(0, vol))
        h = max(o, c) * (1 + abs(rng.gauss(0, vol / 3)))
        l = min(o, c) * (1 - abs(rng.gauss(0, vol / 3)))
        out.append(Candle(start=start + i * MIN, open=D(f"{o:.2f}"), high=D(f"{h:.2f}"), low=D(f"{l:.2f}"),
                          close=D(f"{c:.2f}"), volume=D("1")))
        p = float(f"{c:.2f}")
    # OHLC konzisztencia a kerekítés után
    fixed = []
    for c in out:
        hi = max(c.high, c.open, c.close)
        lo = min(c.low, c.open, c.close)
        fixed.append(Candle(c.start, c.open, hi, lo, c.close, c.volume))
    return fixed


def aggregate(m1: list, gran: int):
    buckets = {}
    for c in m1:
        buckets.setdefault(c.start // gran * gran, []).append(c)
    out = []
    for b in sorted(buckets):
        g = buckets[b]
        out.append(Candle(b, g[0].open, max(x.high for x in g), min(x.low for x in g), g[-1].close,
                          sum((x.volume for x in g), Decimal(0))))
    return out


def synthetic_wave(start: int, days: int, seed: int = 3, price: float = 60000.0, amp: float = 0.06,
                   period_days: float = 2.3, noise: float = 0.0015):
    """Szintetikus, hullámzó 1 perces adat (csak tesztekhez – NEM valódi piaci adat): sok kitörés,
    visszahúzódás, szalag-érintés és stop, hogy a motor minden ága kipróbálásra kerüljön."""
    import math
    rng = random.Random(seed)
    out = []
    prev = price
    per = period_days * 1440
    for i in range(days * 1440):
        base = price * (1 + amp * math.sin(2 * math.pi * i / per) + 0.5 * amp * math.sin(2 * math.pi * i / (per / 3.7)))
        c = base * (1 + rng.gauss(0, noise))
        o = prev
        h = max(o, c) * (1 + abs(rng.gauss(0, noise / 2)))
        l = min(o, c) * (1 - abs(rng.gauss(0, noise / 2)))
        o2, h2, l2, c2 = (D(f"{x:.2f}") for x in (o, h, l, c))
        out.append(Candle(start + i * MIN, o2, max(h2, o2, c2), min(l2, o2, c2), c2, D("1")))
        prev = float(c2)
    return out
