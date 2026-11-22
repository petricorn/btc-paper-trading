"""Hosszú időszak letöltése (Fázis 2): Coinbase BTC-USD 1m havi fájlokba, 1h és 1d egy-egy fájlba.

Folytatható: a már kész havi fájlokat kihagyja (ha megszakad, újraindítva onnan folytatja).
Csak nyilvános piaci adat, API kulcs nélkül.

Példa:  python scripts/download_full.py --start 2018-01-01 --warmup-start 2017-03-01 --end 2026-11-22
"""
import argparse
import sys
import time
from datetime import datetime, timezone
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


def month_starts(start: int, end: int):
    d = datetime.fromtimestamp(start, timezone.utc).replace(day=1, hour=0, minute=0, second=0)
    while int(d.timestamp()) < end:
        nxt = d.replace(year=d.year + 1, month=1) if d.month == 12 else d.replace(month=d.month + 1)
        yield d, int(d.timestamp()), int(nxt.timestamp())
        d = nxt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--out", default="data/full")
    ap.add_argument("--start", required=True, help="1 perces adat kezdete")
    ap.add_argument("--warmup-start", required=True, help="1h/1d adat kezdete (indikátor-bemelegítés)")
    ap.add_argument("--end", required=True)
    a = ap.parse_args()
    cfg = load_config(a.config)
    cb = CoinbaseClient(HttpClient.from_config(cfg), cfg.get("instrument.coinbase_product"))
    out = Path(a.out)
    end = ts(a.end)
    for gran in (86400, 3600):
        path = out / f"coinbase_{cb.product}_{gran}.csv"
        c = cb.candles(gran, ts(a.warmup_start), end - gran)
        chk = check_series(c, gran)
        write_candles(path, chk.candles)
        print(f"{gran}s: {len(chk.candles)} gyertya, hiány={len(chk.gaps)} dupl={len(chk.duplicates)}", flush=True)
    t0 = time.time()
    total_gaps = 0
    for d, ms, me in month_starts(ts(a.start), end):
        path = out / "m1" / f"{d:%Y-%m}.csv"
        done = path.with_suffix(".done")
        if done.exists():
            continue
        last = min(me, end) - 60
        c = cb.candles(60, ms, last)
        chk = check_series(c, 60)
        if chk.duplicates or chk.bad:
            raise SystemExit(f"{d:%Y-%m}: hibás adat (duplikált={len(chk.duplicates)}, hibás={len(chk.bad)})")
        write_candles(path, chk.candles)
        missing_head = (chk.candles[0].start - ms) // 60 if chk.candles else 0
        missing_tail = (last - chk.candles[-1].start) // 60 if chk.candles else 0
        gaps = len(chk.gaps) + missing_head + missing_tail
        total_gaps += gaps
        done.write_text(f"{len(chk.candles)} {gaps}\n", encoding="utf-8")
        print(f"{d:%Y-%m}: {len(chk.candles)} gyertya, hiányzó perc={gaps}, eltelt {time.time() - t0:.0f} s, "
              f"kérések {cb.http.request_count}", flush=True)
    print(f"KÉSZ. Összes hiányzó perc: {total_gaps}. Vége: {iso(end)}", flush=True)


if __name__ == "__main__":
    main()
