"""Fázis 2: mutatók, tömör adattár, paraméterrács, walk-forward ablakok, fennsík-szabály, backteszt-futás."""
import math
from decimal import Decimal

import pytest

from btcpaper.backtest import (RunResult, add_months, combo_key, grid_combos, make_config, neighbors, run_backtest,
                               select_params, ts, wf_windows)
from btcpaper.compact import CompactSeries, to_cents
from btcpaper.metrics import (RoundTrip, compute_stats, daily_returns, max_drawdown, max_drawdown_from_returns,
                              monte_carlo_drawdowns, round_trips, sharpe)
from btcpaper.replay import HistoricalData, Series
from btcpaper.timeutil import D1, H1
from tests.helpers import T0, aggregate, cfg_with, synthetic_wave

CFG = cfg_with()


# ---------------------------------------------------------------- mutatók

def test_sharpe_and_drawdown_hand_computed():
    r = [0.01, -0.01, 0.02, 0.0]
    m = sum(r) / 4
    sd = math.sqrt(sum((x - m) ** 2 for x in r) / 3)
    assert sharpe(r) == pytest.approx(m / sd * math.sqrt(365))
    assert sharpe([0.01, 0.01]) == 0.0
    assert max_drawdown_from_returns([0.1, -0.5, 0.2]) == pytest.approx(0.5)
    pts = [(0, 100.0), (1, 120.0), (2, 60.0), (3, 130.0), (4, 117.0)]
    assert max_drawdown(pts, 0, 10) == pytest.approx(0.5)
    assert max_drawdown(pts, 3, 10) == pytest.approx(0.1)


def test_daily_returns_use_last_value_per_day():
    pts = [(0, 100.0), (3600, 105.0), (86400, 110.0), (86400 + 7200, 99.0), (2 * 86400, 99.0)]
    assert daily_returns(pts, 86400, 3 * 86400) == pytest.approx([99 / 105 - 1, 0.0])


def test_stats_win_rate_profit_factor_cagr():
    trips = [RoundTrip("P1", "a", 0, 1, 10.0, 200), RoundTrip("P1", "b", 0, 1, -5.0, 200),
             RoundTrip("P1", "c", 0, 1, 2.0, 200)]
    st = compute_stats([0.001] * 365, trips)
    assert st.trades == 3 and st.win_rate == pytest.approx(2 / 3)
    assert st.profit_factor == pytest.approx(12 / 5)
    assert st.cagr == pytest.approx(1.001 ** 365 - 1)


def test_round_trips_from_trades():
    rows = [
        {"portfolio": "P1", "side": "BUY", "reason": "entry", "position_id": "x", "time": "10", "cash_after": "50",
         "notional_usd": "149.4", "fee_usd": "0.6", "btc_after": "0.002", "pnl_usd": None},
        {"portfolio": "P1", "side": "SELL", "reason": "target_partial", "position_id": "x", "time": "20",
         "btc_after": "0.001", "pnl_usd": "3"},
        {"portfolio": "P1", "side": "SELL", "reason": "stop", "position_id": "x", "time": "30", "btc_after": "0",
         "pnl_usd": "-1"},
    ]
    t = round_trips(rows, "P1")
    assert len(t) == 1 and t[0].pnl == 2.0 and t[0].equity_before == 200.0 and t[0].exit_time == 30
    assert t[0].ret == pytest.approx(0.01)


def test_monte_carlo_bounds():
    mc = monte_carlo_drawdowns([0.05, -0.02, -0.03, 0.04, -0.01], n=2000)
    assert 0 <= mc["p5"] <= mc["p50"] <= mc["p95"] <= mc["max"] < 1
    assert mc["max"] == pytest.approx(1 - 0.98 * 0.97 * 0.99)   # a három veszteség egymás után
    assert monte_carlo_drawdowns([], n=10) == {"n": 0}


# ---------------------------------------------------------------- tömör adattár

def test_compact_series_exact_roundtrip(tmp_path):
    from btcpaper.replay import write_candles
    from tests.helpers import candle
    cs = [candle(T0 + i * 60, "83468.69", "83527", "83400.1", "83500.05") for i in range(5)]
    write_candles(tmp_path / "a.csv", cs)
    s = CompactSeries.from_csvs([tmp_path / "a.csv"])
    s.save(tmp_path / "npy")
    s2 = CompactSeries.load(tmp_path / "npy")
    c = s2.get(T0 + 120)
    assert (c.open, c.high, c.low, c.close) == (Decimal("83468.69"), Decimal("83527"), Decimal("83400.1"),
                                                Decimal("83500.05"))
    assert s2.get(T0 + 30) is None
    assert [x.start for x in s2.range(T0 + 60, T0 + 180)] == [T0 + 60, T0 + 120, T0 + 180]
    with pytest.raises(ValueError):
        to_cents("1.001")


