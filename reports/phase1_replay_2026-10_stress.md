# Fázis 1 – 1 hónap visszajátszás (valódi Coinbase adat) – STRESSZ-PRÓBA

> Laza, csak tesztre szánt paraméterekkel (sok trade a mechanika ellenőrzéséhez). Ez NEM a valódi stratégia és nem értékelés.

- Időszak: 2026-10-01T00:00:00Z – 2026-11-01T00:00:00Z (UTC)
- Config verzió: `e4fb063712b3`  ·  véletlen mag: 2026
- Adat: Coinbase BTC-USD 1m/1h/1d, letöltve a nyilvános API-ról. Az 1 perces adatban 3 perc hiányzik a Coinbase-nél is (nem volt kötés) → elfogadott hiány.

## Ellenőrzések

| Ellenőrzés | Eredmény |
|---|---|
| Futás végig, invariáns-hiba nélkül | ✅ (4871 futás, 48 s) |
| Determinizmus (2 futás azonos) | ✅ `a3306a7c2cefe586` / `a3306a7c2cefe586` |
| Mentés+visszatöltés minden 13. futás után = memóriában futtatva | ✅ `a3306a7c2cefe586` (374 mentés) |
| Dupla futás elutasítva | ✅ 90/90 |
| Elbukott mentés után folytatás a mentett állapotból | ✅ 105 eset |
| Független audit (árak, első érintés, díjak, kockázat, jelzések pandas-szal) | ✅ 0 hiba |

## Szimulált GitHub-körülmények

- Tervezett futás (5 percenként): 8928; lefutott: 4871
- Kimaradt futás: 263; késett futás (10–45 perc, ill. 1–1,5 óra): 941; átfedés miatt összevont: 3794
- Szándékos adat-hibák: {'stale': 23, 'duplicate': 13, 'crosscheck': 45, 'fetch_error': 14} → döntés nélküli futás: 102
- Adat-hiba miatti döntés nélküli futások (motor számlálója): 102 (kereszt-ellenőrzés: 45, régi adat: 30, hiány/duplikátum: 21, letöltési hiba: 14)
- Késés miatt elmaradt belépés: 1; stop alatti ár miatt: 0
- Riasztások az outboxban: BUY: 29, SELL: 24, ALERT_DATA: 2, DATA_RECOVERED: 2

## Portfóliók a hónap végén (csak a mechanika ellenőrzése, NEM stratégia-értékelés)

| Portfólió | Tőke ($) | Hozam | Max drawdown | Trade-sorok |
|---|---|---|---|---|
| P1 | 189.35 | -5.33% | 5.41% | 6 |
| P2 | 198.72 | -0.64% | 3.00% | 8 |
| P3 | 164.14 | -17.93% | 18.88% | 33 |
| B1 | 185.03 | -7.48% | 12.10% | 1 |
| B2 | 197.43 | -1.29% | 1.74% | 5 |

## Minden trade

