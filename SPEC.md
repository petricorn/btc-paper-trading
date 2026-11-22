# Eredeti specifikáció (a tulajdonos saját szövege, változtatás nélkül)

Építs nekem egy Bitcoin PAPER TRADING rendszert, ami a saját GitHub repójában fut, GitHub Actions-ön.

## 0. Alapszabályok (nem alkuképes)
* Ez szimuláció, valódi pénz nincs. Tőzsdei számlát vagy API kulcsot NEM használunk, csak nyilvános piaci adatokat. Valódi megbízást soha nem adsz le.
* Csak spot, csak long, tőkeáttét nincs. Portfóliónként egyszerre legfeljebb 1 nyitott pozíció.
* A kereskedési döntéseket determinisztikus Python kód hozza, nem egy AI-modell. A bot futás közben NEM hív Claude-ot.
* Adatot soha nem találsz ki. Ha egy adat hiányzik, régi vagy ellentmondásos, abban a futásban nincs trade, és ezt naplózod.
* Fázisokban dolgozz (lásd 8. pont). Minden fázis elején írd le a tervet. Minden fázis végén mutasd meg az átadási feltételek teljesülését, és várd meg a jóváhagyásomat. Ha valami nem egyértelmű, kérdezz.

## 1. Architektúra: egyetlen motor
* A backteszt és az éles paper futás UGYANAZT az eseményvezérelt motort használja. Az éles futás csak új gyertyákat ad a motornak. Külön backteszt-logika tilos.
* Python 3.12, a függőségek rögzített verzióval (requirements.txt).
* Minden paraméter a config.yaml-ban legyen. A config verzióját (hash) minden trade-hez és jelzéshez mentsd el.
* Minden időbélyeg UTC-ben legyen tárolva. Az üzenetekben Europe/Budapest idő jelenjen meg.

## 2. Párhuzamos portfóliók (ez a „tanulás" alapja)
* Egyszerre fusson 5 független, képzeletbeli portfólió, mindegyik 200 USD kezdőtőkével:
   * P1, P2, P3: a 3 stratégiajelölt (lásd 4. pont);
   * B1: buy & hold (az indulás napján vesz, és tart);
   * B2: heti DCA (a 200 USD-t 26 hét alatt egyenlő heti részletekben veszi meg).
* A portfóliók ugyanazokat az adatokat és díjakat használják, de semmit nem osztanak meg egymással.
* A cél: élő, előre nem ismert adatokon kiderüljön, melyik változat működik a két mércéhez (B1, B2) képest.

## 3. Adatok: valós és ellenőrzött
* Elsődleges forrás: a Coinbase Exchange nyilvános API-ja (BTC-USD; 1m, 4h vagy 6h, 1d gyertyák). Másodlagos forrás: a Kraken nyilvános API-ja (XBTUSD).
* A Binance api.binance.com-ot ne használd: amerikai szerver-IP-ről 451-es hibát ad, és a GitHub futtatók ilyen IP-ről mennek.
* Először készíts egy "diagnostics" workflow-t. Ez a GitHub futtatóról teszteljen minden végpontot, és jelentse, melyik működik.
* Lapozás: a Coinbase kérésenként korlátozott számú gyertyát ad, ezért a hosszabb időszakokat lapozva kérd le.
* Hiány-ellenőrzés: hiányzó vagy duplikált gyertya esetén abban a futásban nincs döntés.
* Kereszt-ellenőrzés minden futásban: ha a két forrás utolsó ára a beállított küszöbnél jobban eltér (alapból 0,5%), vagy ha az adat 3 percnél régebbi, akkor abban a futásban nincs új trade. Naplózd, milyen gyakran fordul ez elő. Ha a hiba 3 egymást követő futásban fennáll, küldj riasztást.
* Jelzést csak LEZÁRT gyertyából számolj.
* Kiegészítő kontextus a riporthoz: Fear & Greed index (alternative.me). Funding rate és open interest csak akkor, ha a diagnostics szerint elérhető.
* Kell retry exponenciális backoff-fal, timeout, és a rate limitek betartása.

