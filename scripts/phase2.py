"""Fázis 2 vezérlő: backteszt, walk-forward, robusztusság, Monte Carlo, riport.

Lépések:
  python scripts/phase2.py insample      # rács + walk-forward + alapparaméterek + robusztusság + riport
  python scripts/phase2.py holdout       # a tartalék EGYSZERI kiértékelése (utána zárolva)

Minden futás eredménye a results/phase2/ mappába kerül (újrafuttatáskor nem számolja újra).
"""
import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from btcpaper.backtest import (ALL, STRATS, Choice, add_months, combo_key, grid_combos, load_result,  # noqa: E402
                               make_config, run_backtest, save_result, select_params, ts, wf_windows)
from btcpaper.config import load_config  # noqa: E402
from btcpaper.metrics import compute_stats, daily_returns, monte_carlo_drawdowns, max_drawdown  # noqa: E402
from btcpaper.timeutil import iso  # noqa: E402

DATA = None
RESULTS = Path("results/phase2")
HOLDOUT_LOCK = Path("reports/phase2_holdout_DONE.txt")


def _init(data_dir):
    global DATA
    from btcpaper.compact import load_full
    DATA = load_full(data_dir)


def _job(job):
    path = RESULTS / f"{job['name']}.json.gz"
    if path.exists():
        return job["name"], "cache"
    cfg = load_config(job["config"])
    c = make_config(cfg, job["params"], kill_switch=job["kill_switch"])
    t0 = time.time()
    r = run_backtest(c, DATA, job["start"], job["end"], job["name"], job["params"], seed=job.get("seed", 1),
                     delay_min=job.get("delay_min"), delay_max=job.get("delay_max"),
                     audit_check=job.get("audit", False))
    save_result(r, path)
    return job["name"], f"{time.time() - t0:.0f} s"


def run_jobs(jobs, data_dir, workers):
    todo = [j for j in jobs if not (RESULTS / f"{j['name']}.json.gz").exists()]
    print(f"{len(jobs)} futás, ebből számolandó: {len(todo)}", flush=True)
    if not todo:
        return
    with mp.get_context("spawn").Pool(processes=min(workers, len(todo)), initializer=_init,
                                      initargs=(data_dir,)) as pool:
        for name, info in pool.imap_unordered(_job, todo):
            print(f"  kész: {name} ({info})", flush=True)


def grid_jobs(cfg, config_path):
    start, hold = ts(cfg.get("backtest.data_start")), ts(cfg.get("backtest.holdout_start"))
    combos = {n: grid_combos(cfg, n) for n in STRATS}
    n = max(len(v) for v in combos.values())
    jobs = []
    for i in range(n):
        params = {s: combos[s][i % len(combos[s])] for s in STRATS}
        jobs.append({"name": f"grid_{i:02d}", "config": config_path, "params": params, "kill_switch": False,
                     "start": start, "end": hold})
    return jobs


def grid_index(cfg):
    """stratégia → combo_key → RunResult (a rácsfutásokból)."""
    out = {s: {} for s in STRATS}
    combos = {n: grid_combos(cfg, n) for n in STRATS}
    n = max(len(v) for v in combos.values())
    for i in range(n):
        r = load_result(RESULTS / f"grid_{i:02d}.json.gz")
        for s in STRATS:
            out[s].setdefault(combo_key(r.params[s]), r)
    return out


def fmt_pct(x):
    return f"{x * 100:+.1f}%" if x == x else "–"


def fmt(x, d=2):
    if x == float("inf"):
        return "∞"
    return f"{x:.{d}f}"


def stats_row(label, st):
    return (f"| {label} | {fmt_pct(st.total_return)} | {fmt_pct(st.cagr)} | {st.max_drawdown * 100:.1f}% | "
            f"{fmt(st.sharpe)} | {st.win_rate * 100:.0f}% | {fmt(st.profit_factor)} | {st.trades} |")


HEAD = ["| Portfólió | Hozam | CAGR | Max DD | Sharpe | Win rate | Profit factor | Trade-ek |",
        "|---|---|---|---|---|---|---|---|"]


def stitched(cfg, choices, name):
    """A walk-forward teszt-ablakok összefűzve: napi hozamok, kötések, max DD."""
    rets, trips = [], []
    for ch in choices:
        a, b = ch.test
        r = load_result(RESULTS / f"wf_{ch.window:02d}.json.gz")
        if ch.params is None:
            days = len(daily_returns(r.equity["B1"], a, b))
            rets += [0.0] * days            # készpénzben marad
            continue
        rets += daily_returns(r.equity[name], a, b)
        trips += [t for t in r.trips(name) if a <= t.exit_time < b]
    return compute_stats(rets, trips), trips


