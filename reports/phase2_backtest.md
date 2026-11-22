# Fázis 2 – Backteszt és stratégiaválasztás (mintán belül)

> Szimuláció valódi Coinbase BTC-USD adaton, díjakkal (0,4%/oldal) és csúszással (0,05%). Ugyanaz a motor, mint élőben. Ez nem befektetési tanács.

- Mintán belüli időszak: 2018-01-01 – 2026-05-22 · tartalék (még érintetlen): 2026-05-22 – 2026-11-22
- Walk-forward: 24 hó tanítás → 6 hó teszt, 13 teszt-ablak (2020-01-01 – 2026-05-22)
- Kiválasztás: tanító Sharpe, legalább 6 kötés, Sharpe > 0, és a rácsbeli szomszédok átlag Sharpe-ja ≥ 0.8 × a választotté. Ha nincs ilyen, a stratégia abban a teszt-ablakban készpénzben marad.
- Független audit az alapparaméteres teljes futáson: 0 hiba ✅

## A) Alapparaméterek (a specifikáció szerinti), teljes mintán belüli időszak

| Portfólió | Hozam | CAGR | Max DD | Sharpe | Win rate | Profit factor | Trade-ek |
|---|---|---|---|---|---|---|---|
| P1 | +6.8% | +0.8% | 13.1% | 0.14 | 42% | 1.09 | 77 |
| P2 | -20.4% | -2.7% | 21.1% | -0.81 | 30% | 0.29 | 30 |
| P3 | -20.7% | -2.7% | 20.7% | -1.07 | 25% | 0.12 | 24 |
| B1 | +481.6% | +23.5% | 81.7% | 0.65 | 0% | 0.00 | 0 |
| B2 | +779.4% | +29.7% | 77.1% | 0.73 | 0% | 0.00 | 0 |

## B) Walk-forward, csak mintán kívüli (teszt) ablakok összefűzve

| Portfólió | Hozam | CAGR | Max DD | Sharpe | Win rate | Profit factor | Trade-ek |
|---|---|---|---|---|---|---|---|
| P1 (WF) | -8.4% | -1.4% | 16.1% | -0.13 | 37% | 0.91 | 68 |
| P2 (WF) | -1.5% | -0.2% | 7.1% | -0.06 | 25% | 0.87 | 12 |
| P3 (WF) | +0.0% | +0.0% | 0.0% | 0.00 | 0% | 0.00 | 0 |
| B1 | +976.8% | +45.2% | 77.1% | 0.92 | 0% | 0.00 | 0 |
| B2 | +838.3% | +42.1% | 77.1% | 0.90 | 0% | 0.00 | 0 |

## Ítélet (kockázattal korrigálva, díjak után)

- **P1** alapparaméterrel: kisebb a visszaesése, de a Sharpe-ja NEM jobb mindkét mércénél → nem jobb kockázattal korrigálva; walk-forward: kisebb a visszaesése, de a Sharpe-ja NEM jobb mindkét mércénél → nem jobb kockázattal korrigálva.
- **P2** alapparaméterrel: kisebb a visszaesése, de a Sharpe-ja NEM jobb mindkét mércénél → nem jobb kockázattal korrigálva; walk-forward: kisebb a visszaesése, de a Sharpe-ja NEM jobb mindkét mércénél → nem jobb kockázattal korrigálva.
- **P3** alapparaméterrel: kisebb a visszaesése, de a Sharpe-ja NEM jobb mindkét mércénél → nem jobb kockázattal korrigálva; walk-forward: kisebb a visszaesése, de a Sharpe-ja NEM jobb mindkét mércénél → nem jobb kockázattal korrigálva.

## Walk-forward paraméter-választások

