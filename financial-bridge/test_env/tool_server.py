"""
HTTP wrapper that espone i tool del financial-agent come endpoint REST.
Copia questo file nella cartella financial-agent/ e avvialo con:
    python tool_server.py

Gira su porta 5001 (separato dal web_app.py che usa 5000).
Il claw-code iOS SDK chiama questi endpoint come tool remoti.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, jsonify, request
from flask_cors import CORS

# Import dei tool esistenti — assicurati che tools.py sia nella stessa cartella
from tools import get_stock_price, get_etf_info, confronta_portafoglio

app = Flask(__name__)
CORS(app)

executor = ThreadPoolExecutor(max_workers=8)


# ── Health ────────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "financial-tool-server"})


# ── Tool endpoints ────────────────────────────────────────────────────────────

@app.route("/tool/get_stock_price", methods=["POST"])
def api_get_stock_price():
    data = request.get_json(force=True)
    ticker = data.get("ticker", "")
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400
    try:
        result = get_stock_price(ticker)
        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/tool/get_etf_info", methods=["POST"])
def api_get_etf_info():
    data = request.get_json(force=True)
    ticker = data.get("ticker", "")
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400
    try:
        result = get_etf_info(ticker)
        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/tool/confronta_portafoglio", methods=["POST"])
def api_confronta_portafoglio():
    data = request.get_json(force=True)
    tickers = data.get("tickers", [])
    if not tickers:
        return jsonify({"error": "tickers is required (list)"}), 400
    try:
        result = confronta_portafoglio(tickers)
        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Batch endpoint (chiama più tool in parallelo in una sola request) ─────────

@app.route("/tool/batch", methods=["POST"])
def api_batch():
    """
    Esegue più tool in parallelo. Body:
    {
        "calls": [
            {"tool": "get_stock_price", "input": {"ticker": "AAPL"}},
            {"tool": "get_etf_info",    "input": {"ticker": "VWCE.DE"}}
        ]
    }
    """
    data = request.get_json(force=True)
    calls = data.get("calls", [])
    if not calls:
        return jsonify({"error": "calls is required"}), 400

    tool_map = {
        "get_stock_price":     lambda inp: get_stock_price(inp["ticker"]),
        "get_etf_info":        lambda inp: get_etf_info(inp["ticker"]),
        "confronta_portafoglio": lambda inp: confronta_portafoglio(inp["tickers"]),
    }

    futures = {}
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        for i, call in enumerate(calls):
            fn = tool_map.get(call["tool"])
            if fn:
                futures[pool.submit(fn, call["input"])] = i

    results = [None] * len(calls)
    for future, idx in futures.items():
        try:
            results[idx] = {"ok": future.result()}
        except Exception as e:
            results[idx] = {"error": str(e)}

    return jsonify({"results": results})


if __name__ == "__main__":
    print("Financial Tool Server running on http://0.0.0.0:5001")
    app.run(host="0.0.0.0", port=5001, debug=False, threaded=True)
