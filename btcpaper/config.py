"""config.yaml betöltése, ellenőrzése és verzió-hash számítása."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

from .num import D

STRATEGY_TYPES = {
    "donchian_breakout", "trend_pullback", "bollinger_reversion", "buy_and_hold", "weekly_dca",
}


class ConfigError(ValueError):
    pass


def config_hash(raw: dict) -> str:
    """A config tartalmának ujjlenyomata (12 hexa jegy). Formázás/kommentek nem számítanak."""
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class Config:
    raw: dict
    hash: str

    def get(self, path: str):
        node = self.raw
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                raise ConfigError(f"Hiányzó config kulcs: {path}")
            node = node[part]
        return node

    def d(self, path: str) -> Decimal:
        return D(self.get(path))

    def i(self, path: str) -> int:
        v = self.get(path)
        if isinstance(v, bool) or not isinstance(v, int):
            raise ConfigError(f"{path} egész szám kell legyen, kapott: {v!r}")
        return v

    def strategy(self, name: str) -> dict:
        return self.get(f"strategies.{name}")

    @property
    def names(self) -> list[str]:
        return list(self.get("portfolios.names"))


def _check_range(cfg: Config, path: str, lo, hi):
    v = cfg.d(path)
    if not (D(lo) <= v <= D(hi)):
        raise ConfigError(f"{path}={v} a megengedett [{lo}, {hi}] tartományon kívül")


def validate(cfg: Config) -> None:
    names = cfg.names
    if names != ["P1", "P2", "P3", "B1", "B2"]:
        raise ConfigError("A portfóliók: P1, P2, P3, B1, B2 (ebben a sorrendben)")
    for n in names:
        t = cfg.strategy(n).get("type")
        if t not in STRATEGY_TYPES:
            raise ConfigError(f"{n}: ismeretlen stratégia típus: {t}")
    _check_range(cfg, "portfolios.initial_capital_usd", 1, 1_000_000)
    _check_range(cfg, "costs.fee_rate", 0, "0.05")
    _check_range(cfg, "costs.slippage_rate", 0, "0.05")
    _check_range(cfg, "costs.min_trade_usd", 0, 1000)
    _check_range(cfg, "risk.risk_per_trade", "0.001", "0.05")
    _check_range(cfg, "risk.stop_atr_mult", "0.5", 10)
    _check_range(cfg, "risk.trail_activation_r", 0, 10)
    _check_range(cfg, "risk.trail_atr_mult", "0.5", 10)
    _check_range(cfg, "risk.partial_take_r", "0.5", 20)
    _check_range(cfg, "risk.partial_take_fraction", 0, 1)
    _check_range(cfg, "risk.kill_switch_drawdown", "0.01", "0.9")
    _check_range(cfg, "data.crosscheck_max_diff", "0.0001", "0.1")
    for p in ["risk.atr_period", "risk.cooldown_bars_4h", "risk.max_signal_age_seconds",
              "data.lookback_4h_bars", "data.lookback_1d_bars", "data.candle_close_grace_seconds",
              "data.max_data_age_seconds", "data.max_clock_skew_seconds", "data.m1_gap_settle_minutes",
              "data.decision_gap_block_hours", "data.max_m1_catchup_minutes", "data.alert_after_failed_runs",
              "indicators.ema_fast", "indicators.rsi_period", "indicators.adx_period",
              "http.timeout_seconds", "http.max_retries"]:
        if cfg.i(p) < 0:
            raise ConfigError(f"{p} nem lehet negatív")
    if cfg.i("risk.max_signal_age_seconds") > 3600:
        raise ConfigError("risk.max_signal_age_seconds legfeljebb 3600 (1 óra) lehet")
    if cfg.i("data.max_data_age_seconds") > 180:
        raise ConfigError("data.max_data_age_seconds legfeljebb 180 (3 perc) lehet")
    if cfg.i("strategies.B2.installments") < 1:
        raise ConfigError("B2 installments >= 1")


def load_config(path: str | Path = "config.yaml") -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("A config.yaml üres vagy hibás")
    return config_from_dict(raw)


def config_from_dict(raw: dict) -> Config:
    cfg = Config(raw=raw, hash=config_hash(raw))
    validate(cfg)
    return cfg