## 4. Stratégiák: lassú idősík, kevés trade, kevés díj
* Döntés csak lezárt 4H és 1D gyertyákon. 1 órás vagy rövidebb idősíkú belépés nincs, mert ott a díjak megeszik a profitot.
* Jelöltek: P1: trendkövető Donchian-kitörés (pl. 20 napos csúcs) napi trendszűrővel (záróár > SMA200 1D); P2: trend + visszahúzódás (4H, emelkedő trendben EMA20/RSI14 pullback, majd visszafordulás); P3: mean reversion Bollinger-szalaggal (4H), csak oldalazó piacon (ADX14 < 20).
* Stratégiánként legfeljebb 3–4 hangolható paraméter.
* Kockázatkezelés portfóliónként: kötésenkénti kockázat a tőke 1,5%-a; pozícióméret = kockázat $ / (belépő − stop), legfeljebb a teljes készpénz. Stop loss ATR alapon (pl. 2×ATR14 a 4H-n), belépéskor rögzítve, a stopot soha nem tágítod. Trailing stop +1R felett, a trailing szintjét csak lezárt 4H gyertyán frissíted. Részleges zárás 2R-nél (konfigurálható). Kiszállás után 1 db 4H gyertya cooldown. Kill switch: ha a portfólió 20%-kal a saját csúcsa alá esik, az a portfólió megáll, és riasztást küld.
* Díj és csúszás: alapból 0,4% díj oldalanként és 0,05% csúszás, mindkettő konfigurálható. Minimum ügyletméret: 10 USD.

## 5. Pontos szimuláció: nincs utólagos okosság
* BELÉPÉS: a döntés TÉNYLEGES időpontjában érvényes áron teljesül: a futás pillanatában lekért aktuális ár (Coinbase ticker, ask oldal), csúszással. Múltbeli gyertya árán soha nem teljesül, akkor sem, ha a GitHub-futás késett. Ha a jelzés óta több mint 1 óra telt el, vagy az ár már a stop alatt van, a belépés elmarad, és ezt naplózod.
* STOP és CÉLÁR: várakozó megbízásként viselkednek. Minden futáskor töltsd le az 1 perces gyertyákat az utolsó ellenőrzés óta, és időrendben menj végig rajtuk: ha a low ≤ stop, a stop teljesül (ha a gyertya a stop alatt nyitott, akkor a nyitóáron); ha a high ≥ cél, a cél teljesül; ha egy percben mindkettő megtörténik, a stop számít.
* A tőkét mindig a trade-naplóból számold újra. Invariáns-ellenőrzések: készpénz ≥ 0, BTC ≥ 0, a könyvelés egyezik. Ha egy ellenőrzés elbukik, a futás hibával álljon le.

## 6. Futtatás, állapot, megbízhatóság
* Fő workflow: cron "*/5 * * * *" + workflow_dispatch. Concurrency group (cancel-in-progress: false) és timeout-minutes.
* Kérdezd meg, hogy publikus vagy privát lesz-e a repó. Privátnál legalább 30 perces intervallum.
* Állapot: state/ mappa (portfolios.json, trades.csv, equity.csv, signals.csv, outbox.json) a "bot-state" ágon, csak az utolsó állapot egyetlen commitban (force-push). A napi riport a main ág reports/ mappájába kerüljön (aktívan tartja a repót a 60 napos inaktivitási tiltás ellen).
* Ismételhetőség: minden futásnak legyen azonosítója; ugyanazt az időszakot kétszer feldolgozva se keletkezzen dupla trade. Ha a mentés (push) elbukik, a futás hibával álljon le, és ne küldjön üzenetet. A következő futás az utolsó mentett állapotból folytassa.
* Outbox: az üzenet először az outbox-ba kerül, csak a sikeres mentés után megy ki; ami nem ment ki, a következő futásban újra próbálkozik; minden üzenetnek egyedi azonosítója van.
* Heartbeat: minden sikeres futás végén pingelj egy külső figyelőt (HEALTHCHECK_URL secret, pl. healthchecks.io); a README-ben írd le a beállítását.

