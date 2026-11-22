"""Élő (paper) futás: friss nyilvános adat → ugyanaz a motor → állapot mentése.

Fázis 1-ben csak helyi állapotmappába ment. A "bot-state" ágra mentés, az outbox kiküldése
(Telegram) és a heartbeat a Fázis 3 része.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from .config import load_config
from .engine import Engine
from .http_client import HttpClient
from .snapshot import build_from_provider
from .sources import CoinbaseClient, KrakenClient
from .state import load_state, new_state, save_state


class LiveProvider:
    def __init__(self, cfg, http: HttpClient | None = None):
        self.http = http or HttpClient.from_config(cfg)
        self.cb = CoinbaseClient(self.http, cfg.get("instrument.coinbase_product"))
        self.kr = KrakenClient(self.http, cfg.get("instrument.kraken_pair"))

    def candles(self, gran, start, end):
        return self.cb.candles(gran, start, end)

    def quote(self):
        return self.cb.ticker()

    def ref_price(self):
        return self.kr.last_price(time.time())

    def clock_offset(self):
        server = self.cb.server_time()
        return time.time() - server


def default_run_id(now: float) -> str:
    gh = os.environ.get("GITHUB_RUN_ID")
    if gh:
        return f"gh-{gh}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    return f"local-{int(now)}"


def run_once(config_path: str, state_dir: str, run_id: str | None = None) -> dict:
    cfg = load_config(config_path)
    state_path = Path(state_dir)
    now = time.time()
    state = load_state(state_path) if (state_path / "portfolios.json").exists() else new_state(cfg, int(now))
    run_id = run_id or default_run_id(now)
    snap = build_from_provider(cfg, LiveProvider(cfg), now, run_id, state.meta.m1_cursor)
    result = Engine(cfg).run(state, snap)      # invariáns-hiba esetén kivételt dob → nincs mentés
    save_state(state, state_path)
    return {"result": result, "snapshot_issues": snap.issues, "metrics": snap.metrics}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Egy élő paper futás (szimuláció, valódi megbízás nincs)")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--state", default="state")
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args(argv)
    out = run_once(a.config, a.state, a.run_id)
    r = out["result"]
    if r.get("skipped"):
        print("Kihagyva:", r["reason"])
        return 0
    print("Adat rendben:" if r["data_ok"] else "NINCS DÖNTÉS, adatprobléma:", "; ".join(r["issues"]) or "igen")
    print("Feldolgozott 1m gyertya:", r["m1_processed"], " Új trade-ek:", len(r["new_trades"]))
    for t in r["new_trades"]:
        print(" ", t["trade_id"], t["side"], t["reason"], t["qty_btc"], "@", t["price"])
    print("Mérőszámok:", out["metrics"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
