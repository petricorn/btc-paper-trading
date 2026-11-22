# Útmutató Claude-nak (és minden új fejlesztőnek) – itt tartunk

Ezt a fájlt a Claude Code automatikusan elolvassa, amikor ebben a mappában dolgozik. Ez a projekt teljes
emlékezete: a döntések, az állapot és a következő lépések. **Minden lezárt lépés után frissítsd.**

## A felhasználóról és a munkamódról
- A tulajdonos nem programozó: **magyarul**, egyszerűen magyarázz, és pontos, bemásolható parancsokat adj.
- Az eredeti specifikáció: [SPEC.md](SPEC.md). Ez a szerződés; minden fázis elején terv, a végén az
  átadási feltételek bemutatása és jóváhagyás. Ha valami nem egyértelmű: kérdezz.
- „Ne legyen hiba”: mindent tesztekkel és valódi futásokkal ellenőrizz, és őszintén jelents (ha valami nem
  működik vagy nincs ellenőrizve, mondd ki).
- Ez **szimuláció**. Soha ne adj le valódi megbízást, ne használj tőzsdei API kulcsot, és ne adj személyre
  szabott befektetési tanácsot.

## Állapot (2026-11-22)
| Fázis | Állapot |
|---|---|
| 1 – adatréteg, diagnostics, motor, könyvelés | **KÉSZ, jóváhagyva.** Diagnostics és tesztek zöldek a GitHub futtatón; 2026. októberi visszajátszás hibátlan (`reports/phase1_replay_2026-10.md`). |
| 2 – backteszt, stratégiaválasztás | **Kód kész, a mintán belüli számolás lefutott / fut** (`python scripts/phase2.py insample`), riport: `reports/phase2_backtest.md`. A **tartalék (holdout) még NEM futott** – lásd lent. Jóváhagyásra vár. |
| 3 – éles paper futás (Telegram, napi riport, outbox, heartbeat) | Még nincs elkezdve. |
| 4 – tanulás | Csak 3 hónap éles futás után. |
| Extra: webes felület | Kész: `docs/`, nyilvános: https://petricorn.github.io/btc-paper-trading/ (GitHub Pages, main/docs). Élő adat híján DEMÓ-t mutat. |

## Elfogadott döntések
**Fázis 1:**
1. Publikus repó (így ingyenes az 5 perces cron); `petricorn/btc-paper-trading`.
2. Helyi mappa Google Drive-on kívül: `C:\Projects\btc-paper-trading` (a Drive elrontja a gitet és a venv-et).
3. A 4H gyertyát a lezárt Coinbase 1h gyertyákból rakjuk össze (UTC 00/04/08/12/16/20); a Coinbase nem ad 4h-t.
4. B2 heti DCA: 200/26 = 7,69 $ részlet; a 10 $ minimum ügyletméret csak P1–P3-ra vonatkozik.
5. Részleges zárás 2R-nél 50%; trailing +1R felett, szint = legmagasabb lezárt 4H záró − 2×ATR14, csak szűkül.
   Kill switch: piaci értéken számolt tőke a saját csúcs alatt 20% → zár és leáll (csak P1–P3).
6. Spec-értelmezés: 1H/1D hiány 48 órán belül → nincs döntés; régebbi (lezárt) Coinbase-hiány naplózva és
   elfogadva (különben egy régi kiesés 100 napig blokkolna). 1 perces hiány 30 perc után „kötés nélküli perc”.

**Fázis 2:**
1. Adat 2018-01-01-től (1h/1d bemelegítés 2017-03-tól); tartalék: 2026-05-22 → 2026-11-22, **egyszer**.
2. Backteszt-futásrend: minden 4H zárás + 2 perc, adat-hiba után 5 percenként újrapróbál; robusztussági próba
   véletlen 0–55 perc késéssel.
3. Csak a stratégia-paramétereket hangoljuk (3/stratégia, rács a `config.yaml` `backtest.grid` részében);
   kockázat és díj fix.