## 7. Értesítések: Telegram, magyarul
* Secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID. Minden üzenet elején a portfólió neve.
* VÉTEL: időpont, ár, BTC mennyiség, érték $, díj, stop loss, célár, kockázat $ és %, indoklás (jelzések és értékeik), config verzió, maradék készpénz, teljes tőke.
* ELADÁS: kiszállási ár, ok (stop / cél / trailing / jelzés), P&L $ és %, díjak, új egyenleg, a portfólió eddigi statisztikája.
* NAPI RIPORT minden reggel 7:00-kor magyar idő szerint (cron 05:07 és 06:07 UTC, a kód csak akkor küld, ha Budapesten 7 óra van): ár, 24 órás és 7 napos változás; trend 1D és 4H, RSI, ATR-volatilitás; támaszok és ellenállások; Fear & Greed; RANGSOR mind az 5 portfólióról (tőke, hozam, max drawdown, trade-ek száma, win rate, profit factor); nyitott pozíciók és nem realizált P&L; mire vár most az egyes stratégia; adatok állapota (kimaradt futások, elbukott kereszt-ellenőrzések).
* Heti összefoglaló, valamint riasztás adat-hiba, kill switch, mentési hiba és paraméterváltozás esetén.
* Opcionális: ha van ANTHROPIC_API_KEY secret, a napi riport kapjon 3–5 mondatos értékelést a legolcsóbb aktuális Claude modellel; ha nincs kulcs, kimarad; a döntésekre nem hat.

## 8. Fázisok és átadási feltételek
* FÁZIS 1: adatréteg, diagnostics, motor, könyvelés. Átadás: a diagnostics zöld a GitHub futtatón; a pytest tesztek zöldek (indikátorok, pozícióméret, stop/cél teljesülés a szélső esetekben, késett futás, dupla futás, könyvelés); 1 hónap múltbeli időszak visszajátszása hibátlan.
* FÁZIS 2: backteszt és stratégiaválasztás. Legalább 4 év adat, díjakkal és csúszással. Az utolsó 6 hónap érintetlen tartalék, csak a fázis végén, egyszer. Walk-forward hangolás. Robusztusság: csak olyan paraméter, aminek a szomszéd értékei is hasonlóan jók. Monte Carlo a trade-sorrend keverésével, drawdown-eloszlás. Átadás: táblázat stratégiánként (hozam, max drawdown, Sharpe, win rate, profit factor, trade-ek száma) B1-gyel és B2-vel összevetve, mintán belül és a tartalékon. Őszintén jelentsd, ha egyik stratégia sem jobb kockázattal korrigálva.
* FÁZIS 3: éles paper futás GitHubon: Telegram, napi riport, outbox, heartbeat. Átadás: 48 órás próbafutás hibátlanul, legalább 1 szándékosan kiváltott hibával, amit a rendszer helyesen kezel.
* FÁZIS 4: tanulás. Csak 3 hónap éles futás után, alapból kikapcsolva. Legfeljebb havonta hangol újra, határok között; csak érdemben jobb out-of-sample eredménnyel és elég trade-del élesedik; a kockázati limitekhez soha nem nyúl; minden változás új config-verzió, learning_log.md-be és üzenetben is.

## 9. Siker-definíció
Értékelés legkorábban 3 hónap éles futás után, csak legalább 30 lezárt trade-del. Egy stratégia akkor „jó", ha kockázattal korrigálva (Sharpe, max drawdown) jobb a B1-nél és a B2-nél is, díjak után. Ha nem, a riport ezt egyenesen kimondja.

## 10. README
Magyarul, lépésről lépésre: Telegram bot (BotFather) és chat ID; secrets és healthchecks.io beállítása; Actions bekapcsolása; config módosítása és portfóliók nullázása; teendő heartbeat-riasztáskor.
