"""
Mock tools.py — simula yfinance con dati realistici per test locali.
In produzione questo file è sostituito dal tools.py reale con yfinance.
"""

import time
import random
from cachetools import TTLCache
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

_price_cache: TTLCache = TTLCache(maxsize=256, ttl=300)
_etf_cache:   TTLCache = TTLCache(maxsize=256, ttl=300)
_cache_lock   = threading.Lock()

# Dati mock realistici
MOCK_DATA = {
    "VWCE.DE":  {"price": 118.42, "ter": 0.22, "aum": 18_200, "type": "ETF",  "desc": "Vanguard FTSE All-World Acc"},
    "XDWD.DE":  {"price": 89.15,  "ter": 0.19, "aum": 9_800,  "type": "ETF",  "desc": "iShares MSCI World Acc"},
    "ISPA.MI":  {"price": 5.62,   "ter": 0.20, "aum": 1_200,  "type": "ETF",  "desc": "iShares MSCI EM IMI Acc"},
    "AAPL":     {"price": 189.30, "ter": None,  "aum": None,   "type": "Stock","desc": "Apple Inc."},
    "MSFT":     {"price": 415.20, "ter": None,  "aum": None,   "type": "Stock","desc": "Microsoft Corp"},
    "NVDA":     {"price": 875.50, "ter": None,  "aum": None,   "type": "Stock","desc": "NVIDIA Corp"},
    "SPY":      {"price": 512.80, "ter": 0.09,  "aum": 520_000,"type": "ETF",  "desc": "SPDR S&P 500 ETF"},
    "SWRD.MI":  {"price": 74.30,  "ter": 0.12,  "aum": 4_500,  "type": "ETF",  "desc": "SPDR MSCI World Acc"},
}

def _simulated_delay():
    """Simula latenza rete yfinance (50-150ms)."""
    time.sleep(random.uniform(0.05, 0.15))


def get_stock_price(ticker: str) -> str:
    ticker = ticker.upper().strip()
    with _cache_lock:
        if ticker in _price_cache:
            return _price_cache[ticker] + " [cached]"

    _simulated_delay()

    data = MOCK_DATA.get(ticker)
    if not data:
        result = f"Ticker {ticker} non trovato."
    else:
        result = (
            f"{ticker} ({data['desc']})\n"
            f"Prezzo: €{data['price']:.2f}\n"
            f"Tipo: {data['type']}\n"
            f"Aggiornato: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    with _cache_lock:
        _price_cache[ticker] = result
    return result


def get_etf_info(ticker: str) -> str:
    ticker = ticker.upper().strip()
    with _cache_lock:
        if ticker in _etf_cache:
            return _etf_cache[ticker] + " [cached]"

    _simulated_delay()

    data = MOCK_DATA.get(ticker)
    if not data or data["type"] != "ETF":
        result = f"{ticker}: dati ETF non disponibili."
    else:
        result = (
            f"{ticker} — {data['desc']}\n"
            f"Prezzo: €{data['price']:.2f}\n"
            f"TER: {data['ter']}%\n"
            f"AUM: €{data['aum']:,}M\n"
            f"Tipo: Accumulo\n"
            f"Borsa: {'XETRA' if '.DE' in ticker else 'Borsa Italiana'}"
        )

    with _cache_lock:
        _etf_cache[ticker] = result
    return result


def confronta_portafoglio(tickers: list) -> str:
    tickers = [t.upper().strip() for t in tickers]

    results = {}
    with ThreadPoolExecutor(max_workers=min(len(tickers), 10)) as pool:
        future_to_ticker = {pool.submit(get_etf_info, t): t for t in tickers}
        for future in as_completed(future_to_ticker):
            t = future_to_ticker[future]
            try:
                results[t] = future.result()
            except Exception as e:
                results[t] = f"Errore: {e}"

    lines = [f"=== Confronto Portafoglio ({len(tickers)} strumenti) ===\n"]
    for ticker in tickers:
        lines.append(f"--- {ticker} ---")
        lines.append(results.get(ticker, "N/D"))
        lines.append("")
    return "\n".join(lines)
