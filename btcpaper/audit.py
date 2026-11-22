"""Független utólagos ellenőrzés (audit) egy visszajátszás eredményére.

A motortól FÜGGETLENÜL, a nyers 1 perces / 1 órás / napi gyertyákból újraszámolja:
  * minden teljesülés árát (belépés a futás percének árán, stop/gap a nyitón, cél a célárán),
  * hogy a stop/cél az ELSŐ olyan percben teljesült-e, amikor kellett (nincs kihagyott érintés),
  * díjakat, értéket, kockázatot (<= 1,5%), minimum ügyletméretet, a jelzés korát (<= 1 óra),
  * a belépési jelzés indikátorait pandas-szal, külön implementációval.
Visszaad egy hibalistát; üres lista = minden rendben.
"""
from __future__ import annotations

import json
from decimal import Decimal

import pandas as pd

from .config import Config
from .num import D, q2_down, q2_up, q8_down, q8_up
from .replay import HistoricalData
from .state import State
from .timeutil import H4, MIN, iso

TOL_VALUE = 1e-3          # az engine 4 tizedesre kerekítve naplózza az indikátorértékeket


def _stop_at(stops, t):
    cur = None
    for eff, price, kind in stops:
        if int(eff) <= t:
            cur = (D(price), kind)
    return cur


def _wilder(values: pd.Series, n: int, seed_end: int) -> pd.Series:
    """Wilder-átlag pandas ewm-mel: az első érték a [seed_end-n+1, seed_end] elemek átlaga."""
    v = values.iloc[seed_end:].copy()
    v.iloc[0] = values.iloc[seed_end - n + 1:seed_end + 1].mean()
    out = v.ewm(alpha=1 / n, adjust=False).mean()
    return pd.concat([pd.Series([float("nan")] * seed_end), out.reset_index(drop=True)], ignore_index=True)


def _ema(values: pd.Series, n: int) -> pd.Series:
    v = values.iloc[n - 1:].copy()
    v.iloc[0] = values.iloc[:n].mean()
    out = v.ewm(span=n, adjust=False).mean()
    return pd.concat([pd.Series([float("nan")] * (n - 1)), out.reset_index(drop=True)], ignore_index=True)


