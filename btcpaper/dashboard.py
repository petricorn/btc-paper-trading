"""A webes felület (docs/) adatfájlja: a bot állapotából (state/ mappa) egyetlen JSON.

A felület csak ezt az egy fájlt olvassa. Élőben (Fázis 3) a bot minden futás végén elkészíti, és a
"bot-state" ágra menti; a felület onnan tölti be. Demóként egy visszajátszás állapotából is készíthető.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from .config import Config
from .metrics import compute_stats, daily_returns, max_drawdown, round_trips
from .num import D
from .state import State
from .timeutil import iso

MAX_POINTS = 1500          # tőkegörbe-pontok portfóliónként (ritkítva)
MAX_TRADES = 300
MAX_RUNS = 200
MAX_SIGNALS = 60

LABELS = {
    "P1": "Donchian-kitörés (napi)",
    "P2": "Trend + visszahúzódás (4H)",
    "P3": "Bollinger mean reversion (4H)",
    "B1": "Buy & hold (mérce)",
    "B2": "Heti DCA (mérce)",
}
REASONS = {
    "entry": "belépés", "stop": "stop", "trailing": "trailing stop", "target_partial": "részleges cél",
    "target": "cél", "signal": "kiszállási jelzés", "kill_switch": "kill switch", "buy_and_hold": "buy & hold vétel",
    "dca": "DCA részlet",
}


def _f(x) -> float | None:
    if x is None or x == "":
        return None
    return float(D(x))


def _thin(points: list, n: int) -> list:
    if len(points) <= n:
        return points
    step = len(points) / n
    out = [points[int(i * step)] for i in range(n)]
    if out[-1] != points[-1]:
        out.append(points[-1])
    return out


def _conditions(name: str, cfg: Config, values: dict, entry: bool) -> list[dict]:
    """A belépési feltételek emberi nyelven, teljesült-e mindegyik (a motor naplózott értékeiből)."""
    v = values or {}
    p = cfg.strategy(name)
    out = []
    try:
        if p["type"] == "donchian_breakout":
            n_in, n_sma = p["entry_lookback_days"], p["trend_sma_days"]
            c, hh, sma = v.get("close_1d"), v.get(f"donchian_high_{n_in}"), v.get(f"sma{n_sma}_1d")
            out.append({"label": f"Napi záró a {n_in} napos csúcs fölött", "ok": c is not None and hh is not None and c > hh,
                        "detail": f"{c:,.0f} vs {hh:,.0f}" if c and hh else "kevés adat"})
            out.append({"label": f"Napi záró az SMA{n_sma} fölött (emelkedő trend)",
                        "ok": c is not None and sma is not None and c > sma,
                        "detail": f"{c:,.0f} vs {sma:,.0f}" if c and sma else "kevés adat"})
        elif p["type"] == "trend_pullback":
            nt = p["trend_ema"]
            out.append({"label": f"Emelkedő trend (záró és EMA20 az EMA{nt} fölött)", "ok": bool(v.get("trend")),
                        "detail": f"záró {v.get('close_4h', 0):,.0f} · EMA{nt} {v.get(f'ema{nt}_4h', 0):,.0f}"})
            out.append({"label": f"Visszahúzódás: RSI14 {p['rsi_pullback']} alatt volt",
                        "ok": bool(v.get("pullback")),
                        "detail": f"legkisebb RSI {v.get(f'min_rsi_prev{p['pullback_window']}', 0):.1f}"})
            out.append({"label": "Visszafordulás (záró EMA20 és előző csúcs fölött)", "ok": bool(v.get("reversal")),
                        "detail": f"záró {v.get('close_4h', 0):,.0f} · előző csúcs {v.get('prev_high_4h', 0):,.0f}"})
        elif p["type"] == "bollinger_reversion":
            n = p["bb_period"]
            c, lo, adx = v.get("close_4h"), v.get(f"bb_lower_{n}"), v.get("adx14_4h")
            out.append({"label": "Záró az alsó Bollinger-szalag alatt", "ok": c is not None and lo is not None and c < lo,
                        "detail": f"{c:,.0f} vs {lo:,.0f}" if c and lo else "kevés adat"})
            out.append({"label": f"Oldalazó piac (ADX14 < {p['adx_max']})",
                        "ok": adx is not None and adx < float(D(p["adx_max"])),
                        "detail": f"ADX {adx:.1f}" if adx is not None else "kevés adat"})
    except (TypeError, ValueError, KeyError):
        out.append({"label": "Értékek nem olvashatók", "ok": False, "detail": ""})
    for o in out:   # magyar számformátum: ezres tagolás szóközzel, tizedesvessző
        o["detail"] = o["detail"].replace(",", " ").replace(".", ",")
    return out


def build_dashboard(state: State, cfg: Config, source: str, note: str = "") -> dict:
    names = cfg.names
    cap = float(cfg.d("portfolios.initial_capital_usd"))
    eq_points = {n: [] for n in names}
    price_points = []
    for e in state.equity:
        t = int(e["time"])
        eq_points[e["portfolio"]].append((t, float(D(e["equity"]))))
        if e["portfolio"] == names[0]:
            price_points.append((t, float(D(e["price"]))))
    last_price = price_points[-1][1] if price_points else None
    last_time = price_points[-1][0] if price_points else int(state.meta.last_run_time)
    first_time = price_points[0][0] if price_points else last_time

    def change(sec):
        if not price_points:
            return None
        past = [p for t, p in price_points if t <= last_time - sec]
        return (last_price / past[-1] - 1) if past else None

    portfolios = []
    for n in names:
        p = state.portfolios[n]
        pts = eq_points[n]
        equity = pts[-1][1] if pts else float(p.cash)
        rets = daily_returns(pts, first_time, last_time + 86400)
        trips = round_trips(state.trades, n)
        st = compute_stats(rets, trips, max_drawdown(pts, 0, 2 ** 40))
        pos = None
        if p.position is not None and last_price is not None:
            q = p.position
            cost_part = float(q.cost_total) * float(q.qty) / float(q.initial_qty)
            value = float(q.qty) * last_price
            pos = {"entry_time": iso(q.entry_time), "entry_price": float(q.entry_price), "qty": float(q.qty),
                   "stop": float(q.current_stop), "initial_stop": float(q.initial_stop),
                   "target": _f(q.target), "trailing": q.trailing_active, "value": value,
                   "unrealized": value - cost_part, "r": (last_price - float(q.entry_price)) / float(q.r_value)}
        last_sig = next((s for s in reversed(state.signals) if s["portfolio"] == n), None)
        waiting = None
        if p.kind == "strategy":
            vals = json.loads(last_sig["values"]) if last_sig and last_sig.get("values") else {}
            waiting = {"bar_close": last_sig["bar_close_iso"] if last_sig else None,
                       "action": last_sig["action"] if last_sig else None,
                       "reason": last_sig["reason"] if last_sig else "",
                       "conditions": _conditions(n, cfg, vals, bool(last_sig and last_sig["entry"] in (True, "True")))}
        elif p.kind == "weekly_dca":
            waiting = {"text": f"{p.dca_done}/{cfg.strategy(n)['installments']} heti részlet megvéve"}
        else:
            waiting = {"text": "megvette az indulás napján, tart" if p.bh_done else "az első futáskor vásárol"}
        portfolios.append({
            "name": n, "label": LABELS.get(n, n), "kind": p.kind, "cash": float(p.cash), "btc": float(p.btc),
            "equity": equity, "return": equity / cap - 1, "max_drawdown": st.max_drawdown, "trades": st.trades,
            "win_rate": st.win_rate if st.trades else None,
            "profit_factor": None if not st.trades or st.profit_factor == float("inf") else st.profit_factor,
            "halted": p.halted, "halt_reason": p.halt_reason, "position": pos, "waiting": waiting,
            "equity_series": _thin(pts, MAX_POINTS),
        })

    trades = []
    for t in state.trades[-MAX_TRADES:]:
        trades.append({"time": int(t["time"]), "portfolio": t["portfolio"], "side": t["side"],
                       "reason": REASONS.get(t["reason"], t["reason"]), "qty": _f(t["qty_btc"]),
                       "price": _f(t["price"]), "value": _f(t["notional_usd"]), "fee": _f(t["fee_usd"]),
                       "pnl": _f(t["pnl_usd"]), "config": t["config_hash"]})
    runs = [{"time": int(r["time"]), "ok": r["data_ok"] in (True, "True"), "issues": r["issues"],
             "diff": _f(r.get("crosscheck_diff")), "age": _f(r.get("ticker_age_s"))}
            for r in state.runs[-MAX_RUNS:]]
    alerts = [{"time": int(m["created"]), "kind": m["kind"], "portfolio": m["portfolio"],
               "payload": m["payload"]} for m in state.outbox if m["kind"].startswith(("ALERT", "DATA"))][-30:]
    c = state.meta.counters
    return {
        "schema": 1, "source": source, "note": note, "generated": last_time, "config_hash": state.meta.config_hash,
        "initial_capital": cap, "start_time": state.meta.start_time,
        "price": {"last": last_price, "change_24h": change(86400), "change_7d": change(7 * 86400),
                  "series": _thin(price_points, MAX_POINTS)},
        "health": {"last_run": last_time, "last_ok": runs[-1]["ok"] if runs else None,
                   "last_issues": runs[-1]["issues"] if runs else "",
                   "consecutive_failures": state.meta.consecutive_failures, "runs": c.get("runs", 0),
                   "runs_data_fail": c.get("runs_data_fail", 0), "fail_crosscheck": c.get("fail_crosscheck", 0),
                   "fail_stale": c.get("fail_stale", 0), "fail_gap": c.get("fail_gap", 0),
                   "fail_fetch": c.get("fail_fetch", 0), "entries_skipped_late": c.get("entries_skipped_late", 0)},
        "portfolios": portfolios, "trades": trades, "runs": runs, "alerts": alerts,
    }


def write_dashboard(state: State, cfg: Config, path: str | Path, source: str, note: str = ""):
    data = build_dashboard(state, cfg, source, note)
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    def enc(o):
        if isinstance(o, Decimal):
            return float(o)
        raise TypeError(type(o))

    Path(path).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=enc), encoding="utf-8")
    return data
