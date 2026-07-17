"""
End-to-end test: Anthropic API → tool_use loop → tool_server.py → yfinance.

Questo script simula esattamente quello che fa il claw-ios-sdk Rust:
  1. Manda una query a Claude con i 3 tool definiti
  2. Claude decide di chiamare i tool
  3. Noi inoltriamo la chiamata a http://localhost:5001/tool/<name>
  4. Restituiamo il risultato a Claude
  5. Claude produce la risposta finale

Requisiti prima di lanciare:
  - export ANTHROPIC_API_KEY=sk-ant-...
  - tool_server.py deve essere in esecuzione su localhost:5001
    (lancialo in un altro terminale: python tool_server.py)
  - pip install anthropic requests

Uso:
  python e2e_test.py
  python e2e_test.py --model claude-haiku-4-5-20251001
  python e2e_test.py --prompt "Quanto costa Apple oggi?"
"""

import argparse
import json
import os
import sys
import time

import requests

try:
    from anthropic import Anthropic
except ImportError:
    print("ERRORE: pip install anthropic", file=sys.stderr)
    sys.exit(1)

BASE = "http://localhost:5001"

# Stessa definizione usata in rust/crates/claw-ios-sdk/src/financial.rs
TOOLS = [
    {
        "name": "get_stock_price",
        "description": "Get the current price and key metrics for a stock or ETF ticker (e.g. AAPL, VWCE.DE).",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock or ETF ticker symbol"}
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_etf_info",
        "description": "Get detailed information about an ETF: TER, asset class, geographic exposure, AUM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "ETF ticker symbol, e.g. VWCE.DE"}
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "confronta_portafoglio",
        "description": "Compare multiple ETFs or stocks side by side: performance, fees, exposure, risk metrics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tickers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of ticker symbols to compare",
                }
            },
            "required": ["tickers"],
        },
    },
]

SYSTEM_PROMPT = """You have access to financial data tools: get_stock_price, get_etf_info, confronta_portafoglio.
When answering questions about stocks, ETFs, or portfolios:
1. Fetch current data with get_stock_price or get_etf_info before answering
2. For comparisons, use confronta_portafoglio with all tickers at once
3. Always include the data source timestamp and note that prices may be delayed"""


# ─── Tool dispatch ────────────────────────────────────────────────────────────

