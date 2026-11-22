"""Állapot: portfóliók, trade-napló, jelzések, tőkegörbe, futásnapló, outbox.

Fájlok (state/ mappa):
  portfolios.json  – portfóliók és meta (kurzor, futás-azonosítók, számlálók)
  trades.csv       – trade-napló (az igazság forrása: a tőkét mindig ebből számoljuk újra)
  equity.csv       – tőke futásonként
  signals.csv      – kiértékelt jelzések
  runs.csv         – futásnapló (adat-ellenőrzések eredménye)
  outbox.json      – kiküldendő üzenetek
"""
from __future__ import annotations

import copy
import csv
import io
import json
import os
from dataclasses import dataclass, field, asdict
from decimal import Decimal
from pathlib import Path

from .config import Config
from .num import D, ZERO, s

SCHEMA_VERSION = 1


class InvariantError(RuntimeError):
    """Könyvelési invariáns sérült: a futásnak hibával kell leállnia."""


class DuplicateTradeError(InvariantError):
    pass


@dataclass
class Position:
    id: str
    entry_time: int
    active_from: int                  # ettől a perctől figyeljük a stopot/célt (a belépés utáni első teljes perc)
    entry_price: Decimal
    initial_qty: Decimal
    qty: Decimal
    initial_stop: Decimal
    stops: list                       # [[effective_from, stop_price, "initial"|"trailing"], ...] – csak szűkülhet
    target: Decimal | None            # részleges zárás célára (None, ha már teljesült / nincs)
    r_value: Decimal                  # 1R = belépő − kezdő stop
    cost_total: Decimal               # vételi érték + díj
    signal_bar_close: int
    last_trail_bar: int               # az utolsó 4H gyertya kezdete, amit a trailinghez figyelembe vettünk
    highest_close: Decimal | None = None
    trailing_active: bool = False
    realized_net: Decimal = ZERO      # eladásokból befolyt nettó összeg eddig
    fees_total: Decimal = ZERO

    def stop_at(self, t: int) -> tuple[Decimal, str]:
        cur = None
        for eff, price, kind in self.stops:
            if eff <= t:
                cur = (price, kind)
        if cur is None:
            raise InvariantError(f"{self.id}: nincs érvényes stop {t}-kor")
        return cur

    @property
    def current_stop(self) -> Decimal:
        return self.stops[-1][1]


@dataclass
class PortfolioState:
    name: str
    kind: str
    cash: Decimal
    btc: Decimal = ZERO
    peak_equity: Decimal = ZERO
    halted: bool = False
    halt_reason: str = ""
    halt_time: int = 0
    position: Position | None = None
    last_exit_time: int = 0
    last_signal_bar: int = 0          # az utoljára kiértékelt jelzés-gyertya vége
    bh_done: bool = False
    dca_done: int = 0
    trade_seq: int = 0


@dataclass
class Meta:
    schema_version: int
    config_hash: str
    created: int
    start_time: int
    m1_cursor: int                    # a következő feldolgozandó 1 perces gyertya kezdete
    last_run_time: float = 0.0
    last_run_id: str = ""
    recent_run_ids: list = field(default_factory=list)
    consecutive_failures: int = 0
    failure_alert_sent: bool = False
    counters: dict = field(default_factory=dict)


TRADE_FIELDS = ["trade_id", "run_id", "time", "time_iso", "portfolio", "side", "reason", "qty_btc", "price",
                "notional_usd", "fee_usd", "cash_after", "btc_after", "position_id", "pnl_usd", "config_hash",
                "details"]
TRADE_DECIMALS = {"qty_btc", "price", "notional_usd", "fee_usd", "cash_after", "btc_after", "pnl_usd"}
SIGNAL_FIELDS = ["time", "time_iso", "run_id", "portfolio", "timeframe", "bar_close", "bar_close_iso", "entry",
                 "exit", "action", "reason", "values", "config_hash"]
EQUITY_FIELDS = ["time", "time_iso", "run_id", "portfolio", "cash", "btc", "price", "equity", "peak",
                 "drawdown", "position_open", "halted"]
