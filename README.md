# Bitcoin PAPER TRADING (szimuláció)

> **Ez szimuláció.** Valódi pénz nincs. Tőzsdei számlát vagy API kulcsot nem használ, csak nyilvános
> piaci adatot (Coinbase, Kraken). Valódi megbízást soha nem ad le. Ez nem befektetési tanács.

A rendszer 5 független, képzeletbeli portfóliót futtat, mindegyik 200 USD-vel:

| Portfólió | Mi ez? |
|---|---|
| P1 | Trendkövető Donchian-kitörés (20 napos csúcs), napi trendszűrővel (záró > SMA200) |
| P2 | Trend + visszahúzódás (4H): emelkedő trendben RSI14-pullback, majd visszafordulás |
| P3 | Mean reversion Bollinger-szalaggal (4H), csak oldalazó piacon (ADX14 < 20) |
| B1 | Mérce: buy & hold (az indulás napján vesz, és tart) |
| B2 | Mérce: heti DCA (200 USD 26 egyenlő heti részletben) |

A cél: élő, előre nem ismert adatokon kiderüljön, hogy bármelyik stratégia jobb-e a két mércénél,
kockázattal korrigálva és díjak után. Ha nem jobb, a riport ezt egyenesen kimondja.

## Állapot: FÁZIS 1 (adatréteg, diagnostics, motor, könyvelés)

| Fázis | Tartalom | Állapot |
|---|---|---|
| 1 | Adatréteg, diagnostics, motor, könyvelés, tesztek, 1 hónap visszajátszás | elkészült, jóváhagyásra vár |
| 2 | Backteszt (4+ év), walk-forward, robusztusság, Monte Carlo, stratégiaválasztás | még nem |
| 3 | Éles paper futás GitHubon: Telegram, napi riport, outbox, heartbeat | még nem |
| 4 | Tanulás (legkorábban 3 hónap éles futás után, alapból kikapcsolva) | még nem |

## Hogyan működik (röviden)

* **Egyetlen motor** (`btcpaper/engine.py`): a visszajátszás és az éles futás ugyanazt a kódot
  használja. A különbség csak az adatforrás: az éles futás friss adatot kér le, a visszajátszás a letöltött
  múltbeli adatból pontosan azt adja oda, ami az adott pillanatban már ismert volt.
* **Csak lezárt gyertyából** számol jelzést (4H és 1D). A 4H gyertyát a Coinbase lezárt 1 órás
  gyertyáiból rakja össze (UTC 00, 04, 08, 12, 16, 20 órától), mert a Coinbase nem ad 4 órásat.
* **Belépés** a futás pillanatában lekért áron (Coinbase ask + 0,05% csúszás). Ha a jelzés óta több mint
  1 óra telt el, vagy az ár már a stop alatt van, a belépés elmarad, és ez naplózva van.
* **Stop és részleges cél** várakozó megbízásként viselkedik: minden futás végigmegy az utolsó
  ellenőrzés óta lezárult 1 perces gyertyákon. Ha egy percben a stop és a cél is teljesülne, a stop számít.
  Ha a gyertya a stop alatt nyitott, a nyitóáron teljesül.
* **Adatellenőrzés minden futásban:** hiányzó vagy duplikált gyertya, 3 percnél régebbi adat, vagy ha a
  Coinbase és a Kraken ára 0,5%-nál jobban eltér → abban a futásban nincs döntés. 3 egymást követő hibás
  futás → riasztás (az outboxba; a Telegram-küldés a Fázis 3-ban jön).
* **Könyvelés:** a tőkét mindig a trade-naplóból számolja újra. Ha a készpénz vagy a BTC negatív lenne,
  vagy a könyvelés nem egyezik, a futás hibával leáll, és semmit nem ment.
* Minden paraméter a `config.yaml`-ban van; a config ujjlenyomata (hash) minden trade és jelzés mellé
  mentődik. Minden idő UTC-ben tárolódik, a riportokban budapesti idő jelenik meg.

## Mappák

```
config.yaml              minden paraméter
btcpaper/                a program
  sources.py             Coinbase / Kraken / Fear & Greed lekérés (lapozás, újrapróbálás, timeout)
  snapshot.py            adat-ellenőrzés: hiány, duplikátum, frissesség, kereszt-ellenőrzés
  indicators.py          SMA, EMA, RSI, ATR, ADX, Bollinger
  strategies.py          P1, P2, P3 jelzései
  engine.py              az egyetlen motor
  state.py               állapot, trade-napló, könyvelés-ellenőrzés
  replay.py              múltbeli időszak visszajátszása
  audit.py               független utólagos ellenőrzés (pandas-szal)
  diagnostics.py         adatforrás-végpontok tesztje
tests/                   pytest tesztek
scripts/                 adatletöltés, 1 hónap visszajátszás
reports/                 riportok
```

## Helyi futtatás lépésről lépésre (Windows, PowerShell)

1. Python 3.12 kell. Ellenőrzés: `py -3.12 --version`
2. A projekt mappájában (pl. `C:\Projects\btc-paper-trading`):
   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
3. Tesztek: `.\.venv\Scripts\python.exe -m pytest`
4. Adatforrások tesztje: `.\.venv\Scripts\python.exe -m btcpaper.diagnostics`
5. 1 hónap visszajátszása valódi adaton:
   ```powershell
   .\.venv\Scripts\python.exe scripts\download_history.py --m1-start 2026-09-30 --h1-start 2026-06-01 --d1-start 2025-12-01 --end 2026-11-01T02:00:00Z
   .\.venv\Scripts\python.exe scripts\replay_month.py
   ```
   Az eredmény: `reports\phase1_replay_2026-10.md`
6. Egy kézi "éles" paper futás helyben (csak a `state\` mappába ment, semmit nem küld):
   `.\.venv\Scripts\python.exe -m btcpaper.live --state state`

## GitHub Actions

* **tests**: minden push után lefuttatja a teszteket.
* **diagnostics**: kézzel indítható (Actions fül → *diagnostics* → *Run workflow*). A GitHub
  futtatóról teszteli az összes végpontot, és táblázatban jelenti, melyik működik.
* A fő, 5 percenként futó workflow a Fázis 3-ban készül el (addig a bot nem fut automatikusan).

## Config módosítása

Nyisd meg a `config.yaml`-t, írd át az értéket, mentsd, és küldd fel (commit + push). Minden változás új
config-verziót (hash-t) ad; a motor ezt észleli és paraméterváltozás-riasztást tesz az outboxba.
A kockázati korlátokat (pl. 1 óra jelzés-kor, 3 perc adat-kor) a program nem engedi lazítani.

## Ami a Fázis 3-ban kerül ide

Telegram bot (BotFather) és chat ID beállítása, a secrets (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
`HEALTHCHECK_URL`, opcionálisan `ANTHROPIC_API_KEY`), healthchecks.io beállítása, az Actions bekapcsolása,
a portfóliók nullázása és a teendők heartbeat-riasztáskor.
