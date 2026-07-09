"""Eval del verificatore email (Componente C) — eval-first, prima del deploy.

Costruisci `evals/emails_labeled.csv` a verità nota (spec § Eval del verificatore):
  (a) i 139 rimbalzi reali del Registro/Risposte-e-rimbalzi → label `inesistente`;
  (b) un campione di indirizzi che hanno RICEVUTO risposta umana → label `valido`;
  (c) alcuni accept_all ambigui, etichettati a mano dopo verifica.

Il file reale NON va committato (contiene PII): vedi emails_labeled.example.csv
per il formato. Colonne:
  nome,email,verification,mx,smtp,label
    - verification: valid | accept_all   (come nel master)
    - mx:  si | no | nd                  (esito MX simulato/registrato)
    - smtp: ok | inesistente | sconosciuto | (vuoto = non testato)
    - label: inesistente | valido        (verità nota)

Soglie di deploy:
  - precision sulla classe "inesistente" ≥ 0.95  (mai bocciare un indirizzo buono)
  - recall sui rimbalzi noti           ≥ 0.70
Sotto soglia → iterare le euristiche, NON deployare.

Uso:
    python -m evals.eval_verifier [--csv evals/emails_labeled.csv]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from verifier.email_verifier import (  # noqa: E402
    RISCHIO_ALTO,
    infer_domain_patterns,
    score_address,
)

PREC_THRESHOLD = 0.95
RECALL_THRESHOLD = 0.70

_MX = {"si": True, "sì": True, "no": False, "nd": None, "": None}


def _predicted_inesistente(score: str) -> bool:
    """Il verificatore 'boccia' un indirizzo quando lo marca RISCHIO ALTO."""
    return score == RISCHIO_ALTO


def evaluate(rows: list[dict]) -> dict:
    valids = [
        (r["nome"], r["email"])
        for r in rows
        if (r.get("verification") or "").lower() == "valid"
    ]
    dom_patterns = infer_domain_patterns(valids, min_examples=3)

    tp = fp = fn = tn = 0
    errors = []
    for r in rows:
        dom = r["email"].split("@")[-1].lower()
        dp = dom_patterns.get(dom)
        mx = _MX.get((r.get("mx") or "").strip().lower(), None)
        smtp = (r.get("smtp") or "").strip().lower() or None
        score, _sug = score_address(
            r["nome"], r["email"], r.get("verification", ""), dp, mx, smtp
        )
        pred_bad = _predicted_inesistente(score)
        truth_bad = (r.get("label") or "").strip().lower() == "inesistente"

        if pred_bad and truth_bad:
            tp += 1
        elif pred_bad and not truth_bad:
            fp += 1
            errors.append(("FALSO POSITIVO (lead buono perso!)", r["email"], score))
        elif not pred_bad and truth_bad:
            fn += 1
            errors.append(("FALSO NEGATIVO (rimbalzo non colto)", r["email"], score))
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return {
        "n": len(rows),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision_inesistente": round(precision, 3),
        "recall_inesistente": round(recall, 3),
        "errors": errors,
        "pass": precision >= PREC_THRESHOLD and recall >= RECALL_THRESHOLD,
    }


def load_csv(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    default_csv = Path(__file__).resolve().parent / "emails_labeled.csv"
    if not default_csv.exists():
        default_csv = Path(__file__).resolve().parent / "emails_labeled.example.csv"
    ap.add_argument("--csv", default=str(default_csv))
    args = ap.parse_args(argv)

    rows = load_csv(args.csv)
    res = evaluate(rows)
    print(f"Eval verificatore su {res['n']} indirizzi ({args.csv})")
    print(f"  TP={res['tp']} FP={res['fp']} FN={res['fn']} TN={res['tn']}")
    print(f"  precision(inesistente) = {res['precision_inesistente']}  (soglia ≥ {PREC_THRESHOLD})")
    print(f"  recall(inesistente)    = {res['recall_inesistente']}  (soglia ≥ {RECALL_THRESHOLD})")
    if res["errors"]:
        print("  Errori:")
        for kind, email, score in res["errors"]:
            print(f"    - {kind}: {email} → {score}")
    print("  ESITO:", "PASS ✅" if res["pass"] else "SOTTO SOGLIA ❌ (iterare, non deployare)")
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
