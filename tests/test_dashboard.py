"""A webes felület adatfájlja: szerkezet, egyezés a könyveléssel, JSON-ba írhatóság."""
import json

from btcpaper.dashboard import build_dashboard, write_dashboard
from btcpaper.replay import HistoricalData, Series, run_replay
from btcpaper.timeutil import D1, H1
from tests.helpers import T0, aggregate, cfg_with, synthetic_wave

CFG = cfg_with(data__lookback_4h_bars=150, data__lookback_1d_bars=60, strategies__P1__trend_sma_days=50,
               strategies__P1__entry_lookback_days=3, strategies__P2__trend_ema=50,
               strategies__P2__rsi_pullback="55", strategies__P3__adx_max="100", strategies__P3__bb_std="1.0")


def test_dashboard_matches_ledger_and_serializes(tmp_path):
    m1 = synthetic_wave(T0, 64)
    data = HistoricalData(m1=Series(m1), h1=Series(aggregate(m1, H1)), d1=Series(aggregate(m1, D1)))
    st, _ = run_replay(CFG, data, T0 + 58 * D1, T0 + 62 * D1, seed=3)
    d = write_dashboard(st, CFG, tmp_path / "x.json", "demo", "teszt")
    again = json.loads((tmp_path / "x.json").read_text(encoding="utf-8"))
    assert again["source"] == "demo" and again["schema"] == 1
    assert [p["name"] for p in d["portfolios"]] == ["P1", "P2", "P3", "B1", "B2"]
    last_price = d["price"]["last"]
    for p in d["portfolios"]:
        ps = st.portfolios[p["name"]]
        assert abs(p["cash"] - float(ps.cash)) < 1e-9
        assert abs(p["equity"] - (float(ps.cash) + float(ps.btc) * last_price)) < 0.01
        assert p["equity_series"][-1][1] == p["equity"]
        if p["kind"] == "strategy" and p["position"] is None and not p["halted"]:
            assert p["waiting"]["conditions"], p["name"]
    assert len(d["trades"]) == min(len(st.trades), 300)
    assert d["health"]["runs"] == st.meta.counters["runs"]
