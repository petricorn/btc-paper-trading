"""Piaci pillanatkép egy futáshoz.

Az élő futás és a visszajátszás UGYANEZT a kódot használja: csak az adatszolgáltató (provider)
különbözik (élő API vs. letöltött múltbeli adat). Az ellenőrzések (hiány, duplikátum, lezártság,
frissesség, kereszt-ellenőrzés) itt történnek, mindkét esetben azonosan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from .candles import aggregate_4h, check_series, closed_only
from .config import Config
from .models import Candle, Quote, RefPrice
from .timeutil import D1, H1, H4, MIN, iso


class Provider(Protocol):
    def candles(self, gran: int, start: int, end: int) -> list[Candle]: ...
    def quote(self) -> Quote: ...
    def ref_price(self) -> RefPrice: ...
    def clock_offset(self) -> float: ...   # helyi óra − szerveróra (mp), ugyanabban a pillanatban mérve


@dataclass
class RawData:
    m1: list | None = None
    h1: list | None = None
    d1: list | None = None
    quote: Quote | None = None
    ref: RefPrice | None = None
    clock_offset: float | None = None
    errors: list = field(default_factory=list)


@dataclass
class Snapshot:
    now: float
    run_id: str
    m1: dict | None                   # kezdőidő → lezárt 1 perces gyertya (a kurzortól)
    m1_window_end: int                # a feldolgozható percek felső határa (kizáró)
    h4: list
    d1: list
    quote: Quote | None
    ref: RefPrice | None
    issues: list = field(default_factory=list)     # döntést blokkoló problémák
    notes: list = field(default_factory=list)      # nem blokkoló megjegyzések
    metrics: dict = field(default_factory=dict)
    m1_issue: bool = False            # az 1 perces adat nem megbízható (nem dolgozzuk fel)


def fetch_ranges(cfg: Config, now: float, cursor: int) -> dict:
    """Milyen időszakot kérünk le az egyes idősíkokból. Élőben és visszajátszásban azonos."""
    n4 = cfg.i("data.lookback_4h_bars")
    n1d = cfg.i("data.lookback_1d_bars")
    catch = cfg.i("data.max_m1_catchup_minutes")
    now_i = int(now)
    m1_end = min(now_i, cursor + catch * MIN)
    h1_start = (now_i // H4) * H4 - (n4 + 2) * H4
    d1_start = (now_i // D1) * D1 - (n1d + 2) * D1
    return {"m1": (cursor, m1_end), "h1": (h1_start, now_i), "d1": (d1_start, now_i)}


def collect_raw(cfg: Config, provider: Provider, now: float, cursor: int) -> RawData:
    raw = RawData()
    rng = fetch_ranges(cfg, now, cursor)
    for key, gran in (("m1", MIN), ("h1", H1), ("d1", D1)):
        a, b = rng[key]
        if b < a:
            setattr(raw, key, [])
            continue
        try:
            setattr(raw, key, provider.candles(gran, a, b))
        except Exception as e:  # noqa: BLE001 – minden adathiba naplózva, nincs döntés
            raw.errors.append(f"{key} letöltés hiba: {e}")
    for attr, fn in (("quote", provider.quote), ("ref", provider.ref_price), ("clock_offset", provider.clock_offset)):
        try:
            setattr(raw, attr, fn())
        except Exception as e:  # noqa: BLE001
            raw.errors.append(f"{attr} hiba: {e}")
    return raw


def _recent(t: int, now: float, hours: int) -> bool:
    return t >= now - hours * 3600


def build_snapshot(cfg: Config, now: float, run_id: str, cursor: int, raw: RawData) -> Snapshot:
    grace = cfg.i("data.candle_close_grace_seconds")
    max_age = cfg.i("data.max_data_age_seconds")
    block_h = cfg.i("data.decision_gap_block_hours")
    issues: list[str] = list(raw.errors)
    notes: list[str] = []
    metrics: dict = {}

    # ---- 1 perces gyertyák (stop/cél teljesüléshez)
    m1_map = None
    m1_issue = False
    window_end = ((int(now) - grace) // MIN) * MIN
    window_end = min(window_end, fetch_ranges(cfg, now, cursor)["m1"][1] // MIN * MIN)
    if raw.m1 is None:
        m1_issue = True
    else:
        chk = check_series(closed_only(raw.m1, MIN, now, grace), MIN)
        if chk.duplicates or chk.bad or chk.misaligned:
            m1_issue = True
            issues.append(f"1m hibás adat: duplikált={len(chk.duplicates)} hibás={len(chk.bad)} "
                          f"rácson kívüli={len(chk.misaligned)}")
        else:
            m1_map = {c.start: c for c in chk.candles if c.start >= cursor}

    # ---- 1 órás → 4 órás gyertyák
    h4: list[Candle] = []
    if raw.h1 is None:
        issues.append("1H adat nem érhető el")
    else:
        chk = check_series(closed_only(raw.h1, H1, now, grace), H1)
        if chk.duplicates or chk.bad or chk.misaligned:
            issues.append(f"1H hibás adat: duplikált={chk.duplicates[:3]} hibás={chk.bad[:3]}")
        expected_last = ((int(now) - grace) // H1) * H1 - H1
        last = chk.candles[-1].start if chk.candles else None
        tail_missing = [] if last is None else list(range(last + H1, expected_last + 1, H1))
        if last is None:
            issues.append("1H adat üres")
        for g in chk.gaps + tail_missing:
            if _recent(g, now, block_h):
                issues.append(f"1H hiány (friss): {iso(g)}")
                break
        old = [g for g in chk.gaps if not _recent(g, now, block_h)]
        if old:
            notes.append(f"1H régi hiány elfogadva: {len(old)} db, első {iso(old[0])}")
        h4_all, incomplete = aggregate_4h(chk.candles, now, grace)
        if incomplete:
            recent_inc = [b for b in incomplete if _recent(b, now, block_h)]
            if recent_inc:
                issues.append(f"4H hiányos gyertya (friss): {iso(recent_inc[-1])}")
        h4 = h4_all[-cfg.i("data.lookback_4h_bars"):]
        exp4 = ((int(now) - grace) // H4) * H4 - H4
        if h4 and h4[-1].start != exp4:
            issues.append(f"4H utolsó lezárt gyertya hiányzik (várt {iso(exp4)}, van {iso(h4[-1].start)})")

    # ---- napi gyertyák
    d1: list[Candle] = []
    if raw.d1 is None:
        issues.append("1D adat nem érhető el")
    else:
        chk = check_series(closed_only(raw.d1, D1, now, grace), D1)
        if chk.duplicates or chk.bad or chk.misaligned:
            issues.append(f"1D hibás adat: duplikált={chk.duplicates[:3]} hibás={chk.bad[:3]}")
        expected_last = ((int(now) - grace) // D1) * D1 - D1
        last = chk.candles[-1].start if chk.candles else None
        if last is None or last < expected_last:
            issues.append("1D utolsó lezárt gyertya hiányzik")
        for g in chk.gaps:
            if _recent(g, now, block_h):
                issues.append(f"1D hiány (friss): {iso(g)}")
                break
        old = [g for g in chk.gaps if not _recent(g, now, block_h)]
        if old:
            notes.append(f"1D régi hiány elfogadva: {len(old)} db")
        d1 = chk.candles[-cfg.i("data.lookback_1d_bars"):]

    # ---- frissesség és kereszt-ellenőrzés
    q, ref = raw.quote, raw.ref
    if q is not None:
        age = now - q.time
        metrics["ticker_age_s"] = round(age, 1)
        metrics["cb_last"] = q.last
        if age > max_age:
            issues.append(f"Coinbase ár régi: {age:.0f} s")
        if age < -max_age:
            issues.append(f"Coinbase ár ideje a jövőben: {age:.0f} s")
        if not (q.bid > 0 and q.ask > 0 and q.bid <= q.ask):
            issues.append(f"Coinbase ticker ellentmondásos: bid={q.bid} ask={q.ask}")
    elif not any("quote" in e for e in issues):
        issues.append("Coinbase ár nem érhető el")
    if ref is not None:
        metrics["kraken_last"] = ref.price
        rage = now - ref.time
        if rage > max_age:
            issues.append(f"Kraken ár régi: {rage:.0f} s")
    if q is not None and ref is not None and ref.price > 0:
        diff = abs(q.last - ref.price) / ref.price
        metrics["crosscheck_diff"] = round(float(diff), 6)
        if diff > cfg.d("data.crosscheck_max_diff"):
            issues.append(f"Kereszt-ellenőrzés: eltérés {float(diff) * 100:.3f}% "
                          f"(Coinbase {q.last}, Kraken {ref.price})")
    elif q is not None:
        issues.append("Kereszt-ellenőrzés nem végezhető el (nincs Kraken ár)")
    if raw.clock_offset is not None:
        skew = raw.clock_offset
        metrics["clock_skew_s"] = round(skew, 2)
        if abs(skew) > cfg.i("data.max_clock_skew_seconds"):
            issues.append(f"Óraeltérés a Coinbase szerverhez: {skew:.1f} s")

    return Snapshot(now=now, run_id=run_id, m1=m1_map, m1_window_end=window_end, h4=h4, d1=d1, quote=q, ref=ref,
                    issues=issues, notes=notes, metrics=metrics, m1_issue=m1_issue)


def build_from_provider(cfg: Config, provider: Provider, now: float, run_id: str, cursor: int) -> Snapshot:
    return build_snapshot(cfg, now, run_id, cursor, collect_raw(cfg, provider, now, cursor))


__all__ = ["Snapshot", "RawData", "build_snapshot", "collect_raw", "build_from_provider", "fetch_ranges", "Decimal"]
