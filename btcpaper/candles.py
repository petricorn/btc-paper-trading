"""Gyertya-ellenőrzés: duplikátum, hiány, hibás OHLC, lezártság, 1H → 4H összevonás."""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Candle
from .timeutil import H4


@dataclass
class SeriesCheck:
    candles: list[Candle]                    # időrendben, duplikátum nélkül (az első példány marad)
    duplicates: list[int] = field(default_factory=list)   # többször érkezett kezdőidők
    gaps: list[int] = field(default_factory=list)         # hiányzó kezdőidők (a sorozat belsejében)
    bad: list[int] = field(default_factory=list)          # hibás OHLC (pl. low > high)
    misaligned: list[int] = field(default_factory=list)   # nem rácsra eső kezdőidő

    @property
    def clean(self) -> bool:
        return not (self.duplicates or self.gaps or self.bad or self.misaligned)


def ohlc_ok(c: Candle) -> bool:
    return (
        c.low > 0
        and c.low <= c.open <= c.high
        and c.low <= c.close <= c.high
        and c.volume >= 0
    )


def check_series(candles: list[Candle], gran: int) -> SeriesCheck:
    seen: dict[int, Candle] = {}
    dups: list[int] = []
    bad: list[int] = []
    mis: list[int] = []
    for c in candles:
        if c.start % gran != 0:
            mis.append(c.start)
            continue
        if c.start in seen:
            dups.append(c.start)
            continue
        if not ohlc_ok(c):
            bad.append(c.start)
        seen[c.start] = c
    ordered = [seen[k] for k in sorted(seen)]
    gaps: list[int] = []
    for a, b in zip(ordered, ordered[1:]):
        t = a.start + gran
        while t < b.start:
            gaps.append(t)
            t += gran
    return SeriesCheck(ordered, sorted(set(dups)), gaps, sorted(bad), sorted(mis))


def closed_only(candles: list[Candle], gran: int, now: float, grace: int) -> list[Candle]:
    """Csak a LEZÁRT gyertyák: a gyertya vége + türelmi idő <= most."""
    return [c for c in candles if c.start + gran + grace <= now]


def aggregate(h1: list[Candle], target: int, now: float, grace: int) -> tuple[list[Candle], list[int]]:
    """1 órás lezárt gyertyákból `target` (pl. 4H) gyertya, UTC rácsra igazítva (00, 04, 08 ...).

    Csak azok a csoportok kerülnek be, amelyek teljes időtartama lezárult.
    Visszaadja a hiányos csoportok kezdőidejét is (ezeket a hívó kezeli hiányként).
    """
    if target % 3600 != 0:
        raise ValueError("target must be a multiple of 1h")
    buckets: dict[int, list[Candle]] = {}
    for c in h1:
        b = (c.start // target) * target
        buckets.setdefault(b, []).append(c)
    out: list[Candle] = []
    incomplete: list[int] = []
    per = target // 3600
    for b in sorted(buckets):
        if b + target + grace > now:
            continue   # a csoport még nem zárult le
        group = sorted(buckets[b], key=lambda x: x.start)
        if len(group) != per:
            incomplete.append(b)
        out.append(Candle(
            start=b,
            open=group[0].open,
            high=max(x.high for x in group),
            low=min(x.low for x in group),
            close=group[-1].close,
            volume=sum((x.volume for x in group), start=group[0].volume * 0),
        ))
    return out, incomplete


def aggregate_4h(h1: list[Candle], now: float, grace: int) -> tuple[list[Candle], list[int]]:
    return aggregate(h1, H4, now, grace)