RUN_FIELDS = ["run_id", "time", "time_iso", "data_ok", "issues", "notes", "m1_processed", "m1_gaps_accepted",
              "cb_last", "kraken_last", "crosscheck_diff", "ticker_age_s", "config_hash"]


@dataclass
class State:
    meta: Meta
    portfolios: dict
    trades: list = field(default_factory=list)
    signals: list = field(default_factory=list)
    equity: list = field(default_factory=list)
    runs: list = field(default_factory=list)
    outbox: list = field(default_factory=list)

    # --- tranzakció: hiba esetén visszaállítjuk a futás előtti állapotot ---
    def checkpoint(self):
        return (copy.deepcopy(self.meta), copy.deepcopy(self.portfolios), len(self.trades), len(self.signals),
                len(self.equity), len(self.runs), copy.deepcopy(self.outbox))

    def rollback(self, cp):
        meta, ports, nt, ns, ne, nr, outbox = cp
        self.meta = meta
        self.portfolios = ports
        del self.trades[nt:]
        del self.signals[ns:]
        del self.equity[ne:]
        del self.runs[nr:]
        self.outbox = outbox


def new_state(cfg: Config, start_time: int) -> State:
    cap = cfg.d("portfolios.initial_capital_usd")
    ports = {}
    for n in cfg.names:
        t = cfg.strategy(n)["type"]
        kind = "buy_and_hold" if t == "buy_and_hold" else "weekly_dca" if t == "weekly_dca" else "strategy"
        ports[n] = PortfolioState(name=n, kind=kind, cash=cap, peak_equity=cap)
    meta = Meta(schema_version=SCHEMA_VERSION, config_hash=cfg.hash, created=int(start_time),
                start_time=int(start_time), m1_cursor=(int(start_time) // 60) * 60)
    return State(meta=meta, portfolios=ports)


# ---------------------------------------------------------------- szerializálás

def _enc(o):
    if isinstance(o, Decimal):
        return {"__d": s(o)}
    raise TypeError(type(o))


def _dec_hook(d):
    if set(d) == {"__d"}:
        return Decimal(d["__d"])
    return d


def portfolios_to_json(state: State) -> str:
    data = {"meta": asdict(state.meta), "portfolios": {}}
    for n, p in state.portfolios.items():
        pd = asdict(p)
        data["portfolios"][n] = pd
    return json.dumps(data, default=_enc, indent=1, sort_keys=True, ensure_ascii=False)


def portfolios_from_json(text: str) -> tuple[Meta, dict]:
    data = json.loads(text, object_hook=_dec_hook)
    meta = Meta(**data["meta"])
    if meta.schema_version != SCHEMA_VERSION:
        raise InvariantError(f"Ismeretlen állapot-séma: {meta.schema_version}")
    ports = {}
    for n, pd in data["portfolios"].items():
        pos = pd.pop("position")
        p = PortfolioState(**pd)
        if pos is not None:
            p.position = Position(**pos)
        ports[n] = p
    return meta, ports


def _csv_text(rows: list, fields: list) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: (s(v) if isinstance(v, Decimal) else ("" if v is None else v)) for k, v in r.items()})
    return buf.getvalue()


def _read_csv(path: Path, decimals: set | None = None) -> list:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if decimals:
        for r in rows:
            for k in decimals:
                if k in r and r[k] != "":
                    r[k] = Decimal(r[k])
                elif k in r:
                    r[k] = None
    return rows


def _atomic_write(path: Path, text: str):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="")
    os.replace(tmp, path)


def save_state(state: State, folder: str | Path):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    _atomic_write(folder / "portfolios.json", portfolios_to_json(state))
    _atomic_write(folder / "trades.csv", _csv_text(state.trades, TRADE_FIELDS))
    _atomic_write(folder / "signals.csv", _csv_text(state.signals, SIGNAL_FIELDS))
    _atomic_write(folder / "equity.csv", _csv_text(state.equity, EQUITY_FIELDS))
    _atomic_write(folder / "runs.csv", _csv_text(state.runs, RUN_FIELDS))
    _atomic_write(folder / "outbox.json", json.dumps(state.outbox, default=_enc, indent=1, ensure_ascii=False))


