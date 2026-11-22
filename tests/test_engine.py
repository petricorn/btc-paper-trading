"""Motor és könyvelés: pozícióméret, stop/cél szélső esetek, késett és dupla futás, trailing,
cooldown, kill switch, adat-hibák, mércék, invariánsok, mentés/visszatöltés."""
import json
from decimal import Decimal

import pytest

from btcpaper.engine import Engine
from btcpaper.num import D, q2_down, q8_down, q8_up
from btcpaper.state import (InvariantError, check_invariants, load_state, new_state, rebuild_balances,
                            save_state)
from btcpaper.timeutil import H4, MIN
from tests.helpers import T0, cfg_with, engine_with_stub, flat_d1, flat_h4, make_snap, m1_flat

CFG = cfg_with()
FEE = D("0.004")
SLIP = D("0.0005")
BAR_CLOSE = T0 + 10 * H4          # okt. 2. 16:00 UTC – a jelzés gyertyájának vége


def last_sig(st, name="P1"):
    return [s for s in st.signals if s["portfolio"] == name][-1]


def h4_upto(close_time, price=100000, rng=1000):
    return flat_h4(close_time, n=40, price=price, rng=rng)


def setup_entry(cfg=CFG, ask=100000, run_delay=120, price=100000, rng=1000):
    """P1 (stub) jelzést ad a BAR_CLOSE-kor záró 4H gyertyán; a futás run_delay mp-cel később."""
    eng, _ = engine_with_stub(cfg, "P1", entries={BAR_CLOSE})
    st = new_state(cfg, BAR_CLOSE - 600)
    for n in ("B1", "B2"):
        st.portfolios[n].bh_done = True
        st.portfolios[n].dca_done = 26
    now = BAR_CLOSE + run_delay
    m1 = m1_flat(BAR_CLOSE - 600, now - 60, price=price)
    snap = make_snap(now, m1=m1, h4=h4_upto(BAR_CLOSE, price, rng), d1=flat_d1(BAR_CLOSE - 16 * 3600),
                     bid=ask, ask=ask)
    res = eng.run(st, snap)
    return eng, st, res, now


def next_run(eng, st, now, m1, bid=100000, h4=None, run_id=None, issues=None):
    snap = make_snap(now, run_id=run_id, m1=m1, h4=h4 or h4_upto(BAR_CLOSE), d1=flat_d1(BAR_CLOSE - 16 * 3600),
                     bid=bid, issues=issues)
    return eng.run(st, snap)


# ---------------------------------------------------------------- belépés és pozícióméret