def dispatch_tool(name: str, tool_input: dict) -> str:
    """Forward a tool call to tool_server.py and return the text result."""
    url = f"{BASE}/tool/{name}"
    resp = requests.post(url, json=tool_input, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        return f"Tool error: {data['error']}"
    return data.get("result", "")


# ─── Agent loop ───────────────────────────────────────────────────────────────

def run_agent(client: Anthropic, model: str, prompt: str, verbose: bool = True):
    """
    Tool-use loop stile Anthropic API:
      - invia messaggio
      - se stop_reason == "tool_use", esegui i tool e rimanda la risposta
      - ripeti finché stop_reason != "tool_use"
    """
    messages = [{"role": "user", "content": prompt}]
    stats = {
        "iterations": 0,
        "tool_calls": [],
        "input_tokens": 0,
        "output_tokens": 0,
        "start": time.perf_counter(),
    }

    while True:
        stats["iterations"] += 1
        if verbose:
            print(f"\n→ Iteration {stats['iterations']}: calling Claude ({model})...")

        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        stats["input_tokens"] += resp.usage.input_tokens
        stats["output_tokens"] += resp.usage.output_tokens

        # Aggiungi la risposta assistant alla cronologia
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            if verbose:
                print(f"  Stop reason: {resp.stop_reason}")
            # Raccogli tutto il testo finale
            final_text = "".join(
                block.text for block in resp.content if block.type == "text"
            )
            stats["elapsed"] = time.perf_counter() - stats["start"]
            return final_text, stats

        # Altrimenti esegui ogni tool_use block e costruisci tool_result
        tool_results_content = []
        for block in resp.content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_input = block.input
            stats["tool_calls"].append({"name": tool_name, "input": tool_input})

            if verbose:
                print(f"  🔧 {tool_name}({json.dumps(tool_input, ensure_ascii=False)})")

            try:
                result_text = dispatch_tool(tool_name, tool_input)
                preview = result_text.replace("\n", " ")[:120]
                if verbose:
                    print(f"     ← {preview}...")
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })
            except Exception as e:
                if verbose:
                    print(f"     ← ERROR: {e}")
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Error: {e}",
                    "is_error": True,
                })

        messages.append({"role": "user", "content": tool_results_content})


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="E2E test for financial tool server + Anthropic API")
    parser.add_argument("--model", default="claude-haiku-4-5-20251001",
                        help="Anthropic model (default: claude-haiku-4-5)")
    parser.add_argument("--prompt", default=None,
                        help="Query to test (default: runs 3 suite scenarios)")
    parser.add_argument("--quiet", action="store_true", help="Suppress iteration logs")
    args = parser.parse_args()

    # Pre-flight checks
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERRORE: esporta ANTHROPIC_API_KEY prima di lanciare.", file=sys.stderr)
        print("  export ANTHROPIC_API_KEY=sk-ant-...", file=sys.stderr)
        sys.exit(1)

    try:
        requests.get(f"{BASE}/health", timeout=3).raise_for_status()
    except Exception:
        print(f"ERRORE: tool_server.py non raggiungibile su {BASE}", file=sys.stderr)
        print("  Lancia in un altro terminale: python tool_server.py", file=sys.stderr)
        sys.exit(1)

    client = Anthropic(api_key=api_key)

    scenarios = [args.prompt] if args.prompt else [
        "Quanto costa Apple (AAPL) oggi?",
        "Dammi i dettagli dell'ETF VWCE.DE: TER, AUM, composizione.",
        "Confronta VWCE.DE, XDWD.DE e SWRD.MI: quale ha il TER più basso?",
    ]

    print("=" * 70)
    print(f"  E2E Test — model={args.model}")
    print("=" * 70)

    total_passed = 0
    total_failed = 0

    for i, prompt in enumerate(scenarios, 1):
        print(f"\n[Scenario {i}/{len(scenarios)}] {prompt}")
        print("-" * 70)

        try:
            answer, stats = run_agent(client, args.model, prompt, verbose=not args.quiet)
        except Exception as e:
            print(f"  ✗ FALLITO: {e}")
            total_failed += 1
            continue

        print(f"\n  📝 Risposta Claude:")
        for line in answer.strip().splitlines():
            print(f"     {line}")

        print(f"\n  📊 Metriche:")
        print(f"     Iterations:    {stats['iterations']}")
        print(f"     Tool calls:    {len(stats['tool_calls'])}")
        for call in stats['tool_calls']:
            print(f"       • {call['name']}({json.dumps(call['input'], ensure_ascii=False)})")
        print(f"     Tokens:        in={stats['input_tokens']}  out={stats['output_tokens']}")
        print(f"     Latency:       {stats['elapsed']:.2f}s")

        # Check: almeno un tool è stato chiamato
        if len(stats["tool_calls"]) > 0:
            print(f"  ✓ PASSED (Claude ha invocato {len(stats['tool_calls'])} tool)")
            total_passed += 1
        else:
            print(f"  ✗ FAIL: Claude non ha invocato nessun tool (ha risposto direttamente)")
            total_failed += 1

    print("\n" + "=" * 70)
    total = total_passed + total_failed
    print(f"  Risultato: {total_passed}/{total} scenari passati", end="")
    if total_failed:
        print(f"  ({total_failed} FALLITI)")
    else:
        print("  — TUTTO OK ✓")
    print("=" * 70 + "\n")

    sys.exit(0 if total_failed == 0 else 1)


if __name__ == "__main__":
    main()