def verdict(st, b1, b2):
    better_sharpe = st.sharpe > b1.sharpe and st.sharpe > b2.sharpe
    better_dd = st.max_drawdown < b1.max_drawdown and st.max_drawdown < b2.max_drawdown
    if better_sharpe and better_dd:
        return "JOBB mindkét mércénél (Sharpe magasabb ÉS max drawdown kisebb)"
    if better_dd and not better_sharpe:
        return "kisebb a visszaesése, de a Sharpe-ja NEM jobb mindkét mércénél → nem jobb kockázattal korrigálva"
    if better_sharpe and not better_dd:
        return "magasabb Sharpe, de nagyobb visszaesés valamelyik mércénél → nem egyértelműen jobb"
    return "NEM jobb a mércéknél"


def insample(a, cfg):
    start, hold = ts(cfg.get("backtest.data_start")), ts(cfg.get("backtest.holdout_start"))
    t0 = time.time()
    # 1) rács (kill switch nélkül, hogy egy korai leállás ne zárja ki a paramétert későbbi ablakokból)
    run_jobs(grid_jobs(cfg, a.config), a.data, a.workers)
    gi = grid_index(cfg)
    # 2) walk-forward kiválasztás
    windows = wf_windows(cfg)
    choices = {s: [] for s in STRATS}
    wf_jobs = []
    for k, (train, test) in enumerate(windows):
        chosen = {}
        for s in STRATS:
            params, sh, n, nb, cands = select_params(cfg, s, gi[s], train)
            choices[s].append(Choice(k, train, test, params, sh, n, nb, cands))
            if params is not None:
                chosen[s] = params
        # a teszt-ablak friss 200 USD-vel, kill switch BE; a nem kiválasztott stratégia alapparaméterrel
        # fut, de az eredményét nem használjuk (készpénzben maradónak számít)
        wf_jobs.append({"name": f"wf_{k:02d}", "config": a.config, "params": chosen, "kill_switch": True,
                        "start": test[0], "end": test[1]})
    oos_start = windows[0][1][0]
    extra = [
        {"name": "default_full", "config": a.config, "params": {}, "kill_switch": True, "start": start,
         "end": hold, "audit": True},
        {"name": "bench_oos", "config": a.config, "params": {}, "kill_switch": True, "start": oos_start,
         "end": hold},
        {"name": "robust_delay", "config": a.config, "params": {}, "kill_switch": True, "start": start,
         "end": hold, "seed": 99, "delay_min": 0, "delay_max": cfg.i("backtest.robustness_delay_max_seconds")},
    ]
    run_jobs(wf_jobs + extra, a.data, a.workers)
    print(f"Számolás kész: {time.time() - t0:.0f} s", flush=True)
    # mentjük a kiválasztást (a tartalékhoz is kell)
    (RESULTS / "choices.json").write_text(json.dumps(
        {s: [{"window": c.window, "train": c.train, "test": c.test, "params": c.params,
              "train_sharpe": c.train_sharpe, "train_trades": c.train_trades, "neighbor_sharpe": c.neighbor_sharpe,
              "candidates": c.candidates} for c in v] for s, v in choices.items()}, indent=1), encoding="utf-8")
    # 3) riport
    report(cfg, choices, start, hold, oos_start)


