"""Az EGYETLEN eseményvezérelt motor. A backteszt/visszajátszás és az éles paper futás is ezt használja.

Egy futás menete (minden futás egy `Snapshot`-ot kap):
  1. Várakozó megbízások (stop, részleges cél) kiértékelése az utolsó ellenőrzés óta lezárult
     1 perces gyertyákon, időrendben. Ha egy percben a stop és a cél is teljesülne, a stop számít.
  2. Adatminőség: hiány, duplikátum, frissesség, kereszt-ellenőrzés. Ha bármi hibás → ebben a
     futásban nincs döntés (nincs új trade, nincs trailing-frissítés), és naplózzuk.
  3. Döntések a futás TÉNYLEGES időpontjában, az ekkor lekért áron (ask/bid) csúszással:
     kill switch, trailing stop frissítés (csak új lezárt 4H gyertyán), kiszállási jelzés,
     belépés (csak ha a jelzés óta <= 1 óra telt el, és az ár a stop fölött van), mércék (B1, B2).
  4. Tőke rögzítése, futásnapló, invariáns-ellenőrzés. Bármely hiba → a futás teljes visszagörgetése.
"""
from __future__ import annotations

import json
from decimal import Decimal

from .config import Config
from .num import D, SAT, ZERO, q2_down, q2_up, q8_down, q8_up, s
from .snapshot import Snapshot
from .state import Position, PortfolioState, State, check_invariants, InvariantError, DuplicateTradeError
from .strategies import MarketContext, build_strategies
from .timeutil import H4, MIN, ceil_to, iso

RECENT_RUN_IDS = 300


def _inc(d: dict, k: str, n: int = 1):
    d[k] = d.get(k, 0) + n


def _jsonable(v):
    if isinstance(v, Decimal):
        return s(v)
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


