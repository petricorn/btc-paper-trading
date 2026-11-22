"""A három stratégiajelölt determinisztikus jelzései. Csak LEZÁRT gyertyákból számolnak.

Minden stratégia a saját idősíkja legutolsó lezárt gyertyáját értékeli:
  P1: napi (1D) gyertya, P2 és P3: 4 órás (4H) gyertya.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from . import indicators as ind
from .config import Config
from .models import Candle
from .num import D
from .timeutil import D1, H4


@dataclass
class Evaluation:
    bar_start: int
    bar_close_time: int          # a gyertya vége (= a jelzés időpontja)
    close: Decimal               # a jelzés gyertyájának záróára
    entry: bool
    exit: bool
    values: dict = field(default_factory=dict)
    note: str = ""


class MarketContext:
    """Egy futás lezárt 4H és 1D gyertyái és a rájuk számolt indikátorok (egyszer számolva)."""

    def __init__(self, cfg: Config, h4: list[Candle], d1: list[Candle]):
        self.cfg = cfg
        self.h4 = h4
        self.d1 = d1
        self._cache: dict = {}

    def series(self, tf: str, what: str) -> list[float]:
        key = (tf, what)
        if key not in self._cache:
            bars = self.h4 if tf == "4h" else self.d1
            self._cache[key] = [float(getattr(b, what)) for b in bars]
        return self._cache[key]

    def cached(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    def atr4h(self) -> list:
        n = self.cfg.i("risk.atr_period")
        return self.cached(("atr4h", n), lambda: ind.atr(self.series("4h", "high"), self.series("4h", "low"),
                                                          self.series("4h", "close"), n))

    def last_atr4h(self) -> float | None:
        a = self.atr4h()
        return a[-1] if a else None


def _r(x):
    return None if x is None else round(x, 4)


class Strategy:
    timeframe = "4h"

    def __init__(self, name: str, cfg: Config):
        self.name = name
        self.cfg = cfg
        self.params = cfg.strategy(name)

    def bars(self, ctx: MarketContext) -> list[Candle]:
        return ctx.h4 if self.timeframe == "4h" else ctx.d1

    def gran(self) -> int:
        return H4 if self.timeframe == "4h" else D1

    def evaluate(self, ctx: MarketContext) -> Evaluation | None:
        bars = self.bars(ctx)
        if not bars:
            return None
        last = bars[-1]
        ev = Evaluation(bar_start=last.start, bar_close_time=last.start + self.gran(), close=last.close,
                        entry=False, exit=False)
        self._evaluate(ctx, bars, ev)
        return ev

    def _evaluate(self, ctx, bars, ev):  # pragma: no cover
        raise NotImplementedError


class DonchianBreakout(Strategy):
    """P1: napi záró a megelőző N nap csúcsa fölött ÉS napi záró > SMA200 → vétel.
    Kiszállási jelzés: napi záró a megelőző M nap mélypontja alatt."""
    timeframe = "1d"

    def _evaluate(self, ctx, bars, ev):
        n_in = int(self.params["entry_lookback_days"])
        n_out = int(self.params["exit_lookback_days"])
        n_sma = int(self.params["trend_sma_days"])
        i = len(bars) - 1
        if i < max(n_in, n_out) or len(bars) < n_sma:
            ev.note = "kevés adat"
            return
        highs = ctx.series("1d", "high")
        lows = ctx.series("1d", "low")
        closes = ctx.series("1d", "close")
        sma_v = ctx.cached(("sma1d", n_sma), lambda: ind.sma(closes, n_sma))[i]
        hh = max(highs[i - n_in:i])
        ll = min(lows[i - n_out:i])
        c = closes[i]
        ev.entry = c > hh and sma_v is not None and c > sma_v
        ev.exit = c < ll
        ev.values = {"close_1d": _r(c), f"donchian_high_{n_in}": _r(hh), f"donchian_low_{n_out}": _r(ll),
                     f"sma{n_sma}_1d": _r(sma_v)}


class TrendPullback(Strategy):
    """P2 (4H): emelkedő trend (záró > EMA_trend és EMA20 > EMA_trend), az előző `window` gyertya
    valamelyikén RSI14 < küszöb (visszahúzódás), és a mostani gyertya visszafordul
    (záró > EMA20 és záró > előző gyertya csúcsa) → vétel. Kiszállási jelzés: záró < EMA_trend."""
    timeframe = "4h"

    def _evaluate(self, ctx, bars, ev):
        n_tr = int(self.params["trend_ema"])
        thr = float(D(self.params["rsi_pullback"]))
        w = int(self.params["pullback_window"])
        n_fast = ctx.cfg.i("indicators.ema_fast")
        n_rsi = ctx.cfg.i("indicators.rsi_period")
        closes = ctx.series("4h", "close")
        highs = ctx.series("4h", "high")
        i = len(bars) - 1
        e_fast = ctx.cached(("ema4h", n_fast), lambda: ind.ema(closes, n_fast))
        e_tr = ctx.cached(("ema4h", n_tr), lambda: ind.ema(closes, n_tr))
        r = ctx.cached(("rsi4h", n_rsi), lambda: ind.rsi(closes, n_rsi))
        prev_rsi = r[i - w:i] if i - w >= 0 else []
        if e_tr[i] is None or e_fast[i] is None or len(prev_rsi) < w or any(v is None for v in prev_rsi):
            ev.note = "kevés adat"
            return
        c = closes[i]
        trend = c > e_tr[i] and e_fast[i] > e_tr[i]
        min_rsi = min(prev_rsi)
        pulled = min_rsi < thr
        reversal = c > e_fast[i] and c > highs[i - 1]
        ev.entry = trend and pulled and reversal
        ev.exit = c < e_tr[i]
        ev.values = {"close_4h": _r(c), f"ema{n_fast}_4h": _r(e_fast[i]), f"ema{n_tr}_4h": _r(e_tr[i]),
                     f"rsi{n_rsi}_4h": _r(r[i]), f"min_rsi_prev{w}": _r(min_rsi), "prev_high_4h": _r(highs[i - 1]),
                     "trend": trend, "pullback": pulled, "reversal": reversal}


class BollingerReversion(Strategy):
    """P3 (4H): csak oldalazó piacon (ADX14 < küszöb), záró az alsó Bollinger-szalag alatt → vétel.
    Kiszállási jelzés: záró >= középvonal (SMA)."""
    timeframe = "4h"

    def _evaluate(self, ctx, bars, ev):
        n = int(self.params["bb_period"])
        k = float(D(self.params["bb_std"]))
        amax = float(D(self.params["adx_max"]))
        n_adx = ctx.cfg.i("indicators.adx_period")
        closes = ctx.series("4h", "close")
        i = len(bars) - 1
        mid, up, lo = ctx.cached(("bb4h", n, k), lambda: ind.bollinger(closes, n, k))
        a = ctx.cached(("adx4h", n_adx), lambda: ind.adx(ctx.series("4h", "high"), ctx.series("4h", "low"),
                                                          closes, n_adx))
        if mid[i] is None or a[i] is None:
            ev.note = "kevés adat"
            return
        c = closes[i]
        ev.entry = c < lo[i] and a[i] < amax
        ev.exit = c >= mid[i]
        ev.values = {"close_4h": _r(c), f"bb_lower_{n}": _r(lo[i]), f"bb_mid_{n}": _r(mid[i]),
                     f"bb_upper_{n}": _r(up[i]), f"adx{n_adx}_4h": _r(a[i])}


STRATEGY_CLASSES = {
    "donchian_breakout": DonchianBreakout,
    "trend_pullback": TrendPullback,
    "bollinger_reversion": BollingerReversion,
}


def build_strategies(cfg: Config) -> dict[str, Strategy]:
    out = {}
    for name in cfg.names:
        t = cfg.strategy(name)["type"]
        if t in STRATEGY_CLASSES:
            out[name] = STRATEGY_CLASSES[t](name, cfg)
    return out
