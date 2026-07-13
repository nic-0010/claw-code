"""Componente A — scanner delle risposte (autonomia sui VECCHI contatti).

Classifica le risposte in arrivo e aggiorna il Registro invii da solo; segnala i
follow-up e le riprese maturati. Elimina il "passo 1" della mattina.

Input (fase 1): export CSV da Outlook con colonne
    tipo, data, mittente, destinatari, oggetto, anteprima, corpo_email, conversationId
(fase 2 Microsoft Graph: fuori scope, non blocca la fase 1).

Pipeline per ogni messaggio ricevuto legato a un nostro thread:
  1. DETERMINISTICO prima del modello:
     - NDR/bounce (postmaster@/mailer-daemon@, oggetti Undeliverable/Mancato
       recapito) → `Mancato recapito`
     - OOF (Automatic reply, Risposta automatica, "assente dal", ferie)
       → `Risposta automatica`
  2. Altrimenti OLLAMA LOCALE classifica il corpo in: positiva ·
     referente_indicato · rifiuto · auto_reply · altro. Output JSON:
     label, confidence, referente (nullable), sintesi_20_parole.
     PRIVACY: il corpo NON lascia mai la macchina (endpoint localhost).
  3. Scrittura (solo --apply, idempotente via common.io_master):
     E `Stato` · G `Risposta associata`="Sì" · H `Preview` (≤200 char) ·
     F append `[scanner GG/MM] …`. Colonne I (formula) e J (variante) MAI.
     confidence < 0.7 → niente scrittura, finisce nel report "DA RIVEDERE".
  4. Follow-up: NON ricalcola nulla — conta dalle formule del foglio quanti
     follow-up/riprese sono maturati oggi e li mette nel report.

Uso:
    python -m scanner.reply_scanner --config config.yaml            # dry-run
    python -m scanner.reply_scanner --config config.yaml --apply

Eval-first: vedi evals/eval_scanner.py (accuracy ≥90%, ZERO falsi positivi
sulla classe `positiva`). Schedule consigliato: APScheduler feriali 07:45.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# --------------------------------------------------------------------------
# Etichette e mapping verso i valori AMMESSI della colonna E `Stato`
# --------------------------------------------------------------------------
POSITIVA = "positiva"
REFERENTE = "referente_indicato"
RIFIUTO = "rifiuto"
AUTO_REPLY = "auto_reply"
BOUNCE = "bounce"
ALTRO = "altro"

LABELS = (POSITIVA, REFERENTE, RIFIUTO, AUTO_REPLY, ALTRO)

LABEL_TO_STATO = {
    POSITIVA: "Risposta positiva / referente",
    REFERENTE: "Risposta positiva / referente",
    RIFIUTO: "Rifiuto / non interessato",
    AUTO_REPLY: "Risposta automatica",
    BOUNCE: "Mancato recapito",
    # ALTRO: nessuna scrittura → report "DA RIVEDERE"
}

CONFIDENCE_THRESHOLD = 0.7

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


# --------------------------------------------------------------------------
# 1) Classificazione DETERMINISTICA (prima del modello)
# --------------------------------------------------------------------------
_BOUNCE_SENDERS = ("postmaster@", "mailer-daemon@", "mailerdaemon@", "noreply+bounces")
_BOUNCE_SUBJECTS = (
    "undeliverable", "undelivered", "delivery status notification",
    "delivery has failed", "mail delivery failed", "mancato recapito",
    "impossibile recapitare", "returned mail", "failure notice",
)
_OOF_SUBJECTS = (
    "automatic reply", "autoreply", "auto-reply", "risposta automatica",
    "out of office", "fuori sede", "fuori ufficio",
)
_OOF_BODY = (
    "assente dal", "sono assente", "sarò assente", "saro assente",
    "in ferie", "fuori sede", "out of office", "rientrerò", "rientrero",
    "i am out of the office", "i will be out",
)


def classify_deterministic(mittente: str, oggetto: str, corpo: str) -> str | None:
    """Ritorna BOUNCE/AUTO_REPLY se il messaggio è riconoscibile senza modello,
    altrimenti None (va al classificatore)."""
    m = (mittente or "").lower()
    o = (oggetto or "").lower()
    b = (corpo or "").lower()

    if any(m.startswith(p) or p in m for p in _BOUNCE_SENDERS):
        return BOUNCE
    if any(s in o for s in _BOUNCE_SUBJECTS):
        return BOUNCE
    if any(s in o for s in _OOF_SUBJECTS):
        return AUTO_REPLY
    if any(s in b[:600] for s in _OOF_BODY):
        return AUTO_REPLY
    return None


# --------------------------------------------------------------------------
# 2) Classificatori del corpo (Ollama locale + fallback euristico)
# --------------------------------------------------------------------------
class Classifier(Protocol):
    def classify(self, corpo: str) -> dict[str, Any]: ...


_OLLAMA_PROMPT = """Sei un classificatore di risposte email B2B (prospecting previdenziale).
Classifica il messaggio in UNA di queste etichette:
- positiva: interesse, disponibilità a sentirsi/vedersi, richiesta di dettagli
- referente_indicato: indica un'ALTRA persona a cui rivolgersi (estrai nome/email)
- rifiuto: non interessato. NB: "ho già un consulente" è un RIFIUTO, non altro.
- auto_reply: risposta automatica, assenza, ferie
- altro: tutto il resto (ambiguo, non pertinente)