class Engine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.strategies = build_strategies(cfg)
        self.fee = cfg.d("costs.fee_rate")
        self.slip = cfg.d("costs.slippage_rate")
        self.min_trade = cfg.d("costs.min_trade_usd")
        self.initial = cfg.d("portfolios.initial_capital_usd")

    # ------------------------------------------------------------------ belépési pont
    def run(self, state: State, snap: Snapshot) -> dict:
        meta = state.meta
        if snap.run_id in meta.recent_run_ids:
            return {"skipped": True, "reason": f"ez a futás ({snap.run_id}) már fel lett dolgozva"}
        if snap.now <= meta.last_run_time:
            return {"skipped": True, "reason": "a futás ideje nem későbbi az utolsó feldolgozott futásnál"}
        cp = state.checkpoint()
        try:
            summary = self._run(state, snap)
            check_invariants(state, self.cfg)
        except Exception:
            state.rollback(cp)
            raise
        return summary

    # ------------------------------------------------------------------ fő logika
    def _run(self, state: State, snap: Snapshot) -> dict:
        cfg, meta = self.cfg, state.meta
        now_i = int(snap.now)
        self._now = now_i
        self._run_id = snap.run_id
        self._trades_before = len(state.trades)
        _inc(meta.counters, "runs")

        if meta.config_hash != cfg.hash:
            self._msg(state, "ALERT_PARAM", None, {"old": meta.config_hash, "new": cfg.hash},
                      f"ALERT_PARAM:{cfg.hash}:{snap.run_id}")
            meta.config_hash = cfg.hash

        processed, accepted = self._process_minutes(state, snap)

        issues = list(snap.issues)
        if not snap.m1_issue and snap.m1 is not None and meta.m1_cursor < snap.m1_window_end:
            issues.append(f"1m nincs naprakészen feldolgozva (kurzor {iso(meta.m1_cursor)}, "
                          f"várt {iso(snap.m1_window_end)}): friss hiány vagy lemaradás")
        if snap.m1_issue or snap.m1 is None:
            if not any(x.startswith("1m") or x.startswith("m1") for x in issues):
                issues.append("1m adat nem használható")
        data_ok = not issues
        self._track_failures(state, data_ok, issues)

        if data_ok:
            ctx = MarketContext(cfg, snap.h4, snap.d1)
            for name in cfg.names:
                p = state.portfolios[name]
                if p.kind == "strategy":
                    self._decide_strategy(state, p, ctx, snap)
                elif p.kind == "buy_and_hold":
                    self._buy_and_hold(state, p, snap)
                elif p.kind == "weekly_dca":
                    self._weekly_dca(state, p, snap)
            self._record_equity(state, snap)

        m = snap.metrics
        state.runs.append({
            "run_id": snap.run_id, "time": now_i, "time_iso": iso(now_i), "data_ok": data_ok,
            "issues": " | ".join(issues), "notes": " | ".join(snap.notes), "m1_processed": processed,
            "m1_gaps_accepted": accepted, "cb_last": m.get("cb_last", ""), "kraken_last": m.get("kraken_last", ""),
            "crosscheck_diff": m.get("crosscheck_diff", ""), "ticker_age_s": m.get("ticker_age_s", ""),
            "config_hash": cfg.hash,
        })
        meta.last_run_time = snap.now
        meta.last_run_id = snap.run_id
        meta.recent_run_ids.append(snap.run_id)
        del meta.recent_run_ids[:-RECENT_RUN_IDS]
        return {"skipped": False, "data_ok": data_ok, "issues": issues, "m1_processed": processed,
                "m1_gaps_accepted": accepted, "new_trades": state.trades[self._trades_before:]}

    # ------------------------------------------------------------------ 1 perces feldolgozás
    def _process_minutes(self, state: State, snap: Snapshot) -> tuple[int, int]:
        meta = state.meta
        if snap.m1 is None or snap.m1_issue:
            return 0, 0
        settle = self.cfg.i("data.m1_gap_settle_minutes") * MIN
        t = meta.m1_cursor
        processed = accepted = 0
        while t + MIN <= snap.m1_window_end:
            c = snap.m1.get(t)
            if c is None:
                if snap.now - (t + MIN) >= settle:
                    accepted += 1                     # régi hiány: abban a percben nem volt kötés
                    _inc(meta.counters, "m1_gaps_accepted")
                    t += MIN
                    continue
                break                                 # friss hiány: várunk, a következő futás újrapróbálja
            for name in self.cfg.names:
                p = state.portfolios[name]
                if p.kind == "strategy" and p.position is not None:
                    self._check_orders(state, p, c)
            processed += 1
            t += MIN
        meta.m1_cursor = t
        return processed, accepted

    def _check_orders(self, state: State, p: PortfolioState, c):
        pos = p.position
        if c.start < pos.active_from:
            return
        stop, kind = pos.stop_at(c.start)
        if c.low <= stop:
            gap = c.open <= stop
            raw = c.open if gap else stop
            price = q8_down(raw * (1 - self.slip))
            reason = "trailing" if kind == "trailing" else "stop"
            self._close(state, p, price, c.start, reason, {
                "stop": stop, "candle_start": iso(c.start), "candle_open": c.open, "candle_low": c.low,
                "gap_below_stop": gap})
            return
        if pos.target is not None and c.high >= pos.target:
            frac = self.cfg.d("risk.partial_take_fraction")
            qty = q8_down(pos.initial_qty * frac)
            target = pos.target
            pos.target = None
            if qty <= 0:
                return
            if qty >= pos.qty:
                self._close(state, p, target, c.start, "target", {"target": target, "candle_high": c.high})
                return
            if q8_down(qty * target) < self.min_trade:
                state.signals.append(self._signal_row(p.name, "4h", c.start, False, False, "partial_skipped",
                                                      "részleges zárás a minimum ügyletméret alatt", {}))
                return
            self._sell(state, p, qty, target, c.start, "target_partial",
                       {"target": target, "candle_start": iso(c.start), "candle_high": c.high},
                       f"{pos.id}:T")

    # ------------------------------------------------------------------ adatminőség, riasztás
    def _track_failures(self, state: State, ok: bool, issues: list):
        meta = state.meta
        thr = self.cfg.i("data.alert_after_failed_runs")
        if ok:
            if meta.failure_alert_sent:
                self._msg(state, "DATA_RECOVERED", None, {"failed_runs": meta.consecutive_failures},
                          f"DATA_RECOVERED:{self._run_id}")
            meta.consecutive_failures = 0
            meta.failure_alert_sent = False
            return
        meta.consecutive_failures += 1
        c = meta.counters
        _inc(c, "runs_data_fail")
        text = " ".join(issues).lower()
        if "kereszt" in text:
            _inc(c, "fail_crosscheck")
        if "régi" in text or "naprakész" in text:
            _inc(c, "fail_stale")
        if "hiány" in text or "duplik" in text or "hibás" in text:
            _inc(c, "fail_gap")
        if "hiba" in text or "nem érhető el" in text:
            _inc(c, "fail_fetch")
        if meta.consecutive_failures >= thr and not meta.failure_alert_sent:
            self._msg(state, "ALERT_DATA", None, {"failed_runs": meta.consecutive_failures, "issues": issues},
                      f"ALERT_DATA:{self._run_id}")
            meta.failure_alert_sent = True

    # ------------------------------------------------------------------ stratégiák
    def _decide_strategy(self, state: State, p: PortfolioState, ctx: MarketContext, snap: Snapshot):
        if p.halted:
            return
        q = snap.quote
        cfg = self.cfg
        equity = p.cash + p.btc * q.bid
        if equity > p.peak_equity:
            p.peak_equity = equity
        dd_lim = cfg.d("risk.kill_switch_drawdown")
        if equity <= p.peak_equity * (1 - dd_lim):
            if p.position is not None and cfg.get("risk.kill_switch_liquidate"):
                self._close(state, p, q8_down(q.bid * (1 - self.slip)), self._now, "kill_switch",
                            {"bid": q.bid, "equity": q8_down(equity), "peak": q8_down(p.peak_equity)})
            p.halted = True
            p.halt_time = self._now
            p.halt_reason = (f"kill switch: tőke {q8_down(equity)} <= csúcs {q8_down(p.peak_equity)} × "
                             f"(1 − {dd_lim})")
            self._msg(state, "ALERT_KILL", p.name, {"equity": q8_down(equity), "peak": q8_down(p.peak_equity),
                                                    "reason": p.halt_reason}, f"ALERT_KILL:{p.name}")
            return

        strat = self.strategies[p.name]
        eff = (self._now // MIN) * MIN + MIN          # módosítás a következő teljes perctől érvényes
        if p.position is not None:
            self._update_trailing(p, ctx, eff)
        ev = strat.evaluate(ctx)
        if ev is None or ev.bar_close_time <= p.last_signal_bar:
            return
        p.last_signal_bar = ev.bar_close_time
        action, reason = "none", ev.note
        if p.position is not None:
            if ev.exit:
                self._close(state, p, q8_down(q.bid * (1 - self.slip)), self._now, "signal",
                            {"bid": q.bid, "signal_bar_close": iso(ev.bar_close_time),
                             "values": _jsonable(ev.values)})
                action = "exit"
            else:
                action = "hold"
        elif ev.entry:
            action, reason = self._try_entry(state, p, ev, ctx, snap)
        else:
            action = "no_signal"
        state.signals.append(self._signal_row(p.name, strat.timeframe, ev.bar_close_time, ev.entry, ev.exit,
                                              action, reason, ev.values))

    def _update_trailing(self, p: PortfolioState, ctx: MarketContext, eff: int):
        pos = p.position
        new = [b for b in ctx.h4 if b.start > pos.last_trail_bar]
        if not new:
            return
        hc = pos.highest_close
        for b in new:
            if b.start + H4 > pos.entry_time and (hc is None or b.close > hc):
                hc = b.close
        pos.highest_close = hc
        pos.last_trail_bar = new[-1].start
        atr = ctx.last_atr4h()
        if hc is None or atr is None:
            return
        if not pos.trailing_active and hc >= pos.entry_price + self.cfg.d("risk.trail_activation_r") * pos.r_value:
            pos.trailing_active = True
        if pos.trailing_active:
            level = q2_down(hc - self.cfg.d("risk.trail_atr_mult") * D(atr))
            if level > pos.current_stop:
                pos.stops.append([eff, level, "trailing"])

    def _try_entry(self, state: State, p: PortfolioState, ev, ctx: MarketContext, snap: Snapshot):
        cfg = self.cfg
        age = self._now - ev.bar_close_time
        if age > cfg.i("risk.max_signal_age_seconds"):
            _inc(state.meta.counters, "entries_skipped_late")
            return "skip", f"késett: a jelzés óta {age // 60} perc telt el (max {cfg.i('risk.max_signal_age_seconds') // 60})"
        if p.last_exit_time:
            earliest = ceil_to(p.last_exit_time, H4) + cfg.i("risk.cooldown_bars_4h") * H4
            if ev.bar_close_time < earliest:
                return "skip", f"cooldown: legkorábbi jelzés-gyertya vége {iso(earliest)}"
        atr = ctx.last_atr4h()
        if atr is None:
            return "skip", "kevés adat az ATR-hez"
        atr_d = D(atr)
        stop = q2_down(ev.close - cfg.d("risk.stop_atr_mult") * atr_d)
        q = snap.quote
        if stop <= 0:
            return "skip", "érvénytelen stop"
        if q.ask <= stop:
            _inc(state.meta.counters, "entries_skipped_below_stop")
            return "skip", f"az ár ({q.ask}) már a stop ({stop}) alatt van"
        fill = q8_up(q.ask * (1 + self.slip))
        per_unit = fill - stop
        equity = p.cash                                     # nincs nyitott pozíció → tőke = készpénz
        risk_usd = equity * cfg.d("risk.risk_per_trade")
        qty = q8_down(min(risk_usd / per_unit, p.cash / (fill * (1 + self.fee))))
        while qty > 0 and self._buy_cost(qty, fill) > p.cash:
            qty -= SAT
        notional = q8_up(qty * fill)
        if qty <= 0 or notional < self.min_trade:
            return "skip", f"túl kicsi pozíció ({notional} USD < {self.min_trade} USD)"
        target = q2_up(fill + cfg.d("risk.partial_take_r") * per_unit)
        pos_id = f"{p.name}:{ev.bar_close_time}"
        details = {"signal_bar_close": iso(ev.bar_close_time), "signal_close": ev.close, "atr14_4h": atr_d,
                   "stop": stop, "target": target, "ask": q.ask, "risk_usd": q8_down(qty * per_unit),
                   "risk_pct": q8_down(qty * per_unit / equity * 100), "values": _jsonable(ev.values),
                   "signal_age_s": age}
        row = self._buy(state, p, qty, fill, self._now, "entry", details, f"{pos_id}:E", pos_id)
        p.position = Position(
            id=pos_id, entry_time=self._now, active_from=(self._now // MIN) * MIN + MIN, entry_price=fill,
            initial_qty=qty, qty=qty, initial_stop=stop, stops=[[(self._now // MIN) * MIN + MIN, stop, "initial"]],
            target=target, r_value=per_unit, cost_total=row["notional_usd"] + row["fee_usd"],
            signal_bar_close=ev.bar_close_time, last_trail_bar=ctx.h4[-1].start,
            fees_total=row["fee_usd"])
        return "entry", ""

    # ------------------------------------------------------------------ mércék
    def _buy_and_hold(self, state: State, p: PortfolioState, snap: Snapshot):
        if p.bh_done:
            return
        fill = q8_up(snap.quote.ask * (1 + self.slip))
        qty = self._qty_for_amount(p.cash, fill)
        if qty <= 0:
            return
        self._buy(state, p, qty, fill, self._now, "buy_and_hold", {"ask": snap.quote.ask}, f"{p.name}:BH", None)
        p.bh_done = True

    def _weekly_dca(self, state: State, p: PortfolioState, snap: Snapshot):
        spec = self.cfg.strategy(p.name)
        n = int(spec["installments"])
        interval = int(spec["interval_days"]) * 86400
        due = min(n, (self._now - state.meta.start_time) // interval + 1)
        fill = q8_up(snap.quote.ask * (1 + self.slip))
        while p.dca_done < due:
            k = p.dca_done + 1
            amount = p.cash if k == n else min(q8_down(self.initial / n), p.cash)
            qty = self._qty_for_amount(amount, fill)
            if qty <= 0:
                break
            self._buy(state, p, qty, fill, self._now, "dca", {"ask": snap.quote.ask, "installment": k,
                                                               "of": n, "amount": amount}, f"{p.name}:DCA{k:02d}",
                      None)
            p.dca_done = k

    # ------------------------------------------------------------------ könyvelés
    def _buy_cost(self, qty: Decimal, price: Decimal) -> Decimal:
        notional = q8_up(qty * price)
        return notional + q8_up(notional * self.fee)

    def _qty_for_amount(self, amount: Decimal, price: Decimal) -> Decimal:
        qty = q8_down(amount / (price * (1 + self.fee)))
        while qty > 0 and self._buy_cost(qty, price) > amount:
            qty -= SAT
        return qty

    def _row(self, state, p: PortfolioState, side, reason, qty, price, notional, fee, time, details, trade_id, pos_id,
             pnl):
        if any(t["trade_id"] == trade_id for t in state.trades):
            raise DuplicateTradeError(f"Ez a trade már létezik: {trade_id}")
        return {"trade_id": trade_id, "run_id": self._run_id, "time": int(time), "time_iso": iso(time),
                "portfolio": p.name, "side": side, "reason": reason, "qty_btc": qty, "price": price,
                "notional_usd": notional, "fee_usd": fee, "cash_after": p.cash, "btc_after": p.btc,
                "position_id": pos_id or "", "pnl_usd": pnl, "config_hash": self.cfg.hash,
                "details": json.dumps(_jsonable(details), ensure_ascii=False, sort_keys=True)}

    def _buy(self, state, p, qty, price, time, reason, details, trade_id, pos_id):
        notional = q8_up(qty * price)
        fee = q8_up(notional * self.fee)
        if notional + fee > p.cash:
            raise InvariantError(f"{p.name}: nincs elég készpénz ({notional + fee} > {p.cash})")
        p.cash = p.cash - notional - fee
        p.btc = p.btc + qty
        row = self._row(state, p, "BUY", reason, qty, price, notional, fee, time, details, trade_id, pos_id, None)
        state.trades.append(row)
        self._msg(state, "BUY", p.name, {"trade_id": trade_id}, f"BUY:{trade_id}")
        return row

    def _sell(self, state, p, qty, price, time, reason, details, trade_id):
        pos = p.position
        if qty > p.btc or qty > pos.qty:
            raise InvariantError(f"{p.name}: több BTC eladása, mint ami van")
        notional = q8_down(qty * price)
        fee = q8_up(notional * self.fee)
        net = notional - fee
        p.cash = p.cash + net
        p.btc = p.btc - qty
        pos.qty = pos.qty - qty
        pos.realized_net += net
        pos.fees_total += fee
        cost_part = q8_down(pos.cost_total * qty / pos.initial_qty)
        pnl = net - cost_part
        # ellenőrizhetőség: a stop-történet és a figyelés kezdete minden eladás mellett
        details = {**details, "stops": pos.stops, "active_from": pos.active_from, "entry_price": pos.entry_price}
        row = self._row(state, p, "SELL", reason, qty, price, notional, fee, time, details, trade_id, pos.id, pnl)
        state.trades.append(row)
        self._msg(state, "SELL", p.name, {"trade_id": trade_id}, f"SELL:{trade_id}")
        return row

    def _close(self, state, p, price, time, reason, details):
        pos = p.position
        details = dict(details)
        row = self._sell(state, p, pos.qty, price, time, reason, details, f"{pos.id}:X")
        if pos.qty != 0:
            raise InvariantError(f"{p.name}: zárás után maradt mennyiség")
        row["details"] = json.dumps({**json.loads(row["details"]),
                                     "round_trip_pnl": s(pos.realized_net - pos.cost_total),
                                     "round_trip_fees": s(pos.fees_total)}, ensure_ascii=False, sort_keys=True)
        p.position = None
        p.last_exit_time = int(time)

    # ------------------------------------------------------------------ napló, üzenet
    def _signal_row(self, name, tf, bar_close, entry, exit_, action, reason, values):
        return {"time": self._now, "time_iso": iso(self._now), "run_id": self._run_id, "portfolio": name,
                "timeframe": tf, "bar_close": bar_close, "bar_close_iso": iso(bar_close), "entry": bool(entry),
                "exit": bool(exit_), "action": action, "reason": reason,
                "values": json.dumps(_jsonable(values), ensure_ascii=False, sort_keys=True),
                "config_hash": self.cfg.hash}

    def _msg(self, state: State, kind: str, portfolio, payload: dict, mid: str):
        if any(m["id"] == mid for m in state.outbox):
            return
        state.outbox.append({"id": mid, "kind": kind, "portfolio": portfolio or "", "created": self._now,
                             "run_id": self._run_id, "payload": _jsonable(payload), "sent": False})

    def _record_equity(self, state: State, snap: Snapshot):
        bid = snap.quote.bid
        for name in self.cfg.names:
            p = state.portfolios[name]
            eq = q8_down(p.cash + p.btc * bid)
            if eq > p.peak_equity:
                p.peak_equity = eq
            dd = ZERO if p.peak_equity == 0 else q8_down((p.peak_equity - eq) / p.peak_equity)
            state.equity.append({"time": self._now, "time_iso": iso(self._now), "run_id": self._run_id,
                                 "portfolio": name, "cash": p.cash, "btc": p.btc, "price": bid, "equity": eq,
                                 "peak": q8_down(p.peak_equity), "drawdown": dd,
                                 "position_open": p.position is not None, "halted": p.halted})