4. Kiválasztás: tanító Sharpe, ≥ 6 kötés, Sharpe > 0, fennsík-szabály (rácsszomszédok átlag Sharpe ≥ 0,8×);
   ha nincs ilyen, a stratégia abban a teszt-ablakban készpénzben marad. Walk-forward 24 hó tanítás / 6 hó teszt.
5. A számolás a tulajdonos gépén fut; tartalékként a `phase2-backtest` GitHub workflow.

**Egyéb:** a hangoló rácsfutásokban a kill switch ki van kapcsolva (`risk.kill_switch_enabled`), a
kiértékelő futásokban be. Self-hosted runner (barát gépe) elvetve: nyilvános repónál biztonsági kockázat.

## Felépítés röviden
- `btcpaper/engine.py` – az EGYETLEN motor (élő és visszajátszás is ezt használja).
- `btcpaper/snapshot.py` – adat-ellenőrzés (hiány, duplikátum, frissesség, Coinbase–Kraken összevetés).
- `btcpaper/state.py` – állapot + könyvelés-újraszámolás (Decimal), invariánsok, tranzakciós visszagörgetés.
- `btcpaper/replay.py` – visszajátszás (késések, dupla futás, elbukott mentés szimulálva).
- `btcpaper/audit.py` – független utólagos ellenőrzés pandas-szal (árak, első érintés, díj, kockázat, jelzések).
- `btcpaper/backtest.py`, `metrics.py`, `scripts/phase2.py` – Fázis 2.
- `btcpaper/dashboard.py` + `docs/` – webes felület (egyetlen `dashboard.json`-t olvas).
- `btcpaper/live.py` – egy élő futás helyben (Fázis 3-ban ebből lesz a GitHub cron).

## Gépbeállítás (új gépen)
```powershell
git clone https://github.com/petricorn/btc-paper-trading.git C:\Projects\btc-paper-trading
cd C:\Projects\btc-paper-trading
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest
```
- A nagy adat (`data/`, `results/`) **nincs a gitben**. Újra letölthető (~1 óra):
  `.\.venv\Scripts\python.exe scripts\download_full.py --start 2018-01-01 --warmup-start 2017-03-01 --end 2026-11-22`
  és `scripts\download_history.py` (lásd README), vagy a tulajdonos ZIP-ben átadja.
- GitHub CLI-hez `workflow` jogosultság kell a workflow-fájlok feltöltéséhez:
  `gh auth refresh -h github.com -s workflow`.
- Windows-on a sima `python` parancs a Store-alias; mindig a `.venv\Scripts\python.exe`-t használd.

## Szigorú szabályok a folytatáshoz
- **A tartalékot (holdout) csak egyszer szabad kiértékelni**: `python scripts/phase2.py holdout`. A program
  `reports/phase2_holdout_DONE.txt` zárfájlt ír, és utána nem engedi újra. A tulajdonos jóváhagyása előtt ne futtasd.
- Ne adj hozzá külön backteszt-logikát; minden a `run_replay → Engine` láncon menjen.
- Adatot soha ne találj ki; hiányos adatnál nincs döntés.
- Minden új funkcióhoz teszt; a `pytest` legyen zöld commit előtt.

## Következő lépések
1. A Fázis 2 riport (`reports/phase2_backtest.md`) bemutatása a tulajdonosnak, őszinte ítélettel; jóváhagyás után
   a tartalék egyszeri kiértékelése, majd Fázis 2 lezárása.
2. Fázis 3 terve (magyarul), kérdések: Telegram bot és chat ID, healthchecks.io, mikor induljon a 48 órás próbafutás.
   Fő workflow: `*/5` cron + workflow_dispatch, concurrency, timeout; állapot a `bot-state` ágon (force-push,
   egyetlen commit); outbox csak sikeres mentés után küld; heartbeat; napi riport 7:00 Budapest; a felület
   `state/dashboard.json`-t olvas a `bot-state` ágról (`scripts/export_dashboard.py` / `btcpaper.dashboard`).
