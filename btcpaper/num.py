"""Pontos pénzügyi számolás Decimal-lal (nincs lebegőpontos kerekítési hiba a könyvelésben)."""
from decimal import Decimal, ROUND_DOWN, ROUND_UP, getcontext

getcontext().prec = 40

ZERO = Decimal("0")
SAT = Decimal("0.00000001")   # 1e-8: BTC mennyiség és USD összeg pontossága
CENT = Decimal("0.01")


def D(x) -> Decimal:
    """Bármiből Decimal, float esetén a szöveges alakon át (nincs bináris zaj)."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        raise TypeError("bool is not a number")
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        return Decimal(repr(x))
    return Decimal(str(x).strip())


def q8_down(x: Decimal) -> Decimal:
    return x.quantize(SAT, rounding=ROUND_DOWN)


def q8_up(x: Decimal) -> Decimal:
    return x.quantize(SAT, rounding=ROUND_UP)


def q2_down(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_DOWN)


def q2_up(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_UP)


def s(x) -> str:
    """Decimal → szöveg mentéshez (tudományos jelölés nélkül)."""
    if x is None:
        return ""
    return format(D(x), "f")