def report(cfg, choices, start, hold, oos_start):
    d = load_result(RESULTS / "default_full.json.gz")
    bo = load_result(RESULTS / "bench_oos.json.gz")
    rb = load_result(RESULTS / "robust_delay.json.gz")
    L = ["# Fázis 2 – Backteszt és stratégiaválasztás (mintán belül)", "",
         "> Szimuláció valódi Coinbase BTC-USD adaton, díjakkal (0,4%/oldal) és csúszással (0,05%). "
         "Ugyanaz a motor, mint élőben. Ez nem befektetési tanács.", "",
         f"- Mintán belüli időszak: {iso(start)[:10]} – {iso(hold)[:10]} · tartalék (még érintetlen): "
         f"{cfg.get('backtest.holdout_start')} – {cfg.get('backtest.holdout_end')}",
         f"- Walk-forward: {cfg.i('backtest.train_months')} hó tanítás → {cfg.i('backtest.test_months')} hó teszt, "
         f"{len(choices['P1'])} teszt-ablak ({iso(oos_start)[:10]} – {iso(hold)[:10]})",
         f"- Kiválasztás: tanító Sharpe, legalább {cfg.i('backtest.min_trades')} kötés, Sharpe > 0, és a rácsbeli "
         f"szomszédok átlag Sharpe-ja ≥ {cfg.get('backtest.plateau_ratio')} × a választotté. Ha nincs ilyen, "
         "a stratégia abban a teszt-ablakban készpénzben marad.",
         f"- Független audit az alapparaméteres teljes futáson: "
         f"{'0 hiba ✅' if d.report.get('audit_problems') == [] else str(d.report.get('audit_problems'))[:500]}",
         ""]
    # A) alapparaméterek, teljes mintán belül
    L += ["## A) Alapparaméterek (a specifikáció szerinti), teljes mintán belüli időszak", ""] + HEAD
    sa = {n: d.stats(n, start, hold) for n in ALL}
    for n in ALL:
        L.append(stats_row(n, sa[n]))
    # B) walk-forward OOS
    L += ["", "## B) Walk-forward, csak mintán kívüli (teszt) ablakok összefűzve", ""] + HEAD
    sb = {}
    trips_b = {}
    for s in STRATS:
        sb[s], trips_b[s] = stitched(cfg, choices[s], s)
        L.append(stats_row(s + " (WF)", sb[s]))
    for n in ("B1", "B2"):
        sb[n] = bo.stats(n, oos_start, hold)
        L.append(stats_row(n, sb[n]))
    # ítélet
    L += ["", "## Ítélet (kockázattal korrigálva, díjak után)", ""]
    for s in STRATS:
        L.append(f"- **{s}** alapparaméterrel: {verdict(sa[s], sa['B1'], sa['B2'])}; walk-forward: "
                 f"{verdict(sb[s], sb['B1'], sb['B2'])}.")
    # walk-forward választások
    L += ["", "## Walk-forward paraméter-választások", "", "| Teszt-ablak | P1 | P2 | P3 |", "|---|---|---|---|"]
    for k in range(len(choices["P1"])):
        cells = []
        for s in STRATS:
            c = choices[s][k]
            cells.append("készpénz (nincs alkalmas)" if c.params is None else
                         ", ".join(f"{v}" for v in c.params.values()) + f" (Sh {c.train_sharpe:.2f}, {c.train_trades} kötés)")
        a_, b_ = choices["P1"][k].test
        L.append(f"| {iso(a_)[:10]} – {iso(b_)[:10]} | " + " | ".join(cells) + " |")
    # Monte Carlo
    L += ["", "## Monte Carlo (a kötések sorrendjének keverése, 10 000×) – max drawdown eloszlás", "",
          "| Stratégia | Kötések | Tényleges sorrend | Medián | 95% eset ennél jobb | Legrosszabb |", "|---|---|---|---|---|---|"]
    for s in STRATS:
        for label, trips in ((f"{s} alap", d.trips(s)), (f"{s} WF", trips_b[s])):
            mc = monte_carlo_drawdowns([t.ret for t in trips], n=cfg.i("backtest.monte_carlo_runs"))
            if mc.get("n"):
                L.append(f"| {label} | {mc['trades']} | {mc['actual_order'] * 100:.1f}% | {mc['p50'] * 100:.1f}% | "
                         f"{mc['p95'] * 100:.1f}% | {mc['max'] * 100:.1f}% |")
            else:
                L.append(f"| {label} | 0 | – | – | – | – |")
    # robusztusság: késés
    L += ["", "## Robusztusság: véletlen 0–55 perces futási késés (alapparaméterek)", ""] + HEAD
    for n in STRATS:
        L.append(stats_row(n + " fix 2 perc", sa[n]))
        L.append(stats_row(n + " 0–55 perc", rb.stats(n, start, hold)))
    # paraméter-érzékenység (teljes időszak, rács)
    gi = grid_index(cfg)
    L += ["", "## Paraméter-érzékenység: Sharpe a teljes mintán belüli időszakon (kill switch nélkül)", ""]
    for s in STRATS:
        rows = []
        for combo in grid_combos(cfg, s):
            r = gi[s][combo_key(combo)]
            st = r.stats(s, start, hold)
            rows.append((st.sharpe, combo, st))
        rows.sort(key=lambda x: -x[0])
        L += [f"**{s}** (legjobb 5 és legrosszabb 3):", "", "| Paraméterek | Sharpe | Hozam | Max DD | Kötések |",
              "|---|---|---|---|---|"]
        for sh, combo, st in rows[:5] + rows[-3:]:
            L.append(f"| {', '.join(f'{k}={v}' for k, v in combo.items())} | {sh:.2f} | {fmt_pct(st.total_return)} | "
                     f"{st.max_drawdown * 100:.1f}% | {st.trades} |")
        L.append("")
    L += ["## Adat és futás", "",
          f"- Alapfutás: {d.report['runs']} szimulált futás, ebből {d.report['retry_runs']} újrapróbálás adat-hiba "
          f"után; adat-hiba miatti döntés nélküli futás: {d.counters.get('runs_data_fail', 0)}; elfogadott hiányzó "
          f"1 perces gyertya: {d.counters.get('m1_gaps_accepted', 0)}; késés miatt elmaradt belépés: "
          f"{d.counters.get('entries_skipped_late', 0)}.",
          "- Ismert közelítések: múltbeli bid/ask nincs (a futás percének nyitóára + csúszás); a futás 4H zárás után "
          "2 perccel történik (élőben 5 percenként, késésekkel – ld. robusztussági táblázat).",
          "", "A tartalék (utolsó 6 hónap) kiértékelése külön lépés, egyszer: `python scripts/phase2.py holdout`."]
    out = Path("reports/phase2_backtest.md")
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:60]))


