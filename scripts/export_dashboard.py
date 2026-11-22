"""A webes felület adatfájljának elkészítése egy állapotmappából.

Példa (demó a visszajátszásból):
  python scripts/export_dashboard.py --state replay_out_stress --out docs/data/demo.json --source demo \
      --note "DEMÓ: 2026. október visszajátszása valódi adaton, laza tesztparaméterekkel"
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from btcpaper.config import load_config  # noqa: E402
from btcpaper.dashboard import write_dashboard  # noqa: E402
from btcpaper.state import load_state  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--config", default="config.yaml")
ap.add_argument("--state", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--source", choices=["demo", "live"], default="live")
ap.add_argument("--note", default="")
ap.add_argument("--stress", action="store_true", help="a stressz-próba (laza teszt) paramétereivel készült állapot")
a = ap.parse_args()
st = load_state(a.state)
cfg = load_config(a.config)
if a.stress:
    from btcpaper.replay import stress_config
    cfg = stress_config(cfg)
d = write_dashboard(st, cfg, a.out, a.source, a.note)
print(f"{a.out}: {len(d['trades'])} trade, {len(d['runs'])} futás, {sum(len(p['equity_series']) for p in d['portfolios'])} pont")
