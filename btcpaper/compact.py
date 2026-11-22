"""Tömör, memóriatakarékos gyertyatár hosszú időszakhoz (több millió 1 perces gyertya).

Az árak egész centben (int64) tárolódnak, így a Decimal-ra visszaalakítás PONTOS
(pl. 8346869 → Decimal('83468.69')). A tömböket .npy fájlokba mentjük, és memory-map módban
töltjük be, így több párhuzamos folyamat ugyanazt a memóriát használja.
"""
from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

import numpy as np

from .models import Candle

FIELDS = ("start", "open", "high", "low", "close")
_ZERO = Decimal(0)


def to_cents(text: str) -> int:
    d = Decimal(text) * 100
    if d != d.to_integral_value():
        raise ValueError(f"az ár nem egész cent: {text}")
    return int(d)


def _cents(v) -> Decimal:
    return Decimal(int(v)).scaleb(-2)


class CompactSeries:
    def __init__(self, arrays: dict):
        self.a = arrays
        self.starts = arrays["start"]

    def __len__(self):
        return len(self.starts)

    def _candle(self, i: int) -> Candle:
        a = self.a
        return Candle(start=int(a["start"][i]), open=_cents(a["open"][i]), high=_cents(a["high"][i]),
                      low=_cents(a["low"][i]), close=_cents(a["close"][i]), volume=_ZERO)

    def range(self, start: int, end: int) -> list[Candle]:
        i = int(np.searchsorted(self.starts, start, side="left"))
        j = int(np.searchsorted(self.starts, end, side="right"))
        return [self._candle(k) for k in range(i, j)]

    def get(self, t: int) -> Candle | None:
        i = int(np.searchsorted(self.starts, t, side="left"))
        if i < len(self.starts) and int(self.starts[i]) == t:
            return self._candle(i)
        return None

    @property
    def candles(self) -> list[Candle]:
        """Az összes gyertya listaként (csak kisebb sorozatokra, pl. 1h/1d)."""
        return [self._candle(k) for k in range(len(self.starts))]

    @property
    def first(self) -> int:
        return int(self.starts[0])

    @property
    def last(self) -> int:
        return int(self.starts[-1])

    # ------------------------------------------------------------ építés / mentés
    @classmethod
    def from_csvs(cls, paths: list[Path]) -> "CompactSeries":
        cols = {f: [] for f in FIELDS}
        for p in paths:
            with Path(p).open(encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    cols["start"].append(int(row["start"]))
                    for f in FIELDS[1:]:
                        cols[f].append(to_cents(row[f]))
        arrays = {f: np.asarray(v, dtype=np.int64) for f, v in cols.items()}
        order = np.argsort(arrays["start"], kind="stable")
        arrays = {f: v[order] for f, v in arrays.items()}
        if len(arrays["start"]) > 1 and np.any(np.diff(arrays["start"]) <= 0):
            raise ValueError("duplikált vagy rendezetlen kezdőidő a gyertyatárban")
        return cls(arrays)

    def save(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        for f in FIELDS:
            np.save(folder / f"{f}.npy", self.a[f])

    @classmethod
    def load(cls, folder: Path) -> "CompactSeries":
        return cls({f: np.load(folder / f"{f}.npy", mmap_mode="r") for f in FIELDS})


def load_full(folder: str | Path, product: str = "BTC-USD"):
    """A data/full mappa betöltése HistoricalData-ként (1m tömören, 1h/1d szintén)."""
    from .replay import HistoricalData
    folder = Path(folder)
    series = {}
    for key, src in (("m1", sorted((folder / "m1").glob("*.csv"))),
                     ("h1", [folder / f"coinbase_{product}_3600.csv"]),
                     ("d1", [folder / f"coinbase_{product}_86400.csv"])):
        cache = folder / f"npy_{key}"
        stamp = cache / "SOURCES.txt"
        sig = "\n".join(f"{p.name} {p.stat().st_size}" for p in src)
        if stamp.exists() and stamp.read_text(encoding="utf-8") == sig:
            series[key] = CompactSeries.load(cache)
        else:
            s = CompactSeries.from_csvs(src)
            s.save(cache)
            stamp.write_text(sig, encoding="utf-8")
            series[key] = CompactSeries.load(cache)
    from .replay import Series
    # az 1h/1d sorozat kicsi: kész Candle-objektumokkal gyorsabb (minden futás ~2400 1h gyertyát kér)
    return HistoricalData(m1=series["m1"], h1=Series(series["h1"].candles), d1=Series(series["d1"].candles))
