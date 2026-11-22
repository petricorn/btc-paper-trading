"""Nyilvános piaci adatforrások. Csak olvasás, API kulcs nélkül. Megbízást SOHA nem ad le."""
from __future__ import annotations

from decimal import Decimal

from .http_client import HttpClient, HttpError
from .models import Candle, Quote, RefPrice
from .num import D
from .timeutil import iso, parse_iso

COINBASE = "https://api.exchange.coinbase.com"
KRAKEN = "https://api.kraken.com"
FEAR_GREED = "https://api.alternative.me/fng/"

COINBASE_GRANULARITIES = {60, 300, 900, 3600, 21600, 86400}
COINBASE_MAX_CANDLES = 300


class DataError(RuntimeError):
    pass


def coinbase_windows(gran: int, start: int, end: int) -> list[tuple[int, int]]:
    """Lapozás: [start, end] (mindkettő zárt) felosztása legfeljebb 300 gyertyás ablakokra.

    A Coinbase mindkét végpontot beleszámolja, és legfeljebb 300 gyertyát enged kérésenként,
    ezért egy ablak: ws .. ws + 299*gran. Az ablakok nem fednek át.
    """
    if gran not in COINBASE_GRANULARITIES:
        raise ValueError(f"Coinbase granularity nem támogatott: {gran}")
    start = (start // gran) * gran
    end = (end // gran) * gran
    out = []
    ws = start
    while ws <= end:
        we = min(ws + (COINBASE_MAX_CANDLES - 1) * gran, end)
        out.append((ws, we))
        ws = we + gran
    return out


class CoinbaseClient:
    def __init__(self, http: HttpClient, product: str = "BTC-USD"):
        self.http = http
        self.product = product

    def candles(self, gran: int, start: int, end: int) -> list[Candle]:
        """Gyertyák [start, end] között, lapozva. A folyamatban lévő gyertyát is visszaadhatja
        (a hívó szűri a lezártakra). Nyers lista: duplikátum/hiány ellenőrzés a hívónál."""
        out: list[Candle] = []
        for ws, we in coinbase_windows(gran, start, end):
            data = self.http.get_json(
                f"{COINBASE}/products/{self.product}/candles",
                params={"granularity": gran, "start": iso(ws), "end": iso(we)},
            )
            if not isinstance(data, list):
                raise DataError(f"Coinbase candles: váratlan válasz: {str(data)[:200]}")
            for row in data:
                # Coinbase sorrend: [time, low, high, open, close, volume]
                if not isinstance(row, list) or len(row) < 6:
                    raise DataError(f"Coinbase candles: hibás sor: {row!r}")
                t = int(row[0])
                if t < ws or t > we:
                    continue   # ablakon kívüli elem: nem a mi kérésünk része
                out.append(Candle(start=t, low=D(row[1]), high=D(row[2]), open=D(row[3]),
                                  close=D(row[4]), volume=D(row[5])))
        out.sort(key=lambda c: c.start)
        return out

    def ticker(self) -> Quote:
        d = self.http.get_json(f"{COINBASE}/products/{self.product}/ticker")
        try:
            return Quote(bid=D(d["bid"]), ask=D(d["ask"]), last=D(d["price"]),
                         time=parse_iso(d["time"]), source="coinbase")
        except (KeyError, TypeError, ValueError) as e:
            raise DataError(f"Coinbase ticker: hibás válasz: {str(d)[:200]}") from e

    def server_time(self) -> float:
        d = self.http.get_json(f"{COINBASE}/time")
        try:
            return float(d["epoch"])
        except (KeyError, TypeError, ValueError) as e:
            raise DataError(f"Coinbase time: hibás válasz: {str(d)[:200]}") from e


class KrakenClient:
    def __init__(self, http: HttpClient, pair: str = "XBTUSD"):
        self.http = http
        self.pair = pair

    def _result(self, path: str, params: dict) -> dict:
        d = self.http.get_json(f"{KRAKEN}{path}", params=params)
        if not isinstance(d, dict) or d.get("error"):
            raise DataError(f"Kraken {path}: hiba: {str(d)[:200]}")
        return d["result"]

    def last_price(self, now: float) -> RefPrice:
        """Utolsó ár és ideje a Kraken 1 perces OHLC-ből (a legutolsó, folyamatban lévő gyertya záróára)."""
        res = self._result("/0/public/OHLC", {"pair": self.pair, "interval": 1, "since": int(now) - 600})
        rows = [v for k, v in res.items() if k != "last"]
        if not rows or not rows[0]:
            raise DataError("Kraken OHLC: üres válasz")
        last = rows[0][-1]
        # Kraken sor: [time, open, high, low, close, vwap, volume, count]
        return RefPrice(price=D(last[4]), time=float(last[0]), source="kraken")

    def ohlc(self, interval_min: int, since: int | None = None) -> list[Candle]:
        params = {"pair": self.pair, "interval": interval_min}
        if since is not None:
            params["since"] = since
        res = self._result("/0/public/OHLC", params)
        rows = [v for k, v in res.items() if k != "last"][0]
        return [Candle(start=int(r[0]), open=D(r[1]), high=D(r[2]), low=D(r[3]), close=D(r[4]),
                       volume=D(r[6])) for r in rows]


def fear_greed(http: HttpClient) -> dict:
    d = http.get_json(FEAR_GREED, params={"limit": 2})
    try:
        item = d["data"][0]
        return {"value": int(item["value"]), "label": item["value_classification"],
                "time": int(item["timestamp"])}
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise DataError(f"Fear & Greed: hibás válasz: {str(d)[:200]}") from e


__all__ = ["CoinbaseClient", "KrakenClient", "fear_greed", "DataError", "HttpError", "coinbase_windows",
           "Decimal"]