def holdout(a, cfg):
    if HOLDOUT_LOCK.exists():
        raise SystemExit(f"A tartalék már ki lett értékelve ({HOLDOUT_LOCK.read_text(encoding='utf-8').strip()}). "
                         "Újrafuttatás nem megengedett.")
    hs, he = ts(cfg.get("backtest.holdout_start")), ts(cfg.get("backtest.holdout_end"))
    gi = grid_index(cfg)
    train = (add_months(hs, -cfg.i("backtest.train_months")), hs)
    chosen, info = {}, {}
    for s in STRATS:
        params, sh, n, nb, cands = select_params(cfg, s, gi[s], train)
        info[s] = {"params": params, "train_sharpe": sh, "train_trades": n, "neighbor_sharpe": nb, "candidates": cands}
        if params is not None:
            chosen[s] = params
    job = {"name": "holdout", "config": a.config, "params": chosen, "kill_switch": True, "start": hs, "end": he,
           "audit": True}
    run_jobs([job], a.data, 1)
    r = load_result(RESULTS / "holdout.json.gz")
    HOLDOUT_LOCK.write_text(f"kiértékelve {iso(time.time())}, config {r.config_hash}\n", encoding="utf-8")
    L = ["", "## C) TARTALÉK (utolsó 6 hónap, egyszeri kiértékelés)", "",
         f"- Időszak: {cfg.get('backtest.holdout_start')} – {cfg.get('backtest.holdout_end')}; a paramétereket a "
         f"megelőző {cfg.i('backtest.train_months')} hónapon választottuk, ugyanazzal a szabállyal.",
         f"- Független audit: {'0 hiba ✅' if r.report.get('audit_problems') == [] else r.report.get('audit_problems')}",
         ""] + HEAD
    st = {n: r.stats(n, hs, he) for n in ALL}
    for n in ALL:
        if n in STRATS and info[n]["params"] is None:
            L.append(f"| {n} | készpénz (nem volt alkalmas paraméter) | | | | | | 0 |")
        else:
            L.append(stats_row(n, st[n]))
    L += ["", "Választott paraméterek: " + "; ".join(f"{s}: {info[s]['params']}" for s in STRATS), ""]
    for s in STRATS:
        if info[s]["params"] is not None:
            L.append(f"- **{s}**: {verdict(st[s], st['B1'], st['B2'])}.")
    out = Path("reports/phase2_backtest.md")
    out.write_text(out.read_text(encoding="utf-8") + "\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["insample", "holdout", "report"])
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--data", default="data/full")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    from btcpaper.awake import keep_awake
    keep_awake()                            # amíg számol, a gép ne aludjon el
    cfg = load_config(a.config)
    RESULTS.mkdir(parents=True, exist_ok=True)
    from btcpaper.compact import load_full
    load_full(a.data)                       # tömör tár építése egyszer, a párhuzamos munkák előtt
    if a.stage == "insample":
        insample(a, cfg)
    elif a.stage == "report":
        ch = json.loads((RESULTS / "choices.json").read_text(encoding="utf-8"))
        choices = {s: [Choice(c["window"], tuple(c["train"]), tuple(c["test"]), c["params"], c["train_sharpe"],
                              c["train_trades"], c["neighbor_sharpe"], c["candidates"]) for c in v]
                   for s, v in ch.items()}
        start, hold = ts(cfg.get("backtest.data_start")), ts(cfg.get("backtest.holdout_start"))
        report(cfg, choices, start, hold, wf_windows(cfg)[0][1][0])
    else:
        holdout(a, cfg)


if __name__ == "__main__":
    main()
