"""
Back test + Stress test del financial tool server.

Test suite:
  1. Functional tests  — ogni endpoint risponde correttamente
  2. Cache tests       — seconda chiamata è più veloce (TTL cache)
  3. Parallel tests    — /tool/batch è più veloce dei singoli sequenziali
  4. Stress test       — N utenti concorrenti per M secondi
  5. Error handling    — ticker invalidi, payload malformati
"""

import json
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BASE = "http://localhost:5001"
PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m→\033[0m"

results = {"passed": 0, "failed": 0}


def check(name: str, ok: bool, detail: str = ""):
    if ok:
        results["passed"] += 1
        print(f"  {PASS} {name}")
    else:
        results["failed"] += 1
        print(f"  {FAIL} {name}  ← {detail}")


def post(path: str, body: dict, timeout: int = 10) -> requests.Response:
    return requests.post(f"{BASE}{path}", json=body, timeout=timeout)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Functional tests
# ─────────────────────────────────────────────────────────────────────────────

def test_functional():
    print(f"\n{INFO} FUNCTIONAL TESTS")

    # health
    r = requests.get(f"{BASE}/health")
    check("GET /health → 200", r.status_code == 200)
    check("health has status:ok", r.json().get("status") == "ok")

    # get_stock_price
    r = post("/tool/get_stock_price", {"ticker": "AAPL"})
    check("get_stock_price AAPL → 200", r.status_code == 200)
    check("get_stock_price AAPL has result", "result" in r.json())
    check("get_stock_price AAPL price present", "Apple" in r.json().get("result", ""))

    # get_etf_info
    r = post("/tool/get_etf_info", {"ticker": "VWCE.DE"})
    check("get_etf_info VWCE.DE → 200", r.status_code == 200)
    check("get_etf_info has TER", "TER" in r.json().get("result", ""))

    # confronta_portafoglio
    r = post("/tool/confronta_portafoglio", {"tickers": ["VWCE.DE", "XDWD.DE", "ISPA.MI"]})
    check("confronta_portafoglio 3 tickers → 200", r.status_code == 200)
    body = r.json().get("result", "")
    check("confronta_portafoglio has all tickers", all(t in body for t in ["VWCE.DE", "XDWD.DE", "ISPA.MI"]))


# ─────────────────────────────────────────────────────────────────────────────
# 2. Cache tests
# ─────────────────────────────────────────────────────────────────────────────

def test_cache():
    print(f"\n{INFO} CACHE TESTS")

    ticker = "MSFT"

    # Prima chiamata (cold)
    t0 = time.perf_counter()
    r1 = post("/tool/get_stock_price", {"ticker": ticker})
    cold_ms = (time.perf_counter() - t0) * 1000

    # Seconda chiamata (cached)
    t1 = time.perf_counter()
    r2 = post("/tool/get_stock_price", {"ticker": ticker})
    warm_ms = (time.perf_counter() - t1) * 1000

    check(f"Cold call {cold_ms:.0f}ms, warm call {warm_ms:.0f}ms", True)
    check("Cache hit: warm < cold", warm_ms < cold_ms,
          f"{warm_ms:.0f}ms not < {cold_ms:.0f}ms")
    check("Cache tag in response", "[cached]" in r2.json().get("result", ""))

    speedup = cold_ms / max(warm_ms, 0.1)
    check(f"Cache speedup ≥ 2x (got {speedup:.1f}x)", speedup >= 2)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Parallel batch tests
# ─────────────────────────────────────────────────────────────────────────────

def test_parallel_batch():
    print(f"\n{INFO} PARALLEL BATCH TESTS")

    tickers = ["VWCE.DE", "XDWD.DE", "ISPA.MI", "SPY", "SWRD.MI"]

    # Sequenziale (cold — svuota cache)
    t0 = time.perf_counter()
    for t in tickers:
        post("/tool/get_etf_info", {"ticker": t + "_NOCACHE"})
    seq_ms = (time.perf_counter() - t0) * 1000

    # Parallelo via /tool/batch
    calls = [{"tool": "get_etf_info", "input": {"ticker": t}} for t in tickers]
    t1 = time.perf_counter()
    r = post("/tool/batch", {"calls": calls})
    par_ms = (time.perf_counter() - t1) * 1000

    check("batch → 200", r.status_code == 200)
    check(f"batch returned {len(tickers)} results",
          len(r.json().get("results", [])) == len(tickers))

    speedup = seq_ms / max(par_ms, 1)
    check(f"Batch speedup ≥ 2x (seq={seq_ms:.0f}ms par={par_ms:.0f}ms, {speedup:.1f}x)",
          speedup >= 2)

    # Tutti i risultati ok
    all_ok = all("ok" in res for res in r.json().get("results", []))
    check("All batch results successful", all_ok)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Stress test
# ─────────────────────────────────────────────────────────────────────────────

def stress_worker(worker_id: int, duration_s: float, stats: dict, lock: threading.Lock):
    """Ogni worker martella il server per duration_s secondi."""
    requests_done = 0
    errors = 0
    latencies = []

    endpoints = [
        ("/tool/get_stock_price",    {"ticker": "AAPL"}),
        ("/tool/get_etf_info",       {"ticker": "VWCE.DE"}),
        ("/tool/get_stock_price",    {"ticker": "MSFT"}),
        ("/tool/confronta_portafoglio", {"tickers": ["VWCE.DE", "XDWD.DE"]}),
    ]

    deadline = time.time() + duration_s
    idx = 0
    while time.time() < deadline:
        path, body = endpoints[idx % len(endpoints)]
        idx += 1
        t0 = time.perf_counter()
        try:
            r = post(path, body, timeout=5)
            latency_ms = (time.perf_counter() - t0) * 1000
            if r.status_code == 200:
                requests_done += 1
                latencies.append(latency_ms)
            else:
                errors += 1
        except Exception:
            errors += 1

    with lock:
        stats["requests"] += requests_done
        stats["errors"]   += errors
        stats["latencies"].extend(latencies)


def test_stress(concurrency: int = 20, duration_s: float = 5.0):
    print(f"\n{INFO} STRESS TEST ({concurrency} workers × {duration_s}s)")

    stats = {"requests": 0, "errors": 0, "latencies": []}
    lock  = threading.Lock()

    threads = [
        threading.Thread(target=stress_worker, args=(i, duration_s, stats, lock))
        for i in range(concurrency)
    ]
    t0 = time.time()
    for th in threads: th.start()
    for th in threads: th.join()
    elapsed = time.time() - t0

    total   = stats["requests"]
    errors  = stats["errors"]
    lats    = sorted(stats["latencies"])
    rps     = total / elapsed
    p50     = lats[len(lats) // 2]      if lats else 0
    p95     = lats[int(len(lats) * .95)] if lats else 0
    p99     = lats[int(len(lats) * .99)] if lats else 0
    err_pct = errors / max(total + errors, 1) * 100

    print(f"     Requests:   {total:,}  ({rps:.0f} req/s)")
    print(f"     Errors:     {errors} ({err_pct:.1f}%)")
    print(f"     Latency:    p50={p50:.0f}ms  p95={p95:.0f}ms  p99={p99:.0f}ms")

    check(f"Throughput ≥ 50 req/s (got {rps:.0f})",     rps >= 50)
    check(f"Error rate < 1% (got {err_pct:.1f}%)",       err_pct < 1.0)
    check(f"p95 latency < 500ms (got {p95:.0f}ms)",      p95 < 500)
    check(f"p99 latency < 1000ms (got {p99:.0f}ms)",     p99 < 1000)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Error handling tests
# ─────────────────────────────────────────────────────────────────────────────

def test_error_handling():
    print(f"\n{INFO} ERROR HANDLING TESTS")

    # Ticker sconosciuto
    r = post("/tool/get_stock_price", {"ticker": "INVALID_TICKER_XYZ"})
    check("Unknown ticker → 200 with message", r.status_code == 200 and "result" in r.json())

    # Payload mancante
    r = post("/tool/get_stock_price", {})
    check("Missing ticker → 400", r.status_code == 400)

    # Endpoint inesistente
    r = requests.post(f"{BASE}/tool/nonexistent", json={}, timeout=5)
    check("Unknown tool → 404 or 405", r.status_code in (404, 405))

    # Tickers lista vuota
    r = post("/tool/confronta_portafoglio", {"tickers": []})
    check("Empty tickers list → 400", r.status_code == 400)

    # Batch con tool inesistente
    r = post("/tool/batch", {"calls": [{"tool": "unknown_tool", "input": {}}]})
    check("Batch with unknown tool → 200 (graceful)", r.status_code == 200)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Financial Tool Server — Test Suite")
    print("=" * 60)

    try:
        requests.get(f"{BASE}/health", timeout=3)
    except Exception:
        print(f"\n{FAIL} Server non raggiungibile su {BASE}. Avvia tool_server.py prima.\n")
        sys.exit(1)

    test_functional()
    test_cache()
    test_parallel_batch()
    test_error_handling()
    test_stress(concurrency=20, duration_s=5.0)

    print("\n" + "=" * 60)
    total = results["passed"] + results["failed"]
    print(f"  Risultato: {results['passed']}/{total} test passati", end="")
    if results["failed"]:
        print(f"  ({results['failed']} FALLITI)")
    else:
        print("  — TUTTO OK ✓")
    print("=" * 60 + "\n")
    sys.exit(0 if results["failed"] == 0 else 1)
