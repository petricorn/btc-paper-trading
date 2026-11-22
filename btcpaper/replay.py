"""Múltbeli időszak visszajátszása UGYANAZZAL a motorral és pillanatkép-építővel, mint az élő futás.

A különbség csak az adatszolgáltató: a ReplayProvider a letöltött valódi Coinbase gyertyákból
pontosan azt adja vissza, ami az adott (szimulált) pillanatban már lezárult. Jövőbeli adat
soha nem kerül a motor elé.

Korlátok (őszintén):
  * Múltbeli bid/ask nincs. A "pillanatnyi ár" a futás percét tartalmazó 1 perces gyertya
    nyitóára (ez a futás pillanatában már ismert), erre jön a csúszás.
  * Múltbeli Kraken ár nincs, ezért visszajátszásban a kereszt-ellenőrzés a Coinbase árral
    egyezőnek tekintett; a hibás eseteket szándékosan beinjektáljuk (eltérés, régi adat).
"""
from __future__ import annotations

import bisect
import csv
import random
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .config import Config
from .engine import Engine
from .models import Candle, Quote, RefPrice
from .num import D
from .snapshot import build_from_provider
from .sources import DataError
from .state import State, load_state, new_state, save_state
from .timeutil import D1, H1, MIN

CACHE_FIELDS = ["start", "open", "high", "low", "close", "volume"]


def write_candles(path: Path, candles: list[Candle]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(CACHE_FIELDS)
        for c in candles:
            w.writerow([c.start, c.open, c.high, c.low, c.close, c.volume])


def read_candles(path: Path) -> list[Candle]:
    with path.open(encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        return [Candle(start=int(x["start"]), open=D(x["open"]), high=D(x["high"]), low=D(x["low"]),
                       close=D(x["close"]), volume=D(x["volume"])) for x in r]


class Series:
    def __init__(self, candles: list[Candle]):
        self.candles = sorted(candles, key=lambda c: c.start)
        self.starts = [c.start for c in self.candles]
        self.by_start = {c.start: c for c in self.candles}

    def range(self, start: int, end: int) -> list[Candle]:
        i = bisect.bisect_left(self.starts, start)
        j = bisect.bisect_right(self.starts, end)
        return self.candles[i:j]


@dataclass
class HistoricalData:
    m1: Series
    h1: Series
    d1: Series

    @classmethod
    def load(cls, folder: str | Path, product: str = "BTC-USD") -> "HistoricalData":
        folder = Path(folder)
        return cls(m1=Series(read_candles(folder / f"coinbase_{product}_60.csv")),
                   h1=Series(read_candles(folder / f"coinbase_{product}_3600.csv")),
                   d1=Series(read_candles(folder / f"coinbase_{product}_86400.csv")))

    def series(self, gran: int) -> Series:
        return {MIN: self.m1, H1: self.h1, D1: self.d1}[gran]


class ReplayProvider:
    """Az adott szimulált pillanatban (now) elérhető adatok; jövőbeli adat soha."""

    def __init__(self, data: HistoricalData, now: float, inject: str | None = None):
        self.data = data
        self.now = now
        self.inject = inject

    def candles(self, gran: int, start: int, end: int) -> list[Candle]:
        if self.inject == "fetch_error" and gran == H1:
            raise DataError("szimulált letöltési hiba")
        end = min(end, int(self.now))
        out = [c for c in self.data.series(gran).range(start, end) if c.start + gran <= self.now]
        if self.inject == "duplicate" and gran == H1 and out:
            out = out + [out[-1]]
        return out

    def _price_now(self) -> tuple[Decimal, float]:
        m = int(self.now) // MIN * MIN
        c = self.data.m1.by_start.get(m)
        if c is None:
            raise DataError(f"nincs 1 perces gyertya a futás percére ({m})")
        return c.open, float(m)

    def quote(self) -> Quote:
        p, t = self._price_now()
        if self.inject == "stale":
            t -= 600
        return Quote(bid=p, ask=p, last=p, time=t, source="replay")

    def ref_price(self) -> RefPrice:
        p, t = self._price_now()
        if self.inject == "crosscheck":
            p = p * Decimal("1.01")
        return RefPrice(price=p, time=t, source="replay")

    def clock_offset(self) -> float:
        return 0.0


@dataclass
class ReplayReport:
    runs_planned: int = 0
    runs_executed: int = 0
    runs_skipped_missed: int = 0
    runs_skipped_overlap: int = 0
    runs_late: int = 0
    save_failures: int = 0
    duplicate_runs: int = 0
    duplicate_runs_rejected: int = 0
    injected: dict = field(default_factory=dict)
    roundtrips: int = 0
    data_fail_runs: int = 0


def run_replay(cfg: Config, data: HistoricalData, start: int, end: int, seed: int = 1, interval: int = 300,
               scenario: bool = True, roundtrip_every: int = 0, workdir: str | None = None,
               progress=None) -> tuple[State, ReplayReport]:
    """Szimulált cron futások [start, end) között. `scenario=True` esetén késések, kimaradt futások,
    dupla futások, sikertelen mentések és adat-hibák is előfordulnak (rögzített véletlen maggal)."""
    rng = random.Random(seed)
    state = new_state(cfg, start)
    engine = Engine(cfg)
    rep = ReplayReport()
    last_now = 0.0
    tmp = None
    if roundtrip_every:
        tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="replay_rt_"))
    t = start
    k = 0
    while t < end:
        rep.runs_planned += 1
        r = [rng.random() for _ in range(6)]   # mindig ugyanannyi húzás → determinisztikus forgatókönyv
        delay = 3 + r[1] * 117
        if scenario:
            if r[0] < 0.03:
                rep.runs_skipped_missed += 1
                t += interval
                continue
            if r[0] < 0.04:
                delay = 3700 + r[1] * 1700          # nagyon késett futás (> 1 óra): a belépésnek el kell maradnia
                rep.runs_late += 1
            elif r[0] < 0.14:
                delay = 600 + r[1] * 2100           # késett futás (10–45 perc)
                rep.runs_late += 1
        now = t + delay
        if now <= last_now:
            rep.runs_skipped_overlap += 1
            t += interval
            continue
        inject = None
        if scenario:
            if r[2] < 0.010:
                inject = "crosscheck"
            elif r[2] < 0.015:
                inject = "stale"
            elif r[2] < 0.018:
                inject = "fetch_error"
            elif r[2] < 0.020:
                inject = "duplicate"
        if inject:
            rep.injected[inject] = rep.injected.get(inject, 0) + 1
        run_id = f"replay-{int(t)}"
        snap = build_from_provider(cfg, ReplayProvider(data, now, inject), now, run_id, state.meta.m1_cursor)
        save_fail = scenario and r[3] < 0.02
        if save_fail:
            cp = state.checkpoint()
            engine.run(state, snap)
            state.rollback(cp)        # a mentés elbukott: mintha a futás meg sem történt volna
            rep.save_failures += 1
        else:
            res = engine.run(state, snap)
            if not res.get("skipped") and not res["data_ok"]:
                rep.data_fail_runs += 1
            if scenario and r[4] < 0.02:
                rep.duplicate_runs += 1
                again = engine.run(state, snap)     # ugyanaz a futás még egyszer
                if again.get("skipped"):
                    rep.duplicate_runs_rejected += 1
        rep.runs_executed += 1
        last_now = now
        k += 1
        if roundtrip_every and k % roundtrip_every == 0:
            save_state(state, tmp)
            state = load_state(tmp)
            rep.roundtrips += 1
        if progress and k % 500 == 0:
            progress(k, t)
        t += interval
    return state, rep