def test_entry_sizing_risk_fee_slippage():
    eng, st, res, now = setup_entry()
    p = st.portfolios["P1"]
    assert res["data_ok"] and len(res["new_trades"]) == 1
    t = res["new_trades"][0]
    stop = D(100000) - 2 * D(1000)                       # záró − 2×ATR14(4H), ATR pontosan 1000
    fill = q8_up(D(100000) * (1 + SLIP))                 # ask + 0,05% csúszás
    assert t["price"] == fill == D("100050.00000000")
    qty = q8_down(D(200) * D("0.015") / (fill - stop))   # kockázat $ / (belépő − stop)
    assert t["qty_btc"] == qty
    assert t["notional_usd"] == q8_up(qty * fill)
    assert t["fee_usd"] == q8_up(t["notional_usd"] * FEE)
    assert p.cash == D(200) - t["notional_usd"] - t["fee_usd"]
    assert qty * (fill - stop) <= D(200) * D("0.015")    # a kockázat nem lépi túl az 1,5%-ot
    pos = p.position
    assert pos.initial_stop == stop and pos.r_value == fill - stop
    assert pos.target == fill + 2 * (fill - stop)        # részleges cél 2R-nél
    assert pos.active_from == (now // 60) * 60 + 60      # a belépés utáni első teljes perctől figyel
    det = json.loads(t["details"])
    assert det["stop"] == "98000.00" and det["values"] == {"stub": True}
    assert t["config_hash"] == CFG.hash
    msgs = [m for m in st.outbox if m["kind"] == "BUY"]
    assert len(msgs) == 1 and msgs[0]["id"] == f"BUY:{t['trade_id']}"


def test_entry_size_capped_by_cash():
    cfg = cfg_with(risk__stop_atr_mult="0.5", risk__risk_per_trade="0.05")
    eng, st, res, _ = setup_entry(cfg=cfg, rng=10)             # nagyon szűk stop → óriási méret → készpénz-plafon
    t = res["new_trades"][0]
    p = st.portfolios["P1"]
    assert t["notional_usd"] + t["fee_usd"] <= D(200)
    assert p.cash >= 0 and p.cash < D("0.01")                  # szinte minden készpénz elment, negatív soha


def test_entry_skipped_below_min_trade_size():
    eng, st, res, _ = setup_entry(rng=40000)                   # hatalmas ATR → pozíció < 10 USD
    assert res["new_trades"] == []
    sig = last_sig(st)
    assert sig["action"] == "skip" and "túl kicsi" in sig["reason"]


def test_entry_skipped_when_price_already_below_stop():
    eng, st, res, _ = setup_entry(ask=97000)                   # stop 98000
    assert res["new_trades"] == []
    assert "stop" in last_sig(st)["reason"] and st.portfolios["P1"].position is None


def test_late_run_over_one_hour_skips_entry_and_never_enters_later():
    eng, st, res, now = setup_entry(run_delay=3601)
    assert res["new_trades"] == []
    assert last_sig(st)["action"] == "skip" and "késett" in last_sig(st)["reason"]
    assert st.meta.counters["entries_skipped_late"] == 1
    # a következő futás sem lép be ugyanarra a jelzésre
    res2 = next_run(eng, st, now + 300, m1_flat(BAR_CLOSE - 600, now + 240))
    assert res2["new_trades"] == []


def test_run_within_one_hour_enters_at_run_time_price_not_bar_price():
    eng, st, res, now = setup_entry(run_delay=3500, ask=100500)
    t = res["new_trades"][0]
    assert t["price"] == q8_up(D(100500) * (1 + SLIP))         # a futás pillanatának ára, nem a gyertya záróára
    assert t["time"] == int(now)


# ---------------------------------------------------------------- stop / cél teljesülés

def _run_with_minutes(eng, st, now, minutes):
    """minutes: {t: (open, high, low, close)} – a többi perc lapos."""
    m1 = m1_flat(BAR_CLOSE - 600, now - 60)
    from tests.helpers import candle
    for t, (o, h, l, c) in minutes.items():
        m1[t] = candle(t, o, h, l, c)
    return next_run(eng, st, now, m1)


def test_stop_fill_at_stop_minus_slippage():
    eng, st, res, now = setup_entry()
    pos = st.portfolios["P1"].position
    t_hit = pos.active_from + 5 * MIN
    r = _run_with_minutes(eng, st, t_hit + 10 * MIN, {t_hit: (98500, 98600, 97900, 98100)})
    sell = [x for x in r["new_trades"] if x["side"] == "SELL"][0]
    assert sell["reason"] == "stop" and sell["time"] == t_hit
    assert sell["price"] == q8_down(D(98000) * (1 - SLIP))
    assert st.portfolios["P1"].position is None and st.portfolios["P1"].btc == 0


def test_stop_gap_below_fills_at_open():
    eng, st, res, now = setup_entry()
    t_hit = st.portfolios["P1"].position.active_from + 2 * MIN
    r = _run_with_minutes(eng, st, t_hit + 5 * MIN, {t_hit: (97000, 97500, 96500, 97200)})
    sell = r["new_trades"][0]
    assert sell["price"] == q8_down(D(97000) * (1 - SLIP))     # a stop alatt nyitott → nyitóár
    assert json.loads(sell["details"])["gap_below_stop"] is True


def test_same_minute_stop_and_target_stop_wins():
    eng, st, res, now = setup_entry()
    pos = st.portfolios["P1"].position
    t_hit = pos.active_from + MIN
    r = _run_with_minutes(eng, st, t_hit + 5 * MIN, {t_hit: (100000, float(pos.target) + 1000, 97000, 100000)})
    assert len(r["new_trades"]) == 1 and r["new_trades"][0]["reason"] == "stop"


def test_target_partial_then_stop_closes_rest():
    eng, st, res, now = setup_entry()
    pos = st.portfolios["P1"].position
    target = pos.target
    q0 = pos.initial_qty
    t1 = pos.active_from + 3 * MIN
    r = _run_with_minutes(eng, st, t1 + 5 * MIN, {t1: (104000, float(target) + 1, 103900, 104100)})
    part = r["new_trades"][0]
    assert part["reason"] == "target_partial" and part["price"] == target    # limit: csúszás nélkül
    assert part["qty_btc"] == q8_down(q0 * D("0.5"))
    assert st.portfolios["P1"].position.target is None
    assert part["pnl_usd"] > 0
    t2 = t1 + 20 * MIN
    r2 = _run_with_minutes(eng, st, t2 + 5 * MIN, {t2: (98100, 98200, 97950, 98000)})
    fin = r2["new_trades"][0]
    assert fin["reason"] == "stop" and fin["qty_btc"] == q0 - part["qty_btc"]
    assert st.portfolios["P1"].btc == 0
    det = json.loads(fin["details"])
    pnl_sum = part["pnl_usd"] + fin["pnl_usd"]
    assert abs(D(det["round_trip_pnl"]) - pnl_sum) <= D("0.00000002")


def test_entry_minute_low_is_not_used_for_stop():
    eng, st, res, now = setup_entry()
    entry_minute = (now // 60) * 60
    r = _run_with_minutes(eng, st, now + 5 * MIN, {entry_minute: (100000, 100000, 90000, 100000)})
    assert r["new_trades"] == [] and st.portfolios["P1"].position is not None


def test_minutes_processed_in_time_order_across_runs():
    eng, st, res, now = setup_entry()
    pos = st.portfolios["P1"].position
    a = pos.active_from + MIN
    b = pos.active_from + 2 * MIN
    target = float(pos.target)
    # a: célár (részleges), b: stop → előbb részleges, utána stop
    r = _run_with_minutes(eng, st, b + 5 * MIN, {a: (100000, target + 5, 99990, 100000),
                                                 b: (99000, 99000, 97000, 97500)})
    assert [x["reason"] for x in r["new_trades"]] == ["target_partial", "stop"]


# ---------------------------------------------------------------- trailing, cooldown, jelzéses kiszállás

def test_trailing_activates_above_1R_only_on_closed_4h_and_never_loosens():
    eng, st, res, now = setup_entry()
    pos = st.portfolios["P1"].position
    R = pos.r_value
    h4 = h4_upto(BAR_CLOSE)
    from tests.helpers import candle
    # +1R alatt záró gyertya: nincs trailing
    b1 = candle(BAR_CLOSE, 100000, 101000, 99500, 101000)
    t_run = BAR_CLOSE + H4 + 100
    next_run(eng, st, t_run, m1_flat(BAR_CLOSE - 600, t_run - 60), h4=h4 + [b1], bid=101000)
    assert not pos.trailing_active and len(pos.stops) == 1
    # +1R fölött záró gyertya: trailing indul, stop = legmagasabb záró − 2×ATR
    hi = D(100050) + R + 500
    b2 = candle(BAR_CLOSE + H4, 101000, hi + 100, 100900, hi)
    t_run2 = BAR_CLOSE + 2 * H4 + 100
    next_run(eng, st, t_run2, m1_flat(BAR_CLOSE - 600, t_run2 - 60, price=int(hi)), h4=h4 + [b1, b2], bid=hi)
    pos = st.portfolios["P1"].position
    assert pos.trailing_active and len(pos.stops) == 2
    eff, level, kind = pos.stops[-1]
    assert kind == "trailing" and level > pos.initial_stop
    assert eff == (t_run2 // 60) * 60 + 60                   # csak a következő perctől érvényes
    # lejjebb záró gyertya: a stop nem tágul
    b3 = candle(BAR_CLOSE + 2 * H4, hi, hi, 99000, 99500)
    t_run3 = BAR_CLOSE + 3 * H4 + 100
    m1 = m1_flat(BAR_CLOSE - 600, t_run3 - 60, price=int(hi))
    next_run(eng, st, t_run3, m1, h4=h4 + [b1, b2, b3], bid=hi)
    pos = st.portfolios["P1"].position
    assert pos.current_stop == level
    check_invariants(st, CFG)


def test_trailing_stop_exit_reason():
    eng, st, res, now = setup_entry()
    pos = st.portfolios["P1"].position
    pos.trailing_active = True
    eff = pos.active_from + 10 * MIN
    pos.stops.append([eff, D(99000), "trailing"])
    r = _run_with_minutes(eng, st, eff + 5 * MIN, {eff + MIN: (99500, 99600, 98900, 99000)})
    assert r["new_trades"][0]["reason"] == "trailing"
    assert r["new_trades"][0]["price"] == q8_down(D(99000) * (1 - SLIP))


def test_cooldown_one_4h_bar_after_exit():
    cfg = CFG
    sig2 = BAR_CLOSE + H4          # a kiszállás gyertyájának vége → tiltott
    sig3 = BAR_CLOSE + 2 * H4      # a következő gyertya → engedélyezett
    eng, stub = engine_with_stub(cfg, "P1", entries={BAR_CLOSE, sig2, sig3})
    st = new_state(cfg, BAR_CLOSE - 600)
    for n in ("B1", "B2"):
        st.portfolios[n].bh_done = True
        st.portfolios[n].dca_done = 26
    from tests.helpers import candle
    h4 = h4_upto(BAR_CLOSE)
    now = BAR_CLOSE + 60
    eng.run(st, make_snap(now, m1=m1_flat(BAR_CLOSE - 600, now - 60), h4=h4, d1=flat_d1(BAR_CLOSE - 57600)))
    pos = st.portfolios["P1"].position
    hit = pos.active_from + 30 * MIN
    m1 = m1_flat(BAR_CLOSE - 600, sig2 + 60)
    m1[hit] = candle(hit, 98500, 98500, 97000, 97500)
    b = [candle(BAR_CLOSE, 100000, 100500, 99500, 100000)]
    r = eng.run(st, make_snap(sig2 + 120, m1=m1, h4=h4 + b, d1=flat_d1(BAR_CLOSE - 57600)))
    assert [x["reason"] for x in r["new_trades"]] == ["stop"]
    assert last_sig(st)["action"] == "skip" and "cooldown" in last_sig(st)["reason"]
    b2 = b + [candle(sig2, 100000, 100500, 99500, 100000)]
    m1 = m1_flat(BAR_CLOSE - 600, sig3 + 60)
    m1[hit] = candle(hit, 98500, 98500, 97000, 97500)
    r = eng.run(st, make_snap(sig3 + 120, m1=m1, h4=h4 + b2, d1=flat_d1(BAR_CLOSE - 57600)))
    assert [x["reason"] for x in r["new_trades"]] == ["entry"]


def test_signal_exit_sells_at_bid_minus_slippage():
    eng, stub = engine_with_stub(CFG, "P1", entries={BAR_CLOSE}, exits={BAR_CLOSE + H4})
    st = new_state(CFG, BAR_CLOSE - 600)
    for n in ("B1", "B2"):
        st.portfolios[n].bh_done = True
        st.portfolios[n].dca_done = 26
    from tests.helpers import candle
    h4 = h4_upto(BAR_CLOSE)
    eng.run(st, make_snap(BAR_CLOSE + 60, m1=m1_flat(BAR_CLOSE - 600, BAR_CLOSE), h4=h4,
                          d1=flat_d1(BAR_CLOSE - 57600)))
    t = BAR_CLOSE + H4 + 90
    r = eng.run(st, make_snap(t, m1=m1_flat(BAR_CLOSE - 600, t - 60), h4=h4 + [candle(BAR_CLOSE, 1e5, 1e5 + 500,
                                                                                         1e5 - 500, 1e5)],
                              d1=flat_d1(BAR_CLOSE - 57600), bid=100200))
    sell = r["new_trades"][0]
    assert sell["reason"] == "signal" and sell["price"] == q8_down(D(100200) * (1 - SLIP))
    assert sell["time"] == int(t)


# ---------------------------------------------------------------- kill switch

def test_kill_switch_liquidates_halts_and_alerts_once():
    eng, st, res, now = setup_entry()
    p = st.portfolios["P1"]
    p.peak_equity = D(260)            # mesterséges csúcs → a 200 körüli tőke 20%-nál mélyebben van alatta
    t = now + 10 * MIN
    r = next_run(eng, st, t, m1_flat(BAR_CLOSE - 600, t - 60))
    assert [x["reason"] for x in r["new_trades"]] == ["kill_switch"]
    assert p.halted and p.position is None and p.btc == 0
    assert sum(1 for m in st.outbox if m["kind"] == "ALERT_KILL") == 1
    r2 = next_run(eng, st, t + 10 * MIN, m1_flat(BAR_CLOSE - 600, t + 9 * MIN))
    assert r2["new_trades"] == []
    assert sum(1 for m in st.outbox if m["kind"] == "ALERT_KILL") == 1


# ---------------------------------------------------------------- adat-hibák és riasztás

def test_data_issue_means_no_trade_and_alert_after_3_runs():
    eng, stub = engine_with_stub(CFG, "P1", entries={BAR_CLOSE})
    st = new_state(CFG, BAR_CLOSE - 600)
    h4 = h4_upto(BAR_CLOSE)
    for k in range(3):
        t = BAR_CLOSE + 60 + k * 300
        r = eng.run(st, make_snap(t, m1=m1_flat(BAR_CLOSE - 600, t - 60), h4=h4, d1=flat_d1(BAR_CLOSE - 57600),
                                  issues=["Kereszt-ellenőrzés: eltérés 0.900%"]))
        assert not r["data_ok"] and r["new_trades"] == []
        assert sum(1 for m in st.outbox if m["kind"] == "ALERT_DATA") == (1 if k == 2 else 0)
    assert st.meta.consecutive_failures == 3 and st.meta.counters["fail_crosscheck"] == 3
    assert st.trades == [] and st.runs[-1]["data_ok"] is False and "Kereszt" in st.runs[-1]["issues"]
    t = BAR_CLOSE + 60 + 3 * 300
    r = eng.run(st, make_snap(t, m1=m1_flat(BAR_CLOSE - 600, t - 60), h4=h4, d1=flat_d1(BAR_CLOSE - 57600)))
    assert r["data_ok"] and st.meta.consecutive_failures == 0
    assert any(m["kind"] == "DATA_RECOVERED" for m in st.outbox)
    # a még 1 órán belüli jelzésre most beléphet; a mércék is most vásárolnak először
    assert {x["reason"] for x in r["new_trades"]} == {"entry", "buy_and_hold", "dca"}


def test_recent_m1_gap_blocks_decisions_but_old_gap_is_accepted():
    eng, st, res, now = setup_entry()
    pos = st.portfolios["P1"].position
    gap = pos.active_from + 2 * MIN
    t = gap + 5 * MIN
    m1 = m1_flat(BAR_CLOSE - 600, t - 60)
    del m1[gap]
    r = next_run(eng, st, t, m1)
    assert not r["data_ok"] and "naprakész" in r["issues"][0]
    assert st.meta.m1_cursor == gap                               # a hiány előtti percig dolgozott fel
    t2 = gap + 31 * MIN                                          # 30 perc után "nem volt kötés" percnek számít
    m1 = m1_flat(BAR_CLOSE - 600, t2 - 60)
    del m1[gap]
    r2 = next_run(eng, st, t2, m1)
    assert r2["data_ok"] and r2["m1_gaps_accepted"] == 1
    assert st.meta.m1_cursor == (int(t2) - 10) // 60 * 60


# ---------------------------------------------------------------- ismételhetőség

def test_duplicate_run_id_and_same_time_are_noops():
    eng, st, res, now = setup_entry()
    n = len(st.trades)
    snap = make_snap(now, run_id="t-%d" % int(now), m1=m1_flat(BAR_CLOSE - 600, now - 60),
                     h4=h4_upto(BAR_CLOSE), d1=flat_d1(BAR_CLOSE - 57600))
    r = eng.run(st, snap)
    assert r["skipped"] and len(st.trades) == n
    snap2 = make_snap(now - 5, run_id="other", m1=m1_flat(BAR_CLOSE - 600, now - 60), h4=h4_upto(BAR_CLOSE),
                      d1=flat_d1(BAR_CLOSE - 57600))
    assert eng.run(st, snap2)["skipped"] and len(st.trades) == n


def test_same_period_processed_twice_no_double_trades(tmp_path):
    """Elbukott mentés: a következő futás a mentett állapotból ugyanazt az időszakot újra feldolgozza."""
    eng, st, res, now = setup_entry()
    save_state(st, tmp_path)
    pos = st.portfolios["P1"].position
    hit = pos.active_from + 4 * MIN
    from tests.helpers import candle
    m1 = m1_flat(BAR_CLOSE - 600, hit + 5 * MIN)
    m1[hit] = candle(hit, 98100, 98100, 97900, 98000)
    r1 = next_run(eng, st, hit + 6 * MIN, m1, run_id="A")
    assert len(r1["new_trades"]) == 1
    # a mentés "elbukott": újratöltjük a régi állapotot, és újra futtatjuk ugyanazt
    st2 = load_state(tmp_path)
    r2 = next_run(eng, st2, hit + 7 * MIN, m1, run_id="B")
    assert len(r2["new_trades"]) == 1
    assert [t["trade_id"] for t in st2.trades] == [t["trade_id"] for t in st.trades]
    r3 = next_run(eng, st2, hit + 8 * MIN, m1, run_id="C")       # és még egyszer: semmi új
    assert r3["new_trades"] == []
    check_invariants(st2, CFG)


def test_duplicate_trade_id_is_rejected_and_run_rolls_back():
    eng, st, res, now = setup_entry()
    before = (len(st.trades), st.portfolios["P1"].cash, st.meta.last_run_time)
    st.portfolios["P1"].position = None          # szándékosan elrontott állapot: ugyanaz a jelzés újra
    st.portfolios["P1"].btc = D(0)
    st.portfolios["P1"].last_signal_bar = 0
    with pytest.raises(InvariantError):
        next_run(eng, st, now + 60, m1_flat(BAR_CLOSE - 600, now))
    assert (len(st.trades), st.meta.last_run_time) == (before[0], before[2])


# ---------------------------------------------------------------- könyvelés és mentés

def test_ledger_rebuild_detects_tampering(tmp_path):
    eng, st, res, now = setup_entry()
    save_state(st, tmp_path)
    p = tmp_path / "trades.csv"
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()
    cols = lines[1].split(",")
    idx = lines[0].split(",").index("fee_usd")
    cols[idx] = "0.01"
    lines[1] = ",".join(cols)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    st2 = load_state(tmp_path)
    with pytest.raises(InvariantError):
        check_invariants(st2, CFG)


def test_invariant_negative_cash_detected():
    st = new_state(CFG, T0)
    st.portfolios["P2"].cash = D("-1")
    with pytest.raises(InvariantError):
        check_invariants(st, CFG)


def test_state_roundtrip_is_lossless(tmp_path):
    eng, st, res, now = setup_entry()
    save_state(st, tmp_path)
    st2 = load_state(tmp_path)
    save_state(st2, tmp_path / "again")
    for f in ("portfolios.json", "trades.csv", "signals.csv", "equity.csv", "runs.csv", "outbox.json"):
        assert (tmp_path / f).read_text(encoding="utf-8") == (tmp_path / "again" / f).read_text(encoding="utf-8")
    assert st2.portfolios["P1"].position == st.portfolios["P1"].position
    check_invariants(st2, CFG)


def test_rebuild_balances_matches_state():
    eng, st, res, now = setup_entry()
    bal = rebuild_balances(st.trades, CFG.names, D(200))
    assert bal["P1"] == (st.portfolios["P1"].cash, st.portfolios["P1"].btc)


def test_config_change_creates_alert_and_new_hash():
    eng, st, res, now = setup_entry()
    cfg2 = cfg_with(costs__slippage_rate="0.001")
    assert cfg2.hash != CFG.hash
    eng2 = Engine(cfg2)
    t = now + 300
    eng2.run(st, make_snap(t, m1=m1_flat(BAR_CLOSE - 600, t - 60), h4=h4_upto(BAR_CLOSE),
                           d1=flat_d1(BAR_CLOSE - 57600)))
    assert st.meta.config_hash == cfg2.hash
    assert any(m["kind"] == "ALERT_PARAM" for m in st.outbox)
    assert st.runs[-1]["config_hash"] == cfg2.hash


# ---------------------------------------------------------------- mércék

def test_buy_and_hold_buys_once_with_all_cash():
    eng, _ = engine_with_stub(CFG, "P1")
    st = new_state(CFG, T0)
    for k in range(3):
        t = T0 + 120 + k * 300
        eng.run(st, make_snap(t, m1=m1_flat(T0, t - 60), h4=h4_upto(T0), d1=flat_d1(T0), bid=100000))
    b1 = [x for x in st.trades if x["portfolio"] == "B1"]
    assert len(b1) == 1
    p = st.portfolios["B1"]
    assert p.cash >= 0 and p.cash < D("0.01") and p.btc == b1[0]["qty_btc"]


def test_weekly_dca_26_equal_installments_with_catchup():
    eng, _ = engine_with_stub(CFG, "P1")
    st = new_state(CFG, T0)
    week = 7 * 86400
    times = [T0 + 120] + [T0 + 120 + k * week for k in (1, 2, 5)] + [T0 + 120 + 30 * week]
    counts = []
    for t in times:
        st.meta.m1_cursor = (int(t) - 10) // 60 * 60      # az 1 perces adat itt nem számít (nincs pozíció)
        eng.run(st, make_snap(t, m1={}, h4=h4_upto(T0), d1=flat_d1(T0), bid=100000))
        counts.append(st.portfolios["B2"].dca_done)
    assert counts == [1, 2, 3, 6, 26]                      # kimaradt hetek pótlása, legfeljebb 26
    b2 = [x for x in st.trades if x["portfolio"] == "B2"]
    assert len(b2) == 26
    amounts = [x["notional_usd"] + x["fee_usd"] for x in b2]
    inst = q8_down(D(200) / 26)
    assert all(inst - D("0.0011") <= a <= inst for a in amounts[:25])   # egyenlő részletek (1 satoshi-kerekítés)
    assert st.portfolios["B2"].cash < D("0.01")                       # a 26. részlet a maradékot költi el
    check_invariants(st, CFG)
