# Fázis 1 – 1 hónap visszajátszás (valódi Coinbase adat)

- Időszak: 2026-10-01T00:00:00Z – 2026-11-01T00:00:00Z (UTC)
- Config verzió: `7918ad748647`  ·  véletlen mag: 2026
- Adat: Coinbase BTC-USD 1m/1h/1d, letöltve a nyilvános API-ról. Az 1 perces adatban 3 perc hiányzik a Coinbase-nél is (nem volt kötés) → elfogadott hiány.

## Ellenőrzések

| Ellenőrzés | Eredmény |
|---|---|
| Futás végig, invariáns-hiba nélkül | ✅ (4871 futás, 47 s) |
| Determinizmus (2 futás azonos) | ✅ `3b8a3619d1c0fb45` / `3b8a3619d1c0fb45` |
| Mentés+visszatöltés minden 13. futás után = memóriában futtatva | ✅ `3b8a3619d1c0fb45` (374 mentés) |
| Dupla futás elutasítva | ✅ 90/90 |
| Elbukott mentés után folytatás a mentett állapotból | ✅ 105 eset |
| Független audit (árak, első érintés, díjak, kockázat, jelzések pandas-szal) | ✅ 0 hiba |

## Szimulált GitHub-körülmények

- Tervezett futás (5 percenként): 8928; lefutott: 4871
- Kimaradt futás: 263; késett futás (10–45 perc, ill. 1–1,5 óra): 941; átfedés miatt összevont: 3794
- Szándékos adat-hibák: {'stale': 23, 'duplicate': 13, 'crosscheck': 45, 'fetch_error': 14} → döntés nélküli futás: 102
- Adat-hiba miatti döntés nélküli futások (motor számlálója): 102 (kereszt-ellenőrzés: 45, régi adat: 30, hiány/duplikátum: 21, letöltési hiba: 14)
- Késés miatt elmaradt belépés: 0; stop alatti ár miatt: 0
- Riasztások az outboxban: BUY: 7, ALERT_DATA: 2, DATA_RECOVERED: 2, SELL: 1

## Portfóliók a hónap végén (csak a mechanika ellenőrzése, NEM stratégia-értékelés)

| Portfólió | Tőke ($) | Hozam | Max drawdown | Trade-sorok |
|---|---|---|---|---|
| P1 | 200.00 | +0.00% | 0.00% | 0 |
| P2 | 200.00 | +0.00% | 0.00% | 0 |
| P3 | 202.81 | +1.41% | 0.46% | 2 |
| B1 | 185.03 | -7.48% | 12.10% | 1 |
| B2 | 197.43 | -1.29% | 1.74% | 5 |

## Minden trade

| Idő (Budapest) | Portfólió | Oldal | Ok | BTC | Ár | Érték $ | Díj $ | P&L $ |
|---|---|---|---|---|---|---|---|---|
| 2026-10-01 02:27 | B1 | BUY | buy_and_hold | 0.00238692 | 83455.93 | 199.20 | 0.7968 |  |
| 2026-10-01 02:27 | B2 | BUY | dca | 0.00009180 | 83455.93 | 7.66 | 0.0306 |  |
| 2026-10-08 02:01 | B2 | BUY | dca | 0.00009199 | 83282.16 | 7.66 | 0.0306 |  |
| 2026-10-13 02:18 | P3 | BUY | entry | 0.00244670 | 81416.83 | 199.20 | 0.7968 |  |
| 2026-10-13 06:02 | P3 | SELL | signal | 0.00244670 | 83225.02 | 203.63 | 0.8145 | 2.81 |
| 2026-10-15 02:00 | B2 | BUY | dca | 0.00009388 | 81607.06 | 7.66 | 0.0306 |  |
| 2026-10-22 02:24 | B2 | BUY | dca | 0.00009101 | 84183.92 | 7.66 | 0.0306 |  |
| 2026-10-29 01:00 | B2 | BUY | dca | 0.00009425 | 81289.94 | 7.66 | 0.0306 |  |

Megjegyzés: egy hónap és ennyi trade semmit nem mond a stratégiák jóságáról; ez csak a motor és a könyvelés helyességének próbája. A stratégiák értékelése a Fázis 2 (4+ év adat).
