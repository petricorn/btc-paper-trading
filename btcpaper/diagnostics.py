"""Diagnostics: minden adatforrás végpontjának tesztje (a GitHub futtatóról futtatva).

Kötelező végpontok (ha bármelyik hibás → piros a workflow):
  Coinbase: candles 1m/1h/6h/1d, lapozás, ticker, szerveridő; Kraken: OHLC 1m, ticker.
Opcionális végpontok (csak jelentjük): Fear & Greed, funding rate / open interest jelöltek.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .candles import check_series
from .config import load_config
from .http_client import HttpClient
from .sources import CoinbaseClient, KrakenClient, fear_greed
from .timeutil import iso


def _check(name, required, fn):
    t0 = time.monotonic()
    try:
        detail = fn()
        ok, err = True, ""
    except Exception as e:  # noqa: BLE001
        detail, ok, err = "", False, f"{type(e).__name__}: {e}"[:300]
    return {"name": name, "required": required, "ok": ok, "ms": int((time.monotonic() - t0) * 1000),
            "detail": detail, "error": err}


def run_diagnostics(cfg) -> list[dict]:
    http = HttpClient.from_config(cfg)
    http.max_retries = 2
    cb = CoinbaseClient(http, cfg.get("instrument.coinbase_product"))
    kr = KrakenClient(http, cfg.get("instrument.kraken_pair"))
    now = int(time.time())
    res = []

    def cb_candles(gran, n):
        def f():
            c = cb.candles(gran, now - n * gran, now)
            chk = check_series(c, gran)
            if not c:
                raise RuntimeError("üres válasz")
            age = now - c[-1].start
            if age > 2 * gran + 120:
                raise RuntimeError(f"az utolsó gyertya túl régi: {age} s")
            return f"{len(c)} gyertya, utolsó {iso(c[-1].start)} (kor {age} s), hiány={len(chk.gaps)} dupl={len(chk.duplicates)}"
        return f

    res.append(_check("Coinbase candles 1m", True, cb_candles(60, 30)))
    res.append(_check("Coinbase candles 1h", True, cb_candles(3600, 48)))
    res.append(_check("Coinbase candles 6h", True, cb_candles(21600, 20)))
    res.append(_check("Coinbase candles 1d", True, cb_candles(86400, 30)))

    def paging():
        start = now - 700 * 60
        c = cb.candles(60, start, now)
        chk = check_series(c, 60)
        if chk.duplicates:
            raise RuntimeError(f"duplikátum lapozásnál: {chk.duplicates[:3]}")
        if len(c) < 650:
            raise RuntimeError(f"túl kevés gyertya: {len(c)}")
        return f"700 perc 3 lapon: {len(c)} gyertya, hiány={len(chk.gaps)}, duplikátum=0"

    res.append(_check("Coinbase lapozás (3 kérés)", True, paging))

    def ticker():
        q = cb.ticker()
        if not (q.bid > 0 and q.ask >= q.bid):
            raise RuntimeError(f"ellentmondásos bid/ask: {q.bid}/{q.ask}")
        return f"bid {q.bid} ask {q.ask} last {q.last} (kor {time.time() - q.time:.1f} s)"

    res.append(_check("Coinbase ticker", True, ticker))
    res.append(_check("Coinbase szerveridő", True, lambda: f"óraeltérés {time.time() - cb.server_time():.2f} s"))

    def kr_last():
        r = kr.last_price(time.time())
        return f"utolsó ár {r.price} (kor {time.time() - r.time:.0f} s)"

    res.append(_check("Kraken OHLC 1m (utolsó ár)", True, kr_last))

    def kr_ticker():
        d = http.get_json("https://api.kraken.com/0/public/Ticker", params={"pair": kr.pair})
        if d.get("error"):
            raise RuntimeError(str(d["error"]))
        v = list(d["result"].values())[0]
        return f"ask {v['a'][0]} bid {v['b'][0]} last {v['c'][0]}"

    res.append(_check("Kraken ticker", True, kr_ticker))

    def cross():
        q = cb.ticker()
        r = kr.last_price(time.time())
        diff = abs(q.last - r.price) / r.price * 100
        return f"Coinbase {q.last} vs Kraken {r.price}: eltérés {float(diff):.4f}%"

    res.append(_check("Kereszt-ellenőrzés (tájékoztató)", False, cross))

    def fg():
        d = fear_greed(http)
        return f"{d['value']} ({d['label']}), {iso(d['time'])}"

    res.append(_check("Fear & Greed (alternative.me)", False, fg))

    def jget(url, params=None):
        return lambda: http.get_json(url, params=params)

    def okx_funding():
        d = jget("https://www.okx.com/api/v5/public/funding-rate", {"instId": "BTC-USDT-SWAP"})()
        return f"fundingRate {d['data'][0]['fundingRate']}"

    def okx_oi():
        d = jget("https://www.okx.com/api/v5/public/open-interest", {"instType": "SWAP", "instId": "BTC-USDT-SWAP"})()
        return f"oi {d['data'][0]['oi']} (oiCcy {d['data'][0].get('oiCcy')})"

    def bybit():
        d = jget("https://api.bybit.com/v5/market/tickers", {"category": "linear", "symbol": "BTCUSDT"})()
        x = d["result"]["list"][0]
        return f"fundingRate {x['fundingRate']} openInterest {x['openInterest']}"

    def deribit():
        d = jget("https://www.deribit.com/api/v2/public/get_book_summary_by_instrument",
                 {"instrument_name": "BTC-PERPETUAL"})()
        x = d["result"][0]
        return f"funding_8h {x.get('funding_8h')} open_interest {x.get('open_interest')}"

    def kraken_fut():
        d = jget("https://futures.kraken.com/derivatives/api/v3/tickers")()
        x = [t for t in d["tickers"] if t.get("symbol") == "PF_XBTUSD"][0]
        return f"fundingRate {x.get('fundingRate')} openInterest {x.get('openInterest')}"

    res.append(_check("Funding: OKX", False, okx_funding))
    res.append(_check("Open interest: OKX", False, okx_oi))
    res.append(_check("Funding + OI: Bybit", False, bybit))
    res.append(_check("Funding + OI: Deribit", False, deribit))
    res.append(_check("Funding + OI: Kraken Futures", False, kraken_fut))
    return res


def to_markdown(results: list[dict]) -> str:
    lines = ["# Diagnostics – adatforrások", "", f"Futás ideje (UTC): {iso(time.time())}", "",
             "| Végpont | Kötelező | Eredmény | Idő (ms) | Részletek |", "|---|---|---|---|---|"]
    for r in results:
        mark = "✅ működik" if r["ok"] else "❌ HIBA"
        det = (r["detail"] if r["ok"] else r["error"]).replace("|", "/")
        lines.append(f"| {r['name']} | {'igen' if r['required'] else 'nem'} | {mark} | {r['ms']} | {det} |")
    req_ok = all(r["ok"] for r in results if r["required"])
    lines += ["", "**Összesítés:** " + ("minden kötelező végpont működik ✅" if req_ok
                                       else "legalább egy kötelező végpont HIBÁS ❌")]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--out", default="diagnostics_out")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    results = run_diagnostics(cfg)
    md = to_markdown(results)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "diagnostics.md").write_text(md, encoding="utf-8")
    (out / "diagnostics.json").write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str),
                                          encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(md)
    print(md)
    return 0 if all(r["ok"] for r in results if r["required"]) else 1


if __name__ == "__main__":
    sys.exit(main())
