"""A három stratégia jelzéslogikája, kézzel szerkesztett árfolyamokon."""
import random

from btcpaper.strategies import BollingerReversion, DonchianBreakout, MarketContext, TrendPullback
from btcpaper.timeutil import D1, H4
from tests.helpers import T0, candle, cfg_with

CFG = cfg_with()


def bars(closes, gran, spread=0.002, start=T0):
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        out.append(candle(start + i * gran, round(o, 2), round(max(o, c) * (1 + spread), 2),
                          round(min(o, c) * (1 - spread), 2), round(c, 2)))
        prev = c
    return out


def test_p1_breakout_above_20d_high_and_sma200():
    closes = [50000 + 50 * i for i in range(230)]        # emelkedő trend
    closes += [closes[-1] - 300 * k for k in range(1, 6)]   # kis visszaesés
    closes += [closes[-1] + 3000]                        # kitörés az előző 20 nap csúcsa fölé
    d1 = bars(closes, D1)
    ev = DonchianBreakout("P1", CFG).evaluate(MarketContext(CFG, [], d1))
    assert ev.entry and not ev.exit
    assert ev.bar_close_time == d1[-1].start + D1
    assert ev.values["close_1d"] > ev.values["donchian_high_20"] > 0
    assert ev.values["close_1d"] > ev.values["sma200_1d"]


def test_p1_no_entry_below_sma200_even_on_breakout():
    closes = [80000 - 100 * i for i in range(230)]        # csökkenő trend → SMA200 a záró fölött
    closes += [closes[-1]] * 25                          # 25 nap oldalazás
    closes += [closes[-1] + 1000]                        # kitörés a 20 napos csúcs fölé
    ev = DonchianBreakout("P1", CFG).evaluate(MarketContext(CFG, [], bars(closes, D1)))
    assert ev.values["close_1d"] > ev.values["donchian_high_20"]
    assert not ev.entry


def test_p1_exit_below_10d_low_and_not_enough_data():
    closes = [50000 + 50 * i for i in range(230)] + [40000]
    ev = DonchianBreakout("P1", CFG).evaluate(MarketContext(CFG, [], bars(closes, D1)))
    assert ev.exit and not ev.entry
    ev2 = DonchianBreakout("P1", CFG).evaluate(MarketContext(CFG, [], bars(closes[:100], D1)))
    assert not ev2.entry and ev2.note == "kevés adat"


def test_p2_trend_pullback_reversal():
    closes = []
    p = 50000.0
    for i in range(200):                                  # zajos emelkedő trend (+30/−20)
        p += 30 if i % 2 == 0 else -20
        closes.append(p)
    for _ in range(5):                                    # visszahúzódás → RSI 40 alá
        p -= 30
        closes.append(p)
    p += 100                                              # visszafordulás
    closes.append(p)
    h4 = bars(closes, H4, spread=0.0001)
    ev = TrendPullback("P2", CFG).evaluate(MarketContext(CFG, h4, []))
    v = ev.values
    assert v["trend"] and v["pullback"] and v["reversal"], v
    assert ev.entry and v["min_rsi_prev3"] < 40
    # visszafordulás nélkül nincs jelzés
    ev2 = TrendPullback("P2", CFG).evaluate(MarketContext(CFG, bars(closes[:-1], H4, spread=0.0001), []))
    assert not ev2.entry


def test_p2_no_entry_without_uptrend():
    closes = [60000 - 20 * i for i in range(200)] + [56000 - 100, 56100]
    ev = TrendPullback("P2", CFG).evaluate(MarketContext(CFG, bars(closes, H4), []))
    assert not ev.values["trend"] and not ev.entry


def test_p3_bollinger_only_in_range_market():
    r = random.Random(1)
    closes = [60000 + r.uniform(-400, 400) for _ in range(120)]        # zajos oldalazás → alacsony ADX
    closes.append(58500)                                               # az alsó szalag alá zár
    ev = BollingerReversion("P3", CFG).evaluate(MarketContext(CFG, bars(closes, H4, spread=0.001), []))
    assert ev.values["close_4h"] < ev.values["bb_lower_20"]
    assert ev.values["adx14_4h"] < 20 and ev.entry
    trend = [50000 + 200 * i for i in range(120)] + [50000 + 200 * 119 - 12000]   # erős trend → magas ADX
    ev2 = BollingerReversion("P3", CFG).evaluate(MarketContext(CFG, bars(trend, H4), []))
    assert ev2.values["close_4h"] < ev2.values["bb_lower_20"]
    assert ev2.values["adx14_4h"] >= 20 and not ev2.entry


def test_p3_exit_at_middle_band():
    r = random.Random(1)
    closes = [60000 + r.uniform(-400, 400) for _ in range(120)] + [60300]
    ev = BollingerReversion("P3", CFG).evaluate(MarketContext(CFG, bars(closes, H4, spread=0.001), []))
    assert ev.exit