| Idő (Budapest) | Portfólió | Oldal | Ok | BTC | Ár | Érték $ | Díj $ | P&L $ |
|---|---|---|---|---|---|---|---|---|
| 2026-10-01 02:27 | B1 | BUY | buy_and_hold | 0.00238692 | 83455.93 | 199.20 | 0.7968 |  |
| 2026-10-01 02:27 | B2 | BUY | dca | 0.00009180 | 83455.93 | 7.66 | 0.0306 |  |
| 2026-10-01 18:13 | P2 | BUY | entry | 0.00236378 | 84272.92 | 199.20 | 0.7968 |  |
| 2026-10-02 06:20 | P2 | SELL | target_partial | 0.00118189 | 86347.29 | 102.05 | 0.4082 | 1.65 |
| 2026-10-02 19:25 | P2 | SELL | trailing | 0.00118189 | 84552.00 | 99.93 | 0.3997 | -0.47 |
| 2026-10-03 06:11 | P2 | BUY | entry | 0.00236599 | 84689.57 | 200.37 | 0.8015 |  |
| 2026-10-05 00:16 | P2 | SELL | target_partial | 0.00118299 | 86595.47 | 102.44 | 0.4098 | 1.44 |
| 2026-10-05 18:03 | P2 | SELL | trailing | 0.00118300 | 85114.38 | 100.69 | 0.4028 | -0.30 |
| 2026-10-06 14:00 | P2 | BUY | entry | 0.00233559 | 86279.31 | 201.51 | 0.8061 |  |
| 2026-10-06 19:20 | P2 | SELL | stop | 0.00233559 | 85423.42 | 199.51 | 0.7981 | -3.60 |
| 2026-10-07 06:01 | P3 | BUY | entry | 0.00236636 | 84181.04 | 199.20 | 0.7968 |  |
| 2026-10-07 15:09 | P3 | SELL | stop | 0.00236636 | 83254.28 | 197.01 | 0.7880 | -3.78 |
| 2026-10-07 22:00 | P3 | BUY | entry | 0.00234246 | 83433.74 | 195.44 | 0.7818 |  |
| 2026-10-08 02:01 | B2 | BUY | dca | 0.00009199 | 83282.16 | 7.66 | 0.0306 |  |
| 2026-10-08 05:21 | P3 | SELL | stop | 0.00234246 | 82553.84 | 193.38 | 0.7735 | -3.62 |
| 2026-10-08 10:00 | P3 | BUY | entry | 0.00231185 | 82980.14 | 191.84 | 0.7674 |  |
| 2026-10-08 14:50 | P3 | SELL | stop | 0.00231185 | 82093.43 | 189.79 | 0.7592 | -3.58 |
| 2026-10-08 22:12 | P3 | BUY | entry | 0.00230069 | 81834.53 | 188.28 | 0.7531 |  |
| 2026-10-10 14:00 | P3 | SELL | signal | 0.00230069 | 82759.29 | 190.40 | 0.7616 | 0.61 |
| 2026-10-12 02:01 | P1 | BUY | entry | 0.00237958 | 83713.48 | 199.20 | 0.7968 |  |
| 2026-10-12 14:21 | P1 | SELL | stop | 0.00237958 | 83044.89 | 197.61 | 0.7904 | -3.18 |
| 2026-10-13 02:18 | P3 | BUY | entry | 0.00231999 | 81416.83 | 188.89 | 0.7555 |  |
| 2026-10-13 02:51 | P3 | SELL | stop | 0.00231999 | 80998.52 | 187.92 | 0.7517 | -2.48 |
| 2026-10-14 18:19 | P3 | BUY | entry | 0.00228500 | 81583.54 | 186.42 | 0.7457 |  |
| 2026-10-15 02:00 | B2 | BUY | dca | 0.00009388 | 81607.06 | 7.66 | 0.0306 |  |
| 2026-10-15 04:24 | P3 | SELL | stop | 0.00228500 | 80584.41 | 184.14 | 0.7365 | -3.77 |
| 2026-10-15 10:18 | P3 | BUY | entry | 0.00225000 | 81185.93 | 182.67 | 0.7307 |  |
| 2026-10-15 14:31 | P3 | SELL | stop | 0.00225000 | 80437.70 | 180.98 | 0.7239 | -3.14 |
| 2026-10-16 18:06 | P3 | BUY | entry | 0.00220951 | 81258.82 | 179.54 | 0.7182 |  |
| 2026-10-18 06:40 | P3 | SELL | signal | 0.00220951 | 81689.14 | 180.49 | 0.7220 | -0.49 |
| 2026-10-18 18:00 | P3 | BUY | entry | 0.00220750 | 81112.22 | 179.06 | 0.7162 |  |
| 2026-10-19 02:22 | P3 | SELL | signal | 0.00220750 | 81988.36 | 180.99 | 0.7240 | 0.49 |
| 2026-10-22 02:24 | P1 | BUY | entry | 0.00232868 | 84183.92 | 196.04 | 0.7841 |  |
| 2026-10-22 02:24 | B2 | BUY | dca | 0.00009101 | 84183.92 | 7.66 | 0.0306 |  |
| 2026-10-22 04:13 | P1 | SELL | stop | 0.00232868 | 83152.73 | 193.64 | 0.7745 | -3.96 |
| 2026-10-22 14:09 | P3 | BUY | entry | 0.00219576 | 81770.07 | 179.55 | 0.7182 |  |
| 2026-10-24 00:48 | P3 | SELL | stop | 0.00219576 | 80740.53 | 177.29 | 0.7091 | -3.69 |
| 2026-10-24 06:27 | P3 | BUY | entry | 0.00217686 | 80792.55 | 175.87 | 0.7035 |  |
| 2026-10-24 16:16 | P3 | SELL | stop | 0.00217686 | 80036.71 | 174.23 | 0.6969 | -3.05 |
| 2026-10-24 22:05 | P3 | BUY | entry | 0.00214655 | 80520.09 | 172.84 | 0.6914 |  |
| 2026-10-26 02:39 | P3 | SELL | stop | 0.00214655 | 79521.73 | 170.70 | 0.6828 | -3.52 |
| 2026-10-26 21:00 | P3 | BUY | entry | 0.00211888 | 79918.06 | 169.34 | 0.6773 |  |
| 2026-10-27 17:20 | P3 | SELL | signal | 0.00211888 | 80419.87 | 170.40 | 0.6816 | -0.30 |
| 2026-10-29 01:00 | P1 | BUY | entry | 0.00236306 | 81289.94 | 192.09 | 0.7684 |  |
| 2026-10-29 01:00 | B2 | BUY | dca | 0.00009425 | 81289.94 | 7.66 | 0.0306 |  |
| 2026-10-29 02:39 | P1 | SELL | stop | 0.00236306 | 80450.06 | 190.11 | 0.7604 | -3.51 |
| 2026-10-29 05:57 | P3 | BUY | entry | 0.00202774 | 80168.07 | 162.56 | 0.6502 |  |
| 2026-10-29 17:30 | P3 | SELL | signal | 0.00202774 | 81305.61 | 164.87 | 0.6595 | 1.00 |
| 2026-10-30 01:12 | P3 | BUY | entry | 0.00218876 | 77685.82 | 170.04 | 0.6801 |  |
| 2026-10-30 01:23 | P3 | SELL | stop | 0.00218876 | 76662.89 | 167.80 | 0.6712 | -3.59 |
| 2026-10-30 09:19 | P3 | BUY | entry | 0.00213360 | 78017.98 | 166.46 | 0.6658 |  |
| 2026-10-30 14:32 | P3 | SELL | stop | 0.00213360 | 76864.55 | 164.00 | 0.6560 | -3.78 |
| 2026-10-30 21:31 | P3 | BUY | entry | 0.00196014 | 76805.87 | 150.55 | 0.6022 |  |

Megjegyzés: egy hónap és ennyi trade semmit nem mond a stratégiák jóságáról; ez csak a motor és a könyvelés helyességének próbája. A stratégiák értékelése a Fázis 2 (4+ év adat).
