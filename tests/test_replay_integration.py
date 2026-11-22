"""Visszajátszás szintetikus adaton (CI-ben is fut): késések, kimaradt és dupla futások, elbukott
mentések, adat-hibák mellett is: invariánsok, determinizmus, mentés/visszatöltés-azonosság, audit."""
import pytest

from btcpaper.audit import audit
from btcpaper.replay import HistoricalData, Series, run_replay
from btcpaper.state import check_invariants, save_state
from btcpaper.timeutil import D1, H1
from tests.helpers import T0, aggregate, cfg_with, synthetic_wave

CFG = cfg_with(data__lookback_4h_bars=150, data__lookback_1d_bars=60,
               strategies__P1__trend_sma_days=50,
               strategies__P1__exit_lookback_days=5, strategies__P2__trend_ema=50,
               # a CI-tesztben sok trade kell a mechanika ellenőrzéséhez → laza (NEM éles) paraméterek
               strategies__P1__entry_lookback_days=3, strategies__P2__rsi_pullback="55",
               strategies__P3__adx_max="100", strategies__P3__bb_std="1.0", risk__stop_atr_mult="1.0")
START = T0 + 58 * D1
END = START + 6 * D1


@pytest.fixture(scope="module")
def data():
    m1 = synthetic_wave(T0, 64)
    return HistoricalData(m1=Series(m1), h1=Series(aggregate(m1, H1)), d1=Series(aggregate(m1, D1)))


@pytest.fixture(scope="module")
def baseline(data):
    return run_replay(CFG, data, START, END, seed=5)


def csv_texts(state, folder):
    save_state(state, folder)
    return {f.name: f.read_text(encoding="utf-8") for f in sorted(folder.iterdir())}


def test_replay_runs_scenarios_and_keeps_invariants(baseline):
    st, rep = baseline
    check_invariants(st, CFG)
    assert rep.runs_executed > 800
    assert rep.runs_late > 0 and rep.runs_skipped_missed > 0 and rep.save_failures > 0
    assert rep.duplicate_runs > 0 and rep.duplicate_runs_rejected == rep.duplicate_runs
    assert sum(rep.injected.values()) > 0 and rep.data_fail_runs >= 1
    ids = [t["trade_id"] for t in st.trades]
    assert len(ids) == len(set(ids))
    kinds = {t["reason"] for t in st.trades}
    assert {"buy_and_hold", "dca", "entry"} <= kinds, kinds


def test_replay_is_deterministic(baseline, data, tmp_path):
    st2, _ = run_replay(CFG, data, START, END, seed=5)
    assert csv_texts(baseline[0], tmp_path / "a") == csv_texts(st2, tmp_path / "b")


def test_replay_with_state_save_load_equals_in_memory(baseline, data, tmp_path):
    st3, rep3 = run_replay(CFG, data, START, END, seed=5, roundtrip_every=7, workdir=str(tmp_path / "rt"))
    assert rep3.roundtrips > 100
    assert csv_texts(baseline[0], tmp_path / "a") == csv_texts(st3, tmp_path / "c")


def test_replay_passes_independent_audit(baseline, data):
    st, _ = baseline
    problems = audit(CFG, st, data)
    assert problems == []


def test_audit_detects_tampering(baseline, data):
    """Az audit nem "mindig zöld": szándékosan elrontott naplóban hibát talál."""
    import copy
    import json
    from decimal import Decimal
    st = copy.deepcopy(baseline[0])
    sells = [t for t in st.trades if t["side"] == "SELL" and t["reason"] in ("stop", "trailing")]
    entries = [t for t in st.trades if t["reason"] == "entry"]
    assert sells and entries
    sells[0]["price"] = sells[0]["price"] + Decimal("5")                 # rossz teljesülési ár
    d = json.loads(entries[0]["details"])
    d["signal_age_s"] = 4000                                             # túl régi jelzés
    entries[0]["details"] = json.dumps(d)
    problems = audit(CFG, st, data, check_signals=False)
    assert any("stop ár" in p or "érték" in p for p in problems)
    assert any("jelzés kora" in p for p in problems)


def test_strategy_trade_counts_reported(baseline):
    st, _ = baseline
    by = {}
    for t in st.trades:
        by.setdefault((t["portfolio"], t["reason"]), 0)
        by[(t["portfolio"], t["reason"])] += 1
    print(sorted(by.items()))
    assert sum(v for (p, r), v in by.items() if r == "entry") >= 3