| Teszt-ablak | P1 | P2 | P3 |
|---|---|---|---|
| 2020-01-01 – 2020-07-01 | 10, 10, 200 (Sh 0.61, 15 kötés) | készpénz (nincs alkalmas) | készpénz (nincs alkalmas) |
| 2020-07-01 – 2021-01-01 | 10, 5, 100 (Sh 0.03, 27 kötés) | készpénz (nincs alkalmas) | készpénz (nincs alkalmas) |
| 2021-01-01 – 2021-07-01 | 20, 5, 150 (Sh 0.59, 28 kötés) | készpénz (nincs alkalmas) | készpénz (nincs alkalmas) |
| 2021-07-01 – 2022-01-01 | 10, 5, 150 (Sh 0.22, 35 kötés) | készpénz (nincs alkalmas) | készpénz (nincs alkalmas) |
| 2022-01-01 – 2022-07-01 | készpénz (nincs alkalmas) | készpénz (nincs alkalmas) | készpénz (nincs alkalmas) |
| 2022-07-01 – 2023-01-01 | 10, 10, 100 (Sh 0.33, 35 kötés) | készpénz (nincs alkalmas) | készpénz (nincs alkalmas) |
| 2023-01-01 – 2023-07-01 | készpénz (nincs alkalmas) | készpénz (nincs alkalmas) | készpénz (nincs alkalmas) |
| 2023-07-01 – 2024-01-01 | 10, 10, 100 (Sh 0.44, 20 kötés) | készpénz (nincs alkalmas) | készpénz (nincs alkalmas) |
| 2024-01-01 – 2024-07-01 | 10, 5, 100 (Sh 1.39, 15 kötés) | készpénz (nincs alkalmas) | készpénz (nincs alkalmas) |
| 2024-07-01 – 2025-01-01 | 20, 5, 150 (Sh 0.95, 20 kötés) | készpénz (nincs alkalmas) | készpénz (nincs alkalmas) |
| 2025-01-01 – 2025-07-01 | 20, 5, 100 (Sh 1.27, 27 kötés) | 200, 45, 5 (Sh 0.14, 40 kötés) | készpénz (nincs alkalmas) |
| 2025-07-01 – 2026-01-01 | készpénz (nincs alkalmas) | 200, 40, 5 (Sh 0.97, 21 kötés) | készpénz (nincs alkalmas) |
| 2026-01-01 – 2026-05-22 | készpénz (nincs alkalmas) | 200, 35, 5 (Sh 0.88, 8 kötés) | készpénz (nincs alkalmas) |

## Monte Carlo (a kötések sorrendjének keverése, 10 000×) – max drawdown eloszlás

| Stratégia | Kötések | Tényleges sorrend | Medián | 95% eset ennél jobb | Legrosszabb |
|---|---|---|---|---|---|
| P1 alap | 77 | 11.6% | 16.6% | 24.6% | 35.2% |
| P1 WF | 68 | 14.2% | 21.2% | 29.5% | 39.8% |
| P2 alap | 30 | 20.4% | 21.0% | 24.1% | 27.2% |
| P2 WF | 12 | 6.2% | 7.1% | 9.6% | 10.9% |
| P3 alap | 24 | 20.7% | 20.9% | 21.8% | 23.2% |
| P3 WF | 0 | – | – | – | – |

## Robusztusság: véletlen 0–55 perces futási késés (alapparaméterek)

| Portfólió | Hozam | CAGR | Max DD | Sharpe | Win rate | Profit factor | Trade-ek |
|---|---|---|---|---|---|---|---|
| P1 fix 2 perc | +6.8% | +0.8% | 13.1% | 0.14 | 42% | 1.09 | 77 |
| P1 0–55 perc | +4.8% | +0.6% | 15.8% | 0.11 | 44% | 1.06 | 77 |
| P2 fix 2 perc | -20.4% | -2.7% | 21.1% | -0.81 | 30% | 0.29 | 30 |
| P2 0–55 perc | -20.2% | -2.7% | 20.9% | -0.81 | 30% | 0.31 | 30 |
| P3 fix 2 perc | -20.7% | -2.7% | 20.7% | -1.07 | 25% | 0.12 | 24 |
| P3 0–55 perc | -20.3% | -2.7% | 20.3% | -1.07 | 25% | 0.11 | 24 |

## Paraméter-érzékenység: Sharpe a teljes mintán belüli időszakon (kill switch nélkül)

**P1** (legjobb 5 és legrosszabb 3):

