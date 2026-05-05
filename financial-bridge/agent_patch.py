"""
Patch per agent.py e web_app.py.
Mostra le modifiche da applicare: modello Haiku, tool paralleli, streaming SSE.
"""

# ═══════════════════════════════════════════════════════════════════════════════
# 1. CAMBIO MODELLO — agent.py e web_app.py
# ═══════════════════════════════════════════════════════════════════════════════

# PRIMA:
MODEL = "claude-opus-4-5"

# DOPO:
MODEL = "claude-haiku-4-5-20251001"
# Alternativa se vuoi più ragionamento: "claude-sonnet-4-6"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TOOL PARALLELI — da usare in agent.py e web_app.py
#    Sostituisce il loop sequenziale di esecuzione tool
# ═══════════════════════════════════════════════════════════════════════════════

from concurrent.futures import ThreadPoolExecutor, as_completed
import json

def execute_tools_parallel(tool_calls: list, tool_map: dict) -> list:
    """
    Esegue più tool in parallelo quando Claude li richiede nello stesso turno.

    Args:
        tool_calls: lista di tool_use blocks da Claude (stop_reason == "tool_use")
        tool_map:   dict {tool_name: callable} con i tuoi tool registrati

    Returns:
        lista di tool_result da passare nel messaggio successivo
    """
    results = {}

    with ThreadPoolExecutor(max_workers=min(len(tool_calls), 8)) as pool:
        future_to_id = {}
        for tc in tool_calls:
            fn = tool_map.get(tc.name)
            if fn:
                future = pool.submit(fn, **tc.input)
                future_to_id[future] = tc.id
            else:
                results[tc.id] = f"Tool '{tc.name}' non trovato"

        for future in as_completed(future_to_id):
            tool_id = future_to_id[future]
            try:
                results[tool_id] = str(future.result())
            except Exception as e:
                results[tool_id] = f"Errore: {e}"

    return [
        {"type": "tool_result", "tool_use_id": tool_id, "content": content}
        for tool_id, content in results.items()
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. STREAMING SSE REALE — web_app.py
#    Sostituisce client.messages.create() con client.messages.stream()
# ═══════════════════════════════════════════════════════════════════════════════

import anthropic


def stream_agent_response(client: anthropic.Anthropic, messages: list, tools: list):
    """
    Generator che emette chunk SSE mentre Claude risponde.
    Usalo in una Flask route con stream=True.

    Yield format:
        data: {"type": "chunk", "text": "..."}   ← testo progressivo
        data: {"type": "tool", "name": "..."}     ← Claude usa un tool
        data: {"type": "done"}                    ← fine risposta
    """
    import json

    while True:
        tool_calls_in_turn = []
        full_text = ""

        with client.messages.stream(
            model=MODEL,
            max_tokens=4096,
            messages=messages,
            tools=tools,
        ) as stream:
            for event in stream:
                # Testo progressivo
                if event.type == "content_block_delta":
                    if hasattr(event.delta, "text"):
                        chunk = event.delta.text
                        full_text += chunk
                        yield f"data: {json.dumps({'type': 'chunk', 'text': chunk})}\n\n"

                # Tool richiesto
                elif event.type == "content_block_stop":
                    if hasattr(event, "content_block") and event.content_block.type == "tool_use":
                        tc = event.content_block
                        tool_calls_in_turn.append(tc)
                        yield f"data: {json.dumps({'type': 'tool', 'name': tc.name})}\n\n"

            final_message = stream.get_final_message()

        # Nessun tool → fine
        if final_message.stop_reason != "tool_use" or not tool_calls_in_turn:
            break

        # Esegui tool in parallelo e continua il loop
        messages.append({"role": "assistant", "content": final_message.content})
        tool_results = execute_tools_parallel(tool_calls_in_turn, TOOL_MAP)
        messages.append({"role": "user", "content": tool_results})

    yield f"data: {json.dumps({'type': 'done'})}\n\n"