def load_state(folder: str | Path) -> State:
    folder = Path(folder)
    meta, ports = portfolios_from_json((folder / "portfolios.json").read_text(encoding="utf-8"))
    trades = _read_csv(folder / "trades.csv", TRADE_DECIMALS)
    for t in trades:
        t["time"] = int(t["time"])
    signals = _read_csv(folder / "signals.csv")
    equity = _read_csv(folder / "equity.csv", {"cash", "btc", "price", "equity", "peak", "drawdown"})
    runs = _read_csv(folder / "runs.csv")
    outbox_path = folder / "outbox.json"
    outbox = json.loads(outbox_path.read_text(encoding="utf-8"), object_hook=_dec_hook) if outbox_path.exists() else []
    return State(meta=meta, portfolios=ports, trades=trades, signals=signals, equity=equity, runs=runs,
                 outbox=outbox)


# ---------------------------------------------------------------- könyvelés-ellenőrzés

def rebuild_balances(trades: list, names: list, initial: Decimal) -> dict:
    """A trade-naplóból újraszámolja a készpénzt és a BTC-t; minden sor után egyeztet."""
    bal = {n: [initial, ZERO] for n in names}
    seen = set()
    for t in trades:
        tid = t["trade_id"]
        if tid in seen:
            raise DuplicateTradeError(f"Dupla trade azonosító a naplóban: {tid}")
        seen.add(tid)
        n = t["portfolio"]
        if n not in bal:
            raise InvariantError(f"Ismeretlen portfólió a naplóban: {n}")
        cash, btc = bal[n]
        qty, notional, fee = D(t["qty_btc"]), D(t["notional_usd"]), D(t["fee_usd"])
        if qty <= 0 or notional <= 0 or fee < 0:
            raise InvariantError(f"{tid}: nem pozitív mennyiség/érték")
        if t["side"] == "BUY":
            cash = cash - notional - fee
            btc = btc + qty
        elif t["side"] == "SELL":
            cash = cash + notional - fee
            btc = btc - qty
        else:
            raise InvariantError(f"{tid}: ismeretlen oldal {t['side']}")
        if cash < 0 or btc < 0:
            raise InvariantError(f"{tid}: negatív egyenleg (cash={cash}, btc={btc})")
        if cash != D(t["cash_after"]) or btc != D(t["btc_after"]):
            raise InvariantError(f"{tid}: a sor egyenlege nem egyezik az újraszámolttal "
                                 f"({t['cash_after']}/{t['btc_after']} vs {cash}/{btc})")
        bal[n] = [cash, btc]
    return {n: (v[0], v[1]) for n, v in bal.items()}


def check_invariants(state: State, cfg: Config):
    bal = rebuild_balances(state.trades, cfg.names, cfg.d("portfolios.initial_capital_usd"))
    for n, p in state.portfolios.items():
        cash, btc = bal[n]
        if p.cash < 0 or p.btc < 0:
            raise InvariantError(f"{n}: negatív egyenleg (cash={p.cash}, btc={p.btc})")
        if p.cash != cash or p.btc != btc:
            raise InvariantError(f"{n}: a könyvelés nem egyezik: állapot {p.cash}/{p.btc}, napló {cash}/{btc}")
        if p.kind == "strategy":
            if p.position is None and p.btc != 0:
                raise InvariantError(f"{n}: nincs nyitott pozíció, mégis van BTC ({p.btc})")
            if p.position is not None and p.position.qty != p.btc:
                raise InvariantError(f"{n}: a pozíció mennyisége ({p.position.qty}) != BTC egyenleg ({p.btc})")
            if p.position is not None:
                prices = [x[1] for x in p.position.stops]
                if any(b < a for a, b in zip(prices, prices[1:])):
                    raise InvariantError(f"{n}: a stop tágult")
        else:
            if p.position is not None:
                raise InvariantError(f"{n}: mérce-portfóliónak nem lehet stratégiai pozíciója")