class IndependentSignals:
    def __init__(self, cfg: Config, data: HistoricalData):
        self.cfg = cfg
        h1 = pd.DataFrame([(c.start, float(c.open), float(c.high), float(c.low), float(c.close))
                           for c in data.h1.candles], columns=["t", "o", "h", "l", "c"])
        h1["b"] = (h1["t"] // H4) * H4
        g = h1.groupby("b")
        h4 = pd.DataFrame({"o": g["o"].first(), "h": g["h"].max(), "l": g["l"].min(), "c": g["c"].last(),
                           "n": g["t"].count()})
        self.h4 = h4
        self.d1 = pd.DataFrame([(c.start, float(c.open), float(c.high), float(c.low), float(c.close))
                                for c in data.d1.candles], columns=["t", "o", "h", "l", "c"]).set_index("t")

    def window4(self, close_time):
        w = self.h4[self.h4.index + H4 <= close_time].tail(self.cfg.i("data.lookback_4h_bars"))
        return w.reset_index()

    def atr(self, w):
        n = self.cfg.i("risk.atr_period")
        pc = w["c"].shift(1)
        tr = pd.concat([w["h"] - w["l"], (w["h"] - pc).abs(), (w["l"] - pc).abs()], axis=1).max(axis=1)
        tr.iloc[0] = w["h"].iloc[0] - w["l"].iloc[0]
        return _wilder(tr, n, n - 1)

    def p1(self, close_time, params):
        w = self.d1[self.d1.index + 86400 <= close_time].tail(self.cfg.i("data.lookback_1d_bars")).reset_index()
        ni, no, ns = int(params["entry_lookback_days"]), int(params["exit_lookback_days"]), int(params["trend_sma_days"])
        c = w["c"].iloc[-1]
        hh = w["h"].iloc[-ni - 1:-1].max()
        sma = w["c"].rolling(ns).mean().iloc[-1]
        return c > hh and c > sma, {"close_1d": c, f"donchian_high_{ni}": hh, f"sma{ns}_1d": sma}

    def p2(self, close_time, params):
        w = self.window4(close_time)
        nt, thr, win = int(params["trend_ema"]), float(params["rsi_pullback"]), int(params["pullback_window"])
        nf, nr = self.cfg.i("indicators.ema_fast"), self.cfg.i("indicators.rsi_period")
        c = w["c"]
        ef, et = _ema(c, nf), _ema(c, nt)
        d = c.diff()
        gain, loss = d.clip(lower=0).fillna(0), (-d).clip(lower=0).fillna(0)
        ag, al = _wilder(gain, nr, nr), _wilder(loss, nr, nr)
        rsi = 100 - 100 / (1 + ag / al)
        i = len(w) - 1
        trend = c[i] > et[i] and ef[i] > et[i]
        pulled = rsi.iloc[i - win:i].min() < thr
        rev = c[i] > ef[i] and c[i] > w["h"][i - 1]
        return bool(trend and pulled and rev), {f"ema{nf}_4h": ef[i], f"ema{nt}_4h": et[i], f"rsi{nr}_4h": rsi[i]}

    def p3(self, close_time, params):
        w = self.window4(close_time)
        n, k, amax = int(params["bb_period"]), float(params["bb_std"]), float(params["adx_max"])
        na = self.cfg.i("indicators.adx_period")
        c, h, lo = w["c"], w["h"], w["l"]
        mid = c.rolling(n).mean()
        sd = c.rolling(n).std(ddof=0)
        lower = mid - k * sd
        up, down = h.diff(), -lo.diff()
        pdm = up.where((up > down) & (up > 0), 0.0).fillna(0)
        mdm = down.where((down > up) & (down > 0), 0.0).fillna(0)
        pc = c.shift(1)
        tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
        atr_, ap, am = _wilder(tr, na, na), _wilder(pdm, na, na), _wilder(mdm, na, na)
        pdi, mdi = 100 * ap / atr_, 100 * am / atr_
        dx = (100 * (pdi - mdi).abs() / (pdi + mdi)).fillna(0)
        adx = _wilder(dx, na, 2 * na - 1)
        i = len(w) - 1
        return bool(c[i] < lower[i] and adx[i] < amax), {f"bb_lower_{n}": lower[i], f"bb_mid_{n}": mid[i],
                                                        f"adx{na}_4h": adx[i]}


def audit(cfg: Config, state: State, data: HistoricalData, check_signals: bool = True) -> list[str]:
    P: list[str] = []
    fee, slip = cfg.d("costs.fee_rate"), cfg.d("costs.slippage_rate")
    risk_rate, min_trade = cfg.d("risk.risk_per_trade"), cfg.d("costs.min_trade_usd")
    cap = cfg.d("portfolios.initial_capital_usd")
    m1 = data.m1
    sig = IndependentSignals(cfg, data) if check_signals else None
    last_cash = {n: cap for n in cfg.names}
    open_pos: dict = {}

    def minute_open(t):
        c = m1.get(int(t) // MIN * MIN)
        return None if c is None else c.open

    def first_touch_check(tid, pos, until, partial_done_at=None):
        stops, af, target = pos["stops"], pos["active_from"], pos["target"]
        for t in range(af, until, MIN):
            c = m1.get(t)
            if c is None:
                continue
            st = _stop_at(stops, t)
            if st and c.low <= st[0]:
                P.append(f"{tid}: a stop már {iso(t)}-kor teljesülhetett volna (low {c.low} <= {st[0]})")
                return
            if target is not None and (partial_done_at is None or t < partial_done_at) and c.high >= target:
                P.append(f"{tid}: a cél már {iso(t)}-kor teljesülhetett volna (high {c.high} >= {target})")
                return

    for t in state.trades:
        tid, n, side = t["trade_id"], t["portfolio"], t["side"]
        qty, price = D(t["qty_btc"]), D(t["price"])
        notional = q8_up(qty * price) if side == "BUY" else q8_down(qty * price)
        if D(t["notional_usd"]) != notional:
            P.append(f"{tid}: érték {t['notional_usd']} != {notional}")
        if D(t["fee_usd"]) != q8_up(notional * fee):
            P.append(f"{tid}: díj {t['fee_usd']} != {q8_up(notional * fee)}")
        d = json.loads(t["details"]) if t["details"] else {}
        time = int(t["time"])
        cash_before = last_cash[n]
        last_cash[n] = D(t["cash_after"])
        if side == "BUY":
            mo = minute_open(time)
            if mo is None or price != q8_up(mo * (1 + slip)):
                P.append(f"{tid}: vételi ár {price} != a futás percének ára + csúszás ({mo})")
            if t["reason"] == "entry":
                stop, target = D(d["stop"]), D(d["target"])
                atr = D(d["atr14_4h"])
                if stop != q2_down(D(d["signal_close"]) - cfg.d("risk.stop_atr_mult") * atr):
                    P.append(f"{tid}: stop számítás hibás")
                if target != q2_up(price + cfg.d("risk.partial_take_r") * (price - stop)):
                    P.append(f"{tid}: célár számítás hibás")
                if not (D(d["ask"]) > stop):
                    P.append(f"{tid}: belépés a stop alatti áron")
                age = int(d["signal_age_s"])
                if not (0 <= age <= cfg.i("risk.max_signal_age_seconds")):
                    P.append(f"{tid}: jelzés kora {age} s")
                if qty * (price - stop) > cash_before * risk_rate:
                    P.append(f"{tid}: kockázat > {risk_rate}")
                if notional < min_trade:
                    P.append(f"{tid}: minimum ügyletméret alatt")
                open_pos[n] = {"id": t["position_id"], "stops": [[time // MIN * MIN + MIN, d["stop"], "initial"]],
                               "active_from": time // MIN * MIN + MIN, "target": target, "partial_at": None}
                if sig is not None:
                    close_time = int(t["time"]) - age
                    params = cfg.strategy(n)
                    fn = {"donchian_breakout": sig.p1, "trend_pullback": sig.p2, "bollinger_reversion": sig.p3}[
                        params["type"]]
                    ok, vals = fn(close_time, params)
                    if not ok:
                        P.append(f"{tid}: a független újraszámolás szerint NEM volt belépési jelzés ({iso(close_time)})")
                    for k, v in vals.items():
                        ev = d["values"].get(k)
                        if ev is None or abs(float(ev) - float(v)) > TOL_VALUE + 1e-9 * abs(float(v)):
                            P.append(f"{tid}: {k} motor={ev} független={v}")
                    a = sig.atr(sig.window4(close_time if params["type"] != "donchian_breakout"
                                            else int(t["time"]))).iloc[-1]
                    if abs(float(atr) - a) > 1e-6 * a:
                        P.append(f"{tid}: ATR motor={atr} független={a}")
        else:
            pos = open_pos.get(n)
            if pos is None or pos["id"] != t["position_id"]:
                P.append(f"{tid}: eladás nyitott pozíció nélkül")
                continue
            stops = d["stops"]
            if [[int(a), str(b), c] for a, b, c in stops[:1]] != [[pos["active_from"], pos["stops"][0][1], "initial"]]:
                P.append(f"{tid}: a kezdő stop eltér a belépéskorinál")
            pr = [D(x[1]) for x in stops]
            if any(b < a for a, b in zip(pr, pr[1:])):
                P.append(f"{tid}: a stop tágult")
            pos["stops"] = stops
            r = t["reason"]
            if r in ("stop", "trailing"):
                c = m1.get(time)
                st = _stop_at(stops, time)
                if c is None or st is None or c.low > st[0]:
                    P.append(f"{tid}: stop teljesülés olyan percben, ahol nem érte el a stopot")
                else:
                    exp = q8_down((c.open if c.open <= st[0] else st[0]) * (1 - slip))
                    if price != exp:
                        P.append(f"{tid}: stop ár {price} != {exp}")
                    if (st[1] == "trailing") != (r == "trailing"):
                        P.append(f"{tid}: stop típus eltér ({st[1]} vs {r})")
                first_touch_check(tid, pos, time, pos["partial_at"])
                open_pos.pop(n)
            elif r == "target_partial":
                c = m1.get(time)
                st = _stop_at(stops, time)
                if c is None or c.high < pos["target"] or c.low <= st[0] or price != pos["target"]:
                    P.append(f"{tid}: részleges cél teljesülése hibás")
                first_touch_check(tid, pos, time)
                pos["partial_at"] = time
            elif r in ("signal", "kill_switch"):
                mo = minute_open(time)
                if mo is None or price != q8_down(mo * (1 - slip)):
                    P.append(f"{tid}: eladási ár {price} != futás percének ára − csúszás ({mo})")
                # a motor a futáskor csak a lezárt (+türelmi idő) perceket ismeri
                known = (time - cfg.i("data.candle_close_grace_seconds")) // MIN * MIN
                first_touch_check(tid, pos, known, pos["partial_at"])
                open_pos.pop(n)
            elif r == "target":
                open_pos.pop(n)
            else:
                P.append(f"{tid}: ismeretlen ok {r}")

    # a még nyitott pozíciók: a feldolgozott percekben nem lehetett stop/cél érintés
    for n, pos in open_pos.items():
        p = state.portfolios[n].position
        if p is None:
            P.append(f"{n}: a napló szerint nyitott pozíció, az állapot szerint nincs")
            continue
        pos["stops"] = [[a, str(b), c] for a, b, c in p.stops]
        pos["target"] = p.target if pos["partial_at"] is None else None
        first_touch_check(f"{n} (nyitott)", pos, state.meta.m1_cursor)
    return P


__all__ = ["audit", "IndependentSignals", "Decimal"]