| Paraméterek | Sharpe | Hozam | Max DD | Kötések |
|---|---|---|---|---|
| entry_lookback_days=20, exit_lookback_days=5, trend_sma_days=150 | 0.29 | +18.3% | 16.5% | 81 |
| entry_lookback_days=20, exit_lookback_days=10, trend_sma_days=150 | 0.29 | +18.3% | 16.5% | 81 |
| entry_lookback_days=20, exit_lookback_days=20, trend_sma_days=150 | 0.29 | +18.3% | 16.5% | 81 |
| entry_lookback_days=10, exit_lookback_days=5, trend_sma_days=150 | 0.26 | +17.6% | 16.9% | 105 |
| entry_lookback_days=10, exit_lookback_days=10, trend_sma_days=150 | 0.26 | +17.6% | 16.9% | 105 |
| entry_lookback_days=55, exit_lookback_days=5, trend_sma_days=100 | -0.40 | -20.0% | 23.2% | 69 |
| entry_lookback_days=55, exit_lookback_days=10, trend_sma_days=100 | -0.40 | -20.0% | 23.2% | 69 |
| entry_lookback_days=55, exit_lookback_days=20, trend_sma_days=100 | -0.40 | -20.0% | 23.2% | 69 |

**P2** (legjobb 5 és legrosszabb 3):

| Paraméterek | Sharpe | Hozam | Max DD | Kötések |
|---|---|---|---|---|
| trend_ema=200, rsi_pullback=35, pullback_window=5 | 0.28 | +8.8% | 11.3% | 29 |
| trend_ema=200, rsi_pullback=40, pullback_window=5 | 0.03 | +0.1% | 13.8% | 76 |
| trend_ema=50, rsi_pullback=30, pullback_window=2 | 0.00 | +0.0% | 0.0% | 0 |
| trend_ema=100, rsi_pullback=30, pullback_window=2 | 0.00 | +0.0% | 0.0% | 0 |
| trend_ema=200, rsi_pullback=30, pullback_window=5 | -0.13 | -1.6% | 6.2% | 7 |
| trend_ema=50, rsi_pullback=45, pullback_window=2 | -0.81 | -31.6% | 31.8% | 88 |
| trend_ema=50, rsi_pullback=45, pullback_window=3 | -0.86 | -36.9% | 37.6% | 114 |
| trend_ema=50, rsi_pullback=45, pullback_window=5 | -1.21 | -52.4% | 52.5% | 150 |

**P3** (legjobb 5 és legrosszabb 3):

| Paraméterek | Sharpe | Hozam | Max DD | Kötések |
|---|---|---|---|---|
| bb_period=30, bb_std=2.5, adx_max=15 | -0.35 | -5.6% | 9.0% | 12 |
| bb_period=30, bb_std=2.0, adx_max=15 | -0.45 | -10.1% | 15.2% | 31 |
| bb_period=20, bb_std=2.5, adx_max=15 | -0.45 | -8.7% | 10.8% | 25 |
| bb_period=20, bb_std=2.0, adx_max=15 | -0.54 | -14.0% | 18.3% | 49 |
| bb_period=30, bb_std=1.5, adx_max=15 | -0.82 | -20.9% | 23.5% | 51 |
| bb_period=20, bb_std=1.5, adx_max=20 | -1.92 | -68.7% | 69.3% | 208 |
| bb_period=20, bb_std=2.0, adx_max=25 | -2.02 | -76.1% | 76.7% | 252 |
| bb_period=20, bb_std=1.5, adx_max=25 | -2.27 | -83.5% | 84.2% | 345 |

## Adat és futás

- Alapfutás: 18378 szimulált futás, ebből 8668 újrapróbálás adat-hiba után; adat-hiba miatti döntés nélküli futás: 8843; elfogadott hiányzó 1 perces gyertya: 4473; késés miatt elmaradt belépés: 1.
- Ismert közelítések: múltbeli bid/ask nincs (a futás percének nyitóára + csúszás); a futás 4H zárás után 2 perccel történik (élőben 5 percenként, késésekkel – ld. robusztussági táblázat).

A tartalék (utolsó 6 hónap) kiértékelése külön lépés, egyszer: `python scripts/phase2.py holdout`.