# ---------------------------------------------------------------- rács, ablakok, kiválasztás

def test_grid_has_at_most_3_params_and_includes_defaults():
    for s in ("P1", "P2", "P3"):
        combos = grid_combos(CFG, s)
        assert len(combos[0]) <= 4
        default = {k: CFG.strategy(s)[k] for k in combos[0]}
        assert default in combos, s
    assert len(grid_combos(CFG, "P1")) == 36 and len(grid_combos(CFG, "P3")) == 18


def test_neighbors_one_step_one_param():
    c = {"entry_lookback_days": 20, "exit_lookback_days": 5, "trend_sma_days": 200}
    nb = neighbors(CFG, "P1", c)
    assert {"entry_lookback_days": 10, "exit_lookback_days": 5, "trend_sma_days": 200} in nb
    assert {"entry_lookback_days": 30, "exit_lookback_days": 5, "trend_sma_days": 200} in nb
    assert {"entry_lookback_days": 20, "exit_lookback_days": 10, "trend_sma_days": 200} in nb
    assert {"entry_lookback_days": 20, "exit_lookback_days": 5, "trend_sma_days": 150} in nb
    assert len(nb) == 4


def test_walk_forward_windows_never_touch_holdout():
    w = wf_windows(CFG)
    hold = ts(CFG.get("backtest.holdout_start"))
    assert len(w) == 13
    assert w[0] == ((ts("2018-01-01"), ts("2020-01-01")), (ts("2020-01-01"), ts("2020-07-01")))
    for (a, b), (c, d) in w:
        assert b == c and d <= hold and add_months(a, 24) == b
    assert w[-1][1][1] == hold


class FakeResult:
    def __init__(self, sharpe_, trades):
        self._s, self._t = sharpe_, trades

    def stats(self, name, a, b):
        class S:
            pass
        s = S()
        s.sharpe, s.trades = self._s, self._t
        return s


def test_select_params_plateau_rule_rejects_isolated_peak():
    combos = grid_combos(CFG, "P3")
    res = {combo_key(c): FakeResult(0.5, 10) for c in combos}
    peak = {"bb_period": 30, "bb_std": "2.5", "adx_max": "25"}
    res[combo_key(peak)] = FakeResult(3.0, 10)          # magányos csúcs: szomszédai 0,5 → elutasítva
    good = {"bb_period": 20, "bb_std": "2.0", "adx_max": "20"}
    res[combo_key(good)] = FakeResult(0.55, 10)         # fennsíkon: szomszédai 0,5 >= 0,8 × 0,55
    params, sh, n, nb, cands = select_params(CFG, "P3", res, (0, 1))
    assert params == good and sh == 0.55


def test_select_params_requires_min_trades_and_positive_sharpe():
    combos = grid_combos(CFG, "P3")
    res = {combo_key(c): FakeResult(1.0, 3) for c in combos}           # túl kevés kötés
    assert select_params(CFG, "P3", res, (0, 1))[0] is None
    res = {combo_key(c): FakeResult(-0.2, 30) for c in combos}         # negatív Sharpe
    assert select_params(CFG, "P3", res, (0, 1))[0] is None


def test_make_config_overrides_and_kill_switch():
    c = make_config(CFG, {"P1": {"entry_lookback_days": 55}}, kill_switch=False)
    assert c.strategy("P1")["entry_lookback_days"] == 55 and c.get("risk.kill_switch_enabled") is False
    assert c.hash != CFG.hash and CFG.strategy("P1")["entry_lookback_days"] == 20


# ---------------------------------------------------------------- backteszt-futás (ugyanaz a motor)

def test_run_backtest_on_synthetic_data_uses_engine_and_passes_audit():
    cfg = cfg_with(data__lookback_4h_bars=150, data__lookback_1d_bars=60, strategies__P1__trend_sma_days=50,
                   strategies__P1__entry_lookback_days=3, strategies__P2__trend_ema=50,
                   strategies__P2__rsi_pullback="55", strategies__P3__adx_max="100", strategies__P3__bb_std="1.0")
    m1 = synthetic_wave(T0, 70)
    data = HistoricalData(m1=Series(m1), h1=Series(aggregate(m1, H1)), d1=Series(aggregate(m1, D1)))
    start, end = T0 + 58 * D1, T0 + 69 * D1
    r = run_backtest(cfg, data, start, end, "t", {}, audit_check=True)
    assert r.report["audit_problems"] == []
    assert r.report["runs"] >= 6 * 11 - 1                     # 4 óránként egy futás
    assert sum(len(r.trips(s)) for s in ("P1", "P2", "P3")) >= 3
    st = r.stats("B1", start, end)
    assert st.days >= 10
    r2 = RunResult.from_json(r.to_json())
    assert r2.stats("P3", start, end) == r.stats("P3", start, end)
