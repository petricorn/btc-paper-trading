"""Valódi Coinbase gyertyák letöltése a visszajátszáshoz (data/cache/, nincs a gitben).

Példa:  python scripts/download_history.py --start 2026-06-01 --end 2026-11-01T02:00:00
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from btcpaper.candles import check_series  # noqa: E402
from btcpaper.config import load_config  # noqa: E402
from btcpaper.http_client import HttpClient  # noqa: E402
from btcpaper.replay import write_candles  # noqa: E402
from btcpaper.sources import CoinbaseClient  # noqa: E402
from btcpaper.timeutil import iso, parse_iso  # noqa: E402


def ts(text):
    return int(parse_iso(text if "T" in text else text + "T00:00:00Z"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--out", default="data/cache")
    ap.add_argument("--m1-start", required=True)
    ap.add_argument("--h1-start", required=True)
    ap.add_argument("--d1-start", required=True)
    ap.add_argument("--end", required=True)
    a = ap.parse_args()
    cfg = load_config(a.config)
    cb = CoinbaseClient(HttpClient.from_config(cfg), cfg.get("instrument.coinbase_product"))
    end = ts(a.end)
    for gran, start in ((86400, ts(a.d1_start)), (3600, ts(a.h1_start)), (60, ts(a.m1_start))):
        candles = cb.candles(gran, start, end)
        chk = check_series(candles, gran)
        path = Path(a.out) / f"coinbase_{cb.product}_{gran}.csv"
        write_candles(path, chk.candles)
        print(f"{gran:>6}s: {len(chk.candles)} gyertya {iso(chk.candles[0].start)} .. {iso(chk.candles[-1].start)}"
              f"  duplikált={len(chk.duplicates)} hiány={len(chk.gaps)} hibás={len(chk.bad)}  -> {path}")
        if chk.gaps:
            print("   hiányzó kezdőidők (első 20):", [iso(g) for g in chk.gaps[:20]])
    print("HTTP kérések száma:", cb.http.request_count)


if __name__ == "__main__":
    main()
