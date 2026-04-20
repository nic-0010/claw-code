"""
Aggiunte a tools.py — incolla queste sezioni nel tuo tools.py esistente.

Modifiche:
  1. TTLCache su get_stock_price e get_etf_info (5 minuti)
  2. confronta_portafoglio con ThreadPoolExecutor (fetch parallelo)
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from cachetools import TTLCache
import threading

# ── Cache ──────────────────────────────────────────────────────────────────────
# TTL = 300 secondi (5 min). maxsize = 256 ticker distinti.
_price_cache: TTLCache = TTLCache(maxsize=256, ttl=300)
_etf_cache:   TTLCache = TTLCache(maxsize=256, ttl=300)
_cache_lock = threading.Lock()


# ── Sostituisce get_stock_price ───────────────────────────────────────────────
def get_stock_price(ticker: str) -> str:
    ticker = ticker.upper().strip()
    with _cache_lock:
        if ticker in _price_cache:
            return _price_cache[ticker]

    # --- Incolla qui il corpo della tua get_stock_price originale ---
    # result = ...
    # ---------------------------------------------------------------

    with _cache_lock:
        _price_cache[ticker] = result
    return result


# ── Sostituisce get_etf_info ──────────────────────────────────────────────────
def get_etf_info(ticker: str) -> str:
    ticker = ticker.upper().strip()
    with _cache_lock:
        if ticker in _etf_cache:
            return _etf_cache[ticker]

    # --- Incolla qui il corpo della tua get_etf_info originale ---
    # result = ...
    # ------------------------------------------------------------

    with _cache_lock:
        _etf_cache[ticker] = result
    return result


# ── Sostituisce confronta_portafoglio ─────────────────────────────────────────
def confronta_portafoglio(tickers: list[str]) -> str:
    """Fetch parallelo: O(1) invece di O(n) rispetto al loop sequenziale."""
    tickers = [t.upper().strip() for t in tickers]

    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(len(tickers), 10)) as pool:
        future_to_ticker = {pool.submit(get_etf_info, t): t for t in tickers}
        for future in as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            try:
                results[ticker] = future.result()
            except Exception as e:
                results[ticker] = f"Errore per {ticker}: {e}"

    # --- Incolla qui la logica di formattazione del tuo originale ---
    # (il dizionario results ha {ticker: info_string} per tutti i ticker)
    # output = ...
    # ---------------------------------------------------------------
    return output
