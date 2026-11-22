from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Candle:
    start: int          # a gyertya kezdete, UTC epoch másodperc
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True, slots=True)
class Quote:
    """Pillanatnyi ár (Coinbase ticker)."""
    bid: Decimal
    ask: Decimal
    last: Decimal
    time: float         # utolsó kötés ideje, UTC epoch
    source: str = "coinbase"


@dataclass(frozen=True, slots=True)
class RefPrice:
    """Másodlagos forrás ára a kereszt-ellenőrzéshez (Kraken)."""
    price: Decimal
    time: float
    source: str = "kraken"
