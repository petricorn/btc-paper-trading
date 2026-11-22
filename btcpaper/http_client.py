"""HTTP kliens: timeout, újrapróbálás exponenciális backoff-fal, rate limit (kérések közti szünet)."""
from __future__ import annotations

import time
from decimal import Decimal

import requests

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class HttpError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class HttpClient:
    def __init__(self, timeout: float = 10, max_retries: int = 5, backoff_base: float = 1.0,
                 min_interval: float = 0.15, user_agent: str = "btc-paper-trading/0.1",
                 session: requests.Session | None = None, sleep=time.sleep, clock=time.monotonic,
                 max_backoff: float = 30.0):
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.min_interval = min_interval
        self.max_backoff = max_backoff
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "application/json"})
        self._sleep = sleep
        self._clock = clock
        self._last = None
        self.request_count = 0

    @classmethod
    def from_config(cls, cfg, **kw) -> "HttpClient":
        return cls(timeout=cfg.i("http.timeout_seconds"), max_retries=cfg.i("http.max_retries"),
                   backoff_base=float(cfg.d("http.backoff_base_seconds")),
                   min_interval=float(cfg.d("http.min_interval_seconds")),
                   user_agent=str(cfg.get("http.user_agent")), **kw)

    def _throttle(self):
        if self._last is not None:
            wait = self.min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def get_json(self, url: str, params: dict | None = None):
        last_err = "ismeretlen hiba"
        status = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            retry_after = None
            try:
                self.request_count += 1
                r = self.session.get(url, params=params, timeout=self.timeout)
            except (requests.Timeout, requests.ConnectionError) as e:
                last_err = f"{type(e).__name__}: {e}"
                status = None
            else:
                status = r.status_code
                if r.status_code == 200:
                    try:
                        return r.json(parse_float=Decimal)
                    except ValueError as e:
                        raise HttpError(f"Hibás JSON válasz: {url}: {e}", status) from e
                if r.status_code not in RETRYABLE_STATUS:
                    raise HttpError(f"HTTP {r.status_code} {url}: {r.text[:200]}", r.status_code)
                last_err = f"HTTP {r.status_code}: {r.text[:200]}"
                ra = r.headers.get("Retry-After")
                if ra:
                    try:
                        retry_after = float(ra)
                    except ValueError:
                        retry_after = None
            if attempt == self.max_retries:
                break
            delay = min(self.backoff_base * (2 ** attempt), self.max_backoff)
            if retry_after is not None:
                delay = max(delay, min(retry_after, self.max_backoff))
            self._sleep(delay)
        raise HttpError(f"Sikertelen kérés {self.max_retries + 1} próbálkozás után: {url}: {last_err}", status)
