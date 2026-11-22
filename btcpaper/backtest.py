"""Fázis 2: backteszt UGYANAZZAL a motorral (replay), paraméterrács, walk-forward, fennsík-szabály.

Nincs külön backteszt-logika: minden futás a `run_replay` → `Engine` láncon megy. A gyorsítás
egyetlen eltérése az élő futáshoz képest a futásrend: a szimulált futás minden 4H zárás után
`run_offset_seconds`-szel történik (adat-hiba esetén 5 percenként újrapróbál, mint az élő cron).
A stopok/célok így is percre pontosan teljesülnek, mert a motor minden 1 perces gyertyát feldolgoz.
"""
from __future__ import annotations

import copy
import gzip
import itertools
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import Config, config_from_dict
from .metrics import RoundTrip, compute_stats, daily_returns, max_drawdown, round_trips
from .replay import run_replay
from .timeutil import H4, parse_iso

STRATS = ("P1", "P2", "P3")
ALL = ("P1", "P2", "P3", "B1", "B2")


def ts(text: str) -> int:
    return int(parse_iso(text if "T" in text else text + "T00:00:00Z"))


def add_months(t: int, months: int) -> int:
    d = datetime.fromtimestamp(t, timezone.utc)
    m = d.month - 1 + months
    return int(d.replace(year=d.year + m // 12, month=m % 12 + 1).timestamp())


# ------------------------------------------------------------------ paraméterrács

def grid_combos(cfg: Config, name: str) -> list[dict]:
    g = cfg.get(f"backtest.grid.{name}")
    keys = list(g)
    return [dict(zip(keys, vals)) for vals in itertools.product(*(g[k] for k in keys))]


def neighbors(cfg: Config, name: str, combo: dict) -> list[dict]:
    """A rácsban egy lépésre lévő paraméter-kombinációk (egyszerre egy paraméter változik)."""
    g = cfg.get(f"backtest.grid.{name}")
    out = []
    for k, values in g.items():
        i = values.index(combo[k])
        for j in (i - 1, i + 1):
            if 0 <= j < len(values):
                n = dict(combo)
                n[k] = values[j]
                out.append(n)
    return out


def combo_key(combo: dict) -> str:
    return json.dumps(combo, sort_keys=True)


def make_config(cfg: Config, params: dict[str, dict] | None = None, kill_switch: bool = True) -> Config:
    raw = copy.deepcopy(cfg.raw)
    for name, combo in (params or {}).items():
        raw["strategies"][name].update(combo)
    raw["risk"]["kill_switch_enabled"] = kill_switch
    return config_from_dict(raw)


# ------------------------------------------------------------------ egy backteszt-futás

@dataclass
class RunResult:
    label: str
    config_hash: str
    params: dict
    start: int
    end: int
    equity: dict          # portfólió → [(idő, tőke)]
    trades: list          # trade-sorok (szövegesítve)
    counters: dict
    report: dict

    def trips(self, name: str) -> list[RoundTrip]:
        return round_trips(self.trades, name)

    def stats(self, name: str, start: int, end: int):
        rets = daily_returns(self.equity[name], start, end)
        trips = [t for t in self.trips(name) if start <= t.exit_time < end]
        return compute_stats(rets, trips, max_drawdown(self.equity[name], start, end))

    def to_json(self) -> dict:
        return {"label": self.label, "config_hash": self.config_hash, "params": self.params, "start": self.start,
                "end": self.end, "equity": self.equity, "trades": self.trades, "counters": self.counters,
                "report": self.report}

    @classmethod
    def from_json(cls, d: dict) -> "RunResult":
        d = dict(d)
        d["equity"] = {k: [tuple(x) for x in v] for k, v in d["equity"].items()}
        return cls(**d)


def run_backtest(cfg: Config, data, start: int, end: int, label: str, params: dict, seed: int = 1,
                 delay_min: float | None = None, delay_max: float | None = None,
                 audit_check: bool = False) -> RunResult:
    off = cfg.i("backtest.run_offset_seconds")
    first = ((start + H4 - 1) // H4) * H4          # az első 4H zárás a kezdetkor vagy utána
    state, rep = run_replay(cfg, data, first, end, seed=seed, interval=H4, scenario=False,
                            delay_min=off if delay_min is None else delay_min,
                            delay_max=off if delay_max is None else delay_max,
                            retry_after=cfg.i("backtest.retry_seconds"))
    problems = None
    if audit_check:
        from .audit import audit
        from .state import check_invariants
        check_invariants(state, cfg)
        problems = audit(cfg, state, data)
    eq = {n: [] for n in ALL}
    for e in state.equity:
        eq[e["portfolio"]].append((int(e["time"]), float(e["equity"])))
    trades = [{k: (str(v) if v is not None else None) for k, v in t.items()} for t in state.trades]
    return RunResult(label=label, config_hash=cfg.hash, params=params, start=start, end=end, equity=eq,
                     trades=trades, counters=dict(state.meta.counters),
                     report={"runs": rep.runs_executed, "retry_runs": rep.retry_runs,
                             "data_fail_runs": rep.data_fail_runs, "audit_problems": problems})


def save_result(r: RunResult, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(r.to_json(), f)


def load_result(path: Path) -> RunResult:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return RunResult.from_json(json.load(f))


# ------------------------------------------------------------------ walk-forward kiválasztás

@dataclass
class Choice:
    window: int
    train: tuple
    test: tuple
    params: dict | None          # None = nincs alkalmas paraméter → készpénzben marad
    train_sharpe: float | None
    train_trades: int | None
    neighbor_sharpe: float | None
    candidates: int              # hány paraméter felelt meg a feltételeknek


def wf_windows(cfg: Config) -> list[tuple]:
    start = ts(cfg.get("backtest.data_start"))
    hold = ts(cfg.get("backtest.holdout_start"))
    tr, te = cfg.i("backtest.train_months"), cfg.i("backtest.test_months")
    out = []
    s = start
    while add_months(s, tr) < hold:
        a, b = s, add_months(s, tr)
        c = min(add_months(b, te), hold)
        out.append(((a, b), (b, c)))
        s = add_months(s, te)
    return out


def select_params(cfg: Config, name: str, grid_results: dict, train: tuple) -> tuple:
    """grid_results: combo_key → RunResult (a teljes időszakra). Visszaad: (params, sharpe, trades,
    szomszéd-átlag, jelöltek száma). Szabály: >= min_trades kötés, Sharpe > 0, és a rácsbeli
    szomszédok átlag Sharpe-ja >= plateau_ratio × a saját Sharpe; ezek közül a legnagyobb Sharpe."""
    a, b = train
    min_tr = cfg.i("backtest.min_trades")
    ratio = float(cfg.d("backtest.plateau_ratio"))
    score = {}
    for combo in grid_combos(cfg, name):
        r = grid_results[combo_key(combo)]
        st = r.stats(name, a, b)
        score[combo_key(combo)] = (st.sharpe, st.trades)
    best = None
    cands = 0
    for combo in grid_combos(cfg, name):
        sh, n = score[combo_key(combo)]
        if n < min_tr or sh <= 0:
            continue
        nb = [score[combo_key(x)][0] for x in neighbors(cfg, name, combo)]
        nb_mean = sum(nb) / len(nb) if nb else 0.0
        if nb_mean < ratio * sh:
            continue
        cands += 1
        if best is None or sh > best[1]:
            best = (combo, sh, n, nb_mean)
    if best is None:
        return None, None, None, None, 0
    return best[0], best[1], best[2], best[3], cands
