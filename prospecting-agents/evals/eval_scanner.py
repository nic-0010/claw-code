"""Eval del reply scanner (Componente A) — eval-first, prima del deploy.

Set: `evals/replies_labeled.jsonl` (dai 14 casi reali di `Risposte e rimbalzi`
+ ~40 risposte dagli export storici, etichettate a mano). Il file reale NON va
committato (PII): vedi replies_labeled.example.jsonl per il formato.

Formato JSONL, un oggetto per riga:
  {"mittente": "...", "oggetto": "...", "corpo": "...",
   "label": "positiva|referente_indicato|rifiuto|auto_reply|bounce|altro"}

Soglie di deploy:
  - accuracy ≥ 0.90
  - ZERO falsi positivi sulla classe `positiva` (un rifiuto marcato positivo è
    il danno peggiore)
Sotto soglia → iterare, NON deployare.

Uso:
    python -m evals.eval_scanner [--jsonl evals/replies_labeled.jsonl]
                                 [--classifier auto|ollama|heuristic]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner.reply_scanner import (  # noqa: E402
    POSITIVA,
    REFERENTE,
    classify_deterministic,
    make_classifier,
)

ACC_THRESHOLD = 0.90


def classify_one(classifier, mittente: str, oggetto: str, corpo: str) -> str:
    det = classify_deterministic(mittente, oggetto, corpo)
    if det is not None:
        return det
    return classifier.classify(corpo)["label"]


def evaluate(rows: list[dict], classifier) -> dict:
    correct = 0
    fp_positiva = []
    errors = []
    for r in rows:
        pred = classify_one(classifier, r.get("mittente", ""), r.get("oggetto", ""),
                            r.get("corpo", ""))
        truth = r["label"]
        # positiva e referente_indicato mappano sullo stesso Stato del Registro:
        # ai fini del danno operativo le trattiamo come stessa macro-classe.
        macro = {REFERENTE: POSITIVA}
        ok = pred == truth or macro.get(pred, pred) == macro.get(truth, truth)
        if ok:
            correct += 1
        else:
            errors.append((truth, pred, (r.get("corpo") or "")[:60]))
            if macro.get(pred, pred) == POSITIVA and macro.get(truth, truth) != POSITIVA:
                fp_positiva.append((truth, pred, (r.get("corpo") or "")[:60]))

    n = len(rows)
    acc = correct / n if n else 0.0
    return {
        "n": n,
        "accuracy": round(acc, 3),
        "fp_positiva": fp_positiva,
        "errors": errors,
        "pass": acc >= ACC_THRESHOLD and not fp_positiva,
    }


def load_jsonl(path: str | Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    default = Path(__file__).resolve().parent / "replies_labeled.jsonl"
    if not default.exists():
        default = Path(__file__).resolve().parent / "replies_labeled.example.jsonl"
    ap.add_argument("--jsonl", default=str(default))
    ap.add_argument("--classifier", choices=("auto", "ollama", "heuristic"),
                    default="auto")
    args = ap.parse_args(argv)

    rows = load_jsonl(args.jsonl)
    res = evaluate(rows, make_classifier(args.classifier))
    print(f"Eval scanner su {res['n']} messaggi ({args.jsonl})")
    print(f"  accuracy = {res['accuracy']}  (soglia ≥ {ACC_THRESHOLD})")
    print(f"  falsi positivi 'positiva' = {len(res['fp_positiva'])}  (soglia = 0)")
    if res["errors"]:
        print("  Errori:")
        for truth, pred, snippet in res["errors"]:
            print(f"    - atteso={truth} predetto={pred}: {snippet!r}")
    print("  ESITO:", "PASS ✅" if res["pass"] else "SOTTO SOGLIA ❌ (iterare, non deployare)")
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
