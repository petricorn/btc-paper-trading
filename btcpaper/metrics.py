"""Teljesítménymutatók a trade-naplóból és a tőkegörbéből.

* Sharpe: napi hozamokból (UTC nap utolsó tőkeértéke), évesítve √365-tel, kockázatmentes hozam 0.
* Max drawdown: a futásonkénti (4 órás) tőkegörbe legnagyobb visszaesése a saját csúcsához képest.
* Win rate, profit factor: lezárt kötésekből (belépés + összes eladás = 1 kötés), díjak után.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from decimal import Decimal


@dataclass
class RoundTrip:
    portfolio: str
    position_id: str
    entry_time: int
    exit_time: int
    pnl: float
    equity_before: float

    @property
    def ret(self) -> float:
        return self.pnl / self.equity_before if self.equity_before else 0.0


def round_trips(trades: list, portfolio: str) -> list[RoundTrip]:
    out = []
    cur = None
    for t in trades:
        if t["portfolio"] != portfolio:
            continue
        if t["side"] == "BUY" and t["reason"] == "entry":
            cash_before = Decimal(t["cash_after"]) + Decimal(t["notional_usd"]) + Decimal(t["fee_usd"])
            cur = {"id": t["position_id"], "entry": int(t["time"]), "pnl": Decimal(0), "eq": float(cash_before),
                   "cost": Decimal(t["notional_usd"]) + Decimal(t["fee_usd"])}
        elif t["side"] == "SELL" and cur is not None and t["position_id"] == cur["id"]:
            cur["pnl"] += Decimal(t["pnl_usd"])
            if Decimal(t["btc_after"]) == 0:
                out.append(RoundTrip(portfolio, cur["id"], cur["entry"], int(t["time"]), float(cur["pnl"]),
                                     cur["eq"]))
                cur = None
    return out


def daily_equity(points: list[tuple[int, float]]) -> list[tuple[int, float]]:
    """[(idő, tőke)] → [(nap kezdete, a nap utolsó tőkeértéke)]"""
    days: dict[int, float] = {}
    for t, e in points:
        days[(int(t) // 86400) * 86400] = e
    return sorted(days.items())


def daily_returns(points: list[tuple[int, float]], start: int, end: int) -> list[float]:
    d = [(t, e) for t, e in daily_equity(points) if start - 86400 <= t < end]
    rets = []
    for (t0, e0), (t1, e1) in zip(d, d[1:]):
        if t1 >= start and e0 > 0:
            rets.append(e1 / e0 - 1)
    return rets


def sharpe(rets: list[float]) -> float:
    if len(rets) < 2:
        return 0.0
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    sd = math.sqrt(var)
    return 0.0 if sd == 0 else m / sd * math.sqrt(365)


def max_drawdown_from_returns(rets: list[float]) -> float:
    eq = peak = 1.0
    mdd = 0.0
    for r in rets:
        eq *= 1 + r
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
    return mdd


def max_drawdown(points: list[tuple[int, float]], start: int, end: int) -> float:
    peak = None
    mdd = 0.0
    for t, e in points:
        if not (start <= t < end):
            continue
        peak = e if peak is None else max(peak, e)
        if peak > 0:
            mdd = max(mdd, 1 - e / peak)
    return mdd


@dataclass
class Stats:
    total_return: float
    cagr: float
    max_drawdown: float
    sharpe: float
    trades: int
    win_rate: float
    profit_factor: float
    days: int

    def asdict(self):
        return asdict(self)


def compute_stats(rets: list[float], trips: list[RoundTrip], mdd: float | None = None) -> Stats:
    growth = 1.0
    for r in rets:
        growth *= 1 + r
    days = len(rets)
    cagr = growth ** (365 / days) - 1 if days > 0 and growth > 0 else (-1.0 if growth <= 0 else 0.0)
    wins = [t.pnl for t in trips if t.pnl > 0]
    losses = [t.pnl for t in trips if t.pnl <= 0]
    pf = (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else (float("inf") if wins else 0.0)
    return Stats(total_return=growth - 1, cagr=cagr,
                 max_drawdown=mdd if mdd is not None else max_drawdown_from_returns(rets),
                 sharpe=sharpe(rets), trades=len(trips), win_rate=(len(wins) / len(trips)) if trips else 0.0,
                 profit_factor=pf, days=days)


def monte_carlo_drawdowns(trade_returns: list[float], n: int = 10000, seed: int = 7) -> dict:
    """A kötések sorrendjének keverése: max drawdown eloszlás (a kötésenkénti hozamok szorzatán)."""
    import random
    rng = random.Random(seed)
    if not trade_returns:
        return {"n": 0}
    dds = []
    r = list(trade_returns)
    for _ in range(n):
        rng.shuffle(r)
        dds.append(max_drawdown_from_returns(r))
    dds.sort()

    def pct(p):
        return dds[min(len(dds) - 1, int(p / 100 * len(dds)))]

    return {"n": n, "trades": len(r), "p5": pct(5), "p50": pct(50), "p95": pct(95), "max": dds[-1],
            "actual_order": max_drawdown_from_returns(trade_returns)}
