"""Időkezelés: minden UTC-ben (epoch másodperc), megjelenítés Europe/Budapest szerint."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MIN = 60
H1 = 3600
H4 = 4 * 3600
D1 = 86400
BUDAPEST = ZoneInfo("Europe/Budapest")


def floor_to(ts: float, step: int) -> int:
    return int(ts // step) * step


def ceil_to(ts: float, step: int) -> int:
    f = floor_to(ts, step)
    return f if f == ts else f + step


def iso(ts: float) -> str:
    """UTC ISO-8601, pl. 2026-10-01T00:00:00Z (tört másodperc nélkül)."""
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str) -> float:
    """ISO idő → epoch. Kezeli a nanoszekundumos törtet (Coinbase) és a 'Z'-t."""
    t = text.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    if "." in t:
        head, rest = t.split(".", 1)
        frac = ""
        i = 0
        while i < len(rest) and rest[i].isdigit():
            frac += rest[i]
            i += 1
        tz = rest[i:]
        t = head + "." + (frac[:6].ljust(6, "0")) + tz
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def budapest(ts: float, fmt: str = "%Y-%m-%d %H:%M") -> str:
    return datetime.fromtimestamp(int(ts), timezone.utc).astimezone(BUDAPEST).strftime(fmt)


def budapest_hour(ts: float) -> int:
    return datetime.fromtimestamp(int(ts), timezone.utc).astimezone(BUDAPEST).hour