Rispondi SOLO con JSON valido:
{"label": "...", "confidence": 0.0-1.0, "referente": {"nome": "...", "email": "..."} | null, "sintesi_20_parole": "..."}

MESSAGGIO:
"""


class OllamaClassifier:
    """Classificazione via Ollama LOCALE (http://localhost:11434). Il corpo
    email non lascia la macchina."""

    def __init__(self, model: str = "llama3.1", host: str = "http://localhost:11434",
                 timeout_s: int = 60):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout_s = timeout_s

    def classify(self, corpo: str) -> dict[str, Any]:
        import requests

        resp = requests.post(
            f"{self.host}/api/generate",
            json={
                "model": self.model,
                "prompt": _OLLAMA_PROMPT + (corpo or "")[:4000],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
            },
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        out = json.loads(resp.json().get("response", "{}"))
        return _sanitize_result(out, corpo)


# Euristiche ordinate: (label, confidence, pattern...). Servono come fallback
# quando Ollama non è disponibile e come baseline dell'eval.
_H_REFERENTE = (
    "può rivolgersi a", "puo rivolgersi a", "si rivolga a", "rivolgersi a",
    "le giro il contatto", "il collega che se ne occupa", "la persona giusta è",
    "la persona giusta e", "può contattare", "puo contattare", "contatti il collega",
    "se ne occupa", "giro la sua mail a", "inoltro al collega",
)
_H_RIFIUTO = (
    "ho già un consulente", "ho gia un consulente", "ho già il mio consulente",
    "non sono interessat", "non mi interessa", "non siamo interessat",
    "già seguito", "gia seguito", "già coperto", "gia coperto",
    "non è di mio interesse", "la ringrazio ma", "grazie ma non",
    "non desidero", "rimuovermi dalla lista", "non contattarmi",
)
_H_POSITIVA = (
    "va bene per", "perfetto per", "confermo l'appuntamento", "confermo la call",
    "mi interessa", "sono interessat", "volentieri", "sentiamoci",
    "mi può chiamare", "mi puo chiamare", "fissiamo", "possiamo sentirci",
    "mi mandi la sintesi", "mi invii pure", "sì, va bene", "si, va bene",
    "ci vediamo", "a che ora", "quando le va bene",
)


class HeuristicClassifier:
    """Fallback deterministico senza modello. Precedenza: referente > rifiuto >
    positiva (mai marcare positivo un messaggio che contiene un rifiuto)."""

    def classify(self, corpo: str) -> dict[str, Any]:
        b = (corpo or "").lower()

        def _hit(pats: tuple) -> bool:
            return any(p in b for p in pats)

        if _hit(_H_REFERENTE):
            emails = [e for e in _EMAIL_RE.findall(corpo or "")]
            ref = {"nome": "", "email": emails[0]} if emails else None
            return _sanitize_result(
                {"label": REFERENTE, "confidence": 0.85, "referente": ref,
                 "sintesi_20_parole": "Indica un referente interno a cui rivolgersi."},
                corpo,
            )
        if _hit(_H_RIFIUTO):
            return _sanitize_result(
                {"label": RIFIUTO, "confidence": 0.85, "referente": None,
                 "sintesi_20_parole": "Non interessato / già seguito da un consulente."},
                corpo,
            )
        if _hit(_H_POSITIVA):
            return _sanitize_result(
                {"label": POSITIVA, "confidence": 0.8, "referente": None,
                 "sintesi_20_parole": "Mostra interesse o disponibilità a sentirsi."},
                corpo,
            )
        return _sanitize_result(
            {"label": ALTRO, "confidence": 0.4, "referente": None,
             "sintesi_20_parole": "Contenuto ambiguo, da rivedere a mano."},
            corpo,
        )


def _sanitize_result(out: dict, corpo: str) -> dict[str, Any]:
    label = str(out.get("label", ALTRO)).strip().lower()
    if label not in LABELS:
        label = ALTRO
    try:
        conf = float(out.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = min(max(conf, 0.0), 1.0)
    ref = out.get("referente") or None
    if ref is not None and not isinstance(ref, dict):
        ref = None
    sintesi = str(out.get("sintesi_20_parole", ""))[:200]
    return {"label": label, "confidence": conf, "referente": ref, "sintesi": sintesi}


def make_classifier(kind: str = "auto") -> Classifier:
    """auto: prova Ollama locale, altrimenti fallback euristico."""
    if kind == "heuristic":
        return HeuristicClassifier()
    if kind == "ollama":
        return OllamaClassifier()
    # auto
    try:
        import requests

        requests.get("http://localhost:11434/api/tags", timeout=2).raise_for_status()
        return OllamaClassifier()
    except Exception:
        return HeuristicClassifier()


# --------------------------------------------------------------------------
# 3) Scansione + scrittura idempotente
# --------------------------------------------------------------------------
EXPORT_COLUMNS = ("tipo", "data", "mittente", "destinatari", "oggetto",
                  "anteprima", "corpo_email", "conversationId")


def load_export(csv_path: str | Path) -> list[dict]:
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def index_registro(rows: list[dict]) -> dict[str, dict]:
    """Indice email → ULTIMA riga del Registro per quel contatto."""
    idx: dict[str, dict] = {}
    for r in rows:
        email = str(r.get("Email") or "").strip().lower()
        if email:
            idx[email] = r        # le righe sono in ordine: l'ultima vince
    return idx


def link_message(msg: dict, reg_idx: dict[str, dict]) -> dict | None:
    """Lega un messaggio ricevuto alla riga del Registro.

    - mittente presente nel Registro → match diretto;
    - bounce (mittente postmaster/daemon): cerca gli indirizzi citati nel corpo
      e li confronta col Registro.
    """
    sender = str(msg.get("mittente") or "").strip().lower()
    if sender in reg_idx:
        return reg_idx[sender]
    corpo = (msg.get("corpo_email") or "") + " " + (msg.get("oggetto") or "")
    for e in _EMAIL_RE.findall(corpo):
        row = reg_idx.get(e.lower())
        if row is not None:
            return row
    return None


def scan(
    export_rows: list[dict],
    registro_rows: list[dict],
    classifier: Classifier,
) -> list[dict]:
    """Classifica i messaggi ricevuti legati ai nostri thread.

    Ritorna una lista di risultati:
      {registro_row, label, stato, confidence, preview, referente, sintesi, writable}
    """
    reg_idx = index_registro(registro_rows)
    results: list[dict] = []
    for msg in export_rows:
        if str(msg.get("tipo") or "").strip().lower() not in ("ricevuto", "received", "in"):
            continue
        row = link_message(msg, reg_idx)
        if row is None:
            continue

        mittente = msg.get("mittente", "")
        oggetto = msg.get("oggetto", "")
        corpo = msg.get("corpo_email") or msg.get("anteprima") or ""

        det = classify_deterministic(mittente, oggetto, corpo)
        if det is not None:
            label, conf, ref, sintesi = det, 1.0, None, ""
        else:
            out = classifier.classify(corpo)
            label, conf, ref, sintesi = (
                out["label"], out["confidence"], out["referente"], out["sintesi"]
            )

        stato = LABEL_TO_STATO.get(label)
        writable = stato is not None and conf >= CONFIDENCE_THRESHOLD
        results.append({
            "registro_row": row,
            "email": row.get("Email"),
            "label": label,
            "stato": stato,
            "confidence": conf,
            "preview": " ".join(corpo.split())[:200],
            "referente": ref,
            "sintesi": sintesi,
            "writable": writable,
        })
    return results


def apply_results(
    master_path: str | Path,
    results: list[dict],
    *,
    apply: bool,
    backup_dir: str | Path = "backup",
    logs_dir: str | Path = "logs",
) -> "Any":
    """Scrive i risultati nel Registro (solo writable). Idempotente, dry-run di
    default, backup + log JSON via common.io_master."""
    from common import io_master as io

    log = io.RunLog(component="reply_scanner", apply=apply)
    wb = io.load(master_path)
    ws = wb["Registro invii"]

    n_written = 0
    for res in results:
        if not res["writable"]:
            log.record_skip("Registro invii", f"riga {res['registro_row'].get('_row')}",
                            f"{res['label']} conf={res['confidence']:.2f} → DA RIVEDERE")
            continue
        r = res["registro_row"]["_row"]
        changed = False
        changed |= io.set_cell(ws, r, "E", res["stato"], log=log)
        changed |= io.set_cell(ws, r, "G", "Sì", log=log)
        changed |= io.set_cell(ws, r, "H", res["preview"], log=log)
        if changed:
            # F: append nota scanner (solo al primo passaggio → idempotente)
            note = f"[scanner {datetime.now():%d/%m}]"
            if res["referente"]:
                ref = res["referente"]
                note += f" referente: {ref.get('nome','')} {ref.get('email','')}".rstrip()
            elif res["sintesi"]:
                note += f" {res['sintesi']}"
            current = ws.cell(r, 6).value or ""
            if note not in str(current):
                new_f = (str(current).rstrip() + " " + note).strip()
                io.set_cell(ws, r, "F", new_f, log=log)
            n_written += 1
        # colonne I (formula) e J (variante) MAI toccate.

    io.save(wb, master_path, apply=apply, backup_dir=backup_dir, log=log)
    log.notes.append(f"messaggi classificati: {len(results)} · scritture: {n_written}")
    log.save(logs_dir)
    return log


# --------------------------------------------------------------------------
# 4) Follow-up maturati (sola LETTURA delle formule del foglio)
# --------------------------------------------------------------------------
def followup_summary(master_path: str | Path) -> dict[str, int]:
    """Conta follow-up e riprese maturati oggi leggendo `Tipo azione`
    (valori cache delle formule). Nessuna scrittura, nessun ricalcolo."""
    from common import io_master as io

    wb = io.load(master_path, data_only=True)
    counts = Counter()
    if "Follow-up e riprese" in wb.sheetnames:
        for r in io.read_rows(wb, "Follow-up e riprese"):
            tipo = str(r.get("Tipo azione") or "").strip()
            if tipo.startswith("Follow-up"):
                counts["follow_up"] += 1
            elif tipo.startswith("Ripresa"):
                counts["riprese"] += 1
    return {"follow_up": counts["follow_up"], "riprese": counts["riprese"]}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scanner risposte (Componente A)")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--apply", action="store_true", help="scrive davvero nel master")
    ap.add_argument("--classifier", choices=("auto", "ollama", "heuristic"),
                    default="auto")
    args = ap.parse_args(argv)

    import yaml
    from common import io_master as io
    from common.notify import notify

    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    master = cfg["master_path"]
    export_csv = cfg["outlook_export_csv"]
    paths = cfg.get("paths", {})

    export_rows = load_export(export_csv)
    registro_rows = io.read_rows(io.load(master, data_only=True), "Registro invii")
    classifier = make_classifier(args.classifier)

    results = scan(export_rows, registro_rows, classifier)
    log = apply_results(
        master, results, apply=args.apply,
        backup_dir=paths.get("backup", "backup"),
        logs_dir=paths.get("logs", "logs"),
    )

    by_label = Counter(r["label"] for r in results)
    da_rivedere = sum(1 for r in results if not r["writable"])
    fu = followup_summary(master)
    report = (
        f"{len(results)} risposte: {by_label.get(POSITIVA,0)+by_label.get(REFERENTE,0)} positive, "
        f"{by_label.get(REFERENTE,0)} referral, {by_label.get(BOUNCE,0)} rimbalzi, "
        f"{da_rivedere} da rivedere · follow-up maturi oggi: {fu['follow_up']} · "
        f"riprese: {fu['riprese']}"
    )
    print(report)
    if not args.apply:
        print("DRY-RUN: nessuna scrittura (usa --apply).")
    notify("Reply scanner", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
