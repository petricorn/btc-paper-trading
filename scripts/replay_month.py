"""Fázis 1 átadás: 1 hónap valódi múltbeli adat visszajátszása, hibakereséssel.

Ellenőrzi:
  1. a futás végig hiba nélkül lefut (minden futás után invariáns-ellenőrzés a motorban),
  2. kétszer lefuttatva bitre azonos eredményt ad (determinizmus),
  3. ha minden 13. futás után elmentjük és visszatöltjük az állapotot, ugyanaz az eredmény,
  4. dupla futás nem okoz dupla trade-et, az elbukott mentés után a futás folytatódik,
  5. a független audit (nyers gyertyákból, pandas-szal újraszámolva) nem talál hibát.
A riport: reports/phase1_replay_<hónap>.md
"""
import argparse
import hashlib
import sys
import tempfile
import time
from collections import Counter
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from btcpaper.audit import audit  # noqa: E402
from btcpaper.config import load_config  # noqa: E402
from btcpaper.replay import HistoricalData, run_replay  # noqa: E402
from btcpaper.state import check_invariants, save_state  # noqa: E402
from btcpaper.timeutil import iso, parse_iso, budapest  # noqa: E402


def digest(state, folder: Path) -> str:
    save_state(state, folder)
    h = hashlib.sha256()
    for f in sorted(folder.iterdir()):
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--data", default="data/cache")
    ap.add_argument("--start", default="2026-10-01T00:00:00Z")
    ap.add_argument("--end", default="2026-11-01T00:00:00Z")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", default="replay_out")
    ap.add_argument("--report", default="reports/phase1_replay_2026-10.md")
    ap.add_argument("--stress", action="store_true",
                    help="laza, CSAK TESZTRE szánt paraméterek, hogy sok trade legyen (mechanika-próba)")
    a = ap.parse_args()
    cfg = load_config(a.config)
    if a.stress:
        from btcpaper.replay import stress_config
        cfg = stress_config(cfg)
    data = HistoricalData.load(a.data, cfg.get("instrument.coinbase_product"))
    start, end = int(parse_iso(a.start)), int(parse_iso(a.end))
    tmp = Path(tempfile.mkdtemp(prefix="replay_"))

    t0 = time.time()
    st1, rep1 = run_replay(cfg, data, start, end, seed=a.seed,
                           progress=lambda k, t: print(f"  futás #{k}, szimulált idő {iso(t)}", flush=True))
    t1 = time.time()
    print(f"1. visszajátszás kész: {t1 - t0:.0f} s")
    st2, _ = run_replay(cfg, data, start, end, seed=a.seed)
    print("2. visszajátszás kész (determinizmus)")
    st3, rep3 = run_replay(cfg, data, start, end, seed=a.seed, roundtrip_every=13, workdir=str(tmp / "rt"))
    print("3. visszajátszás kész (mentés/visszatöltés minden 13. futás után)")
    d1, d2, d3 = digest(st1, tmp / "a"), digest(st2, tmp / "b"), digest(st3, tmp / "c")
    check_invariants(st1, cfg)
    problems = audit(cfg, st1, data)
    save_state(st1, Path(a.out))

    # ---- riport
    cap = cfg.d("portfolios.initial_capital_usd")
    last_eq = {}
    for e in st1.equity:
        last_eq[e["portfolio"]] = e
    max_dd = {}
    for e in st1.equity:
        max_dd[e["portfolio"]] = max(max_dd.get(e["portfolio"], Decimal(0)), e["drawdown"])
    tr_count = Counter((t["portfolio"], t["reason"]) for t in st1.trades)
    c = st1.meta.counters
    runs_ok = sum(1 for r in st1.runs if r["data_ok"])
    lines = [
        "# Fázis 1 – 1 hónap visszajátszás (valódi Coinbase adat)" + (" – STRESSZ-PRÓBA" if a.stress else ""), "",
        *(["> Laza, csak tesztre szánt paraméterekkel (sok trade a mechanika ellenőrzéséhez). "
           "Ez NEM a valódi stratégia és nem értékelés.", ""] if a.stress else []),
        f"- Időszak: {iso(start)} – {iso(end)} (UTC)",
        f"- Config verzió: `{cfg.hash}`  ·  véletlen mag: {a.seed}",
        f"- Adat: Coinbase BTC-USD 1m/1h/1d, letöltve a nyilvános API-ról. Az 1 perces adatban "
        f"{c.get('m1_gaps_accepted', 0)} perc hiányzik a Coinbase-nél is (nem volt kötés) → elfogadott hiány.",
        "",
        "## Ellenőrzések", "",
        "| Ellenőrzés | Eredmény |", "|---|---|",
        f"| Futás végig, invariáns-hiba nélkül | ✅ ({rep1.runs_executed} futás, {t1 - t0:.0f} s) |",
        f"| Determinizmus (2 futás azonos) | {'✅' if d1 == d2 else '❌'} `{d1}` / `{d2}` |",
        f"| Mentés+visszatöltés minden 13. futás után = memóriában futtatva | {'✅' if d1 == d3 else '❌'} "
        f"`{d3}` ({rep3.roundtrips} mentés) |",
        f"| Dupla futás elutasítva | {'✅' if rep1.duplicate_runs == rep1.duplicate_runs_rejected else '❌'} "
        f"{rep1.duplicate_runs_rejected}/{rep1.duplicate_runs} |",
        f"| Elbukott mentés után folytatás a mentett állapotból | ✅ {rep1.save_failures} eset |",
        f"| Független audit (árak, első érintés, díjak, kockázat, jelzések pandas-szal) | "
        f"{'✅ 0 hiba' if not problems else '❌ ' + str(len(problems)) + ' hiba'} |",
        "", "## Szimulált GitHub-körülmények", "",
        f"- Tervezett futás (5 percenként): {rep1.runs_planned}; lefutott: {rep1.runs_executed}",
        f"- Kimaradt futás: {rep1.runs_skipped_missed}; késett futás (10–45 perc, ill. 1–1,5 óra): {rep1.runs_late}; "
        f"átfedés miatt összevont: {rep1.runs_skipped_overlap}",
        f"- Szándékos adat-hibák: {dict(rep1.injected)} → döntés nélküli futás: {rep1.data_fail_runs}",
        f"- Adat-hiba miatti döntés nélküli futások (motor számlálója): {c.get('runs_data_fail', 0)} "
        f"(kereszt-ellenőrzés: {c.get('fail_crosscheck', 0)}, régi adat: {c.get('fail_stale', 0)}, "
        f"hiány/duplikátum: {c.get('fail_gap', 0)}, letöltési hiba: {c.get('fail_fetch', 0)})",
        f"- Késés miatt elmaradt belépés: {c.get('entries_skipped_late', 0)}; stop alatti ár miatt: "
        f"{c.get('entries_skipped_below_stop', 0)}",
        f"- Riasztások az outboxban: " + ", ".join(f"{k}: {v}" for k, v in
                                                Counter(m['kind'] for m in st1.outbox).items()),
        "", "## Portfóliók a hónap végén (csak a mechanika ellenőrzése, NEM stratégia-értékelés)", "",
        "| Portfólió | Tőke ($) | Hozam | Max drawdown | Trade-sorok |", "|---|---|---|---|---|",
    ]
    for n in cfg.names:
        e = last_eq[n]
        ret = (e["equity"] / cap - 1) * 100
        rows = sum(v for (p, r), v in tr_count.items() if p == n)
        lines.append(f"| {n} | {e['equity']:.2f} | {ret:+.2f}% | {max_dd[n] * 100:.2f}% | {rows} |")
    lines += ["", "## Minden trade", "", "| Idő (Budapest) | Portfólió | Oldal | Ok | BTC | Ár | Érték $ | Díj $ | P&L $ |",
              "|---|---|---|---|---|---|---|---|---|"]
    for t in st1.trades:
        pnl = "" if t["pnl_usd"] is None else f"{t['pnl_usd']:.2f}"
        lines.append(f"| {budapest(t['time'])} | {t['portfolio']} | {t['side']} | {t['reason']} | {t['qty_btc']} | "
                     f"{t['price']:.2f} | {t['notional_usd']:.2f} | {t['fee_usd']:.4f} | {pnl} |")
    if problems:
        lines += ["", "## Audit hibák", ""] + [f"- {p}" for p in problems]
    lines += ["", "Megjegyzés: egy hónap és ennyi trade semmit nem mond a stratégiák jóságáról; ez csak a "
              "motor és a könyvelés helyességének próbája. A stratégiák értékelése a Fázis 2 (4+ év adat)."]
    Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    Path(a.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:40]))
    ok = d1 == d2 == d3 and not problems and rep1.duplicate_runs == rep1.duplicate_runs_rejected
    print("\nÖSSZESÍTÉS:", "MINDEN ELLENŐRZÉS ZÖLD" if ok else "HIBA VAN")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
