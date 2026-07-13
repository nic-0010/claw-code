"""Rifornimento di `Nuovi contatti` dall'archivio lead (Componente B, punto 2).

Quando `Nuovi contatti` scende sotto soglia, importa dall'archivio lead
(config `lead_archive`), applica un punteggio, deduplica TOTALMENTE contro
Registro, Non riscrivere, tutte le code e Follow-up, e appende i migliori N.
Append-only + backup + report (via common.io_master). Dry-run di default.

Uso:
    python -m queue.lead_refill --config config.yaml [--apply] [--top 100]
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def existing_identities(wb) -> tuple[set[str], set[tuple[str, str]]]:
    """Tutte le email e le coppie (nome, azienda) già presenti nel master:
    Registro, Non riscrivere, code, Follow-up, Nuovi contatti."""
    from common import io_master as io

    emails: set[str] = set()
    pairs: set[tuple[str, str]] = set()

    def collect(sheet: str, email_col: str, nome_col: str, az_col: str):
        if sheet not in wb.sheetnames:
            return
        for r in io.read_rows(wb, sheet):
            e = _norm(r.get(email_col))
            if e and "@" in e:
                emails.add(e)
            key = (_norm(r.get(nome_col)), _norm(r.get(az_col)))
            if key[0] or key[1]:
                pairs.add(key)

    collect("Registro invii", "Email", "Email", "Ente/dominio")
    collect("Non riscrivere", "Email", "Nome", "Azienda")
    collect("Follow-up e riprese", "Email", "Nome", "Azienda")
    collect("Nuovi contatti", "Email", "Nome", "Azienda")
    for s in wb.sheetnames:
        if s.startswith("Coda invii"):
            collect(s, "Email", "Nome", "Azienda")
    return emails, pairs


def score_lead(lead: dict, scoring_rules: dict | None = None) -> int:
    """Punteggio semplice e trasparente (sostituibile con le `Regole scoring`
    del master via config)."""
    rules = scoring_rules or {}
    score = int(lead.get("Score") or 0)
    if not score:
        ruolo = _norm(lead.get("Ruolo"))
        for needle, pts in (rules.get("ruolo") or {
            "director general": 150, "ceo": 150, "direttore": 120,
            "head of": 110, "dirigente": 110, "responsabile": 90,
            "manager": 80, "officer": 70,
        }).items():
            if needle in ruolo:
                score = max(score, pts)
        if _norm(lead.get("Verification")) == "valid":
            score += 20
    return score


def refill(master_path: str | Path, archive_path: str | Path, cfg: dict,
           *, apply: bool, top_n: int = 100) -> dict:
    """Importa i migliori `top_n` lead nuovi dall'archivio in `Nuovi contatti`
    (append-only). Ritorna un report."""
    from common import io_master as io

    log = io.RunLog(component="lead_refill", apply=apply)
    wb = io.load(master_path)
    if "Nuovi contatti" not in wb.sheetnames:
        raise ValueError("Foglio 'Nuovi contatti' assente nel master")

    emails, pairs = existing_identities(wb)

    arch = io.load(archive_path, data_only=True)
    sheet = arch.sheetnames[0]
    candidates = []
    for r in io.read_rows(arch, sheet):
        email = _norm(r.get("Email"))
        if not email or "@" not in email:
            continue
        key = (_norm(r.get("Nome")), _norm(r.get("Azienda")))
        if email in emails or key in pairs:
            log.record_skip(sheet, f"riga {r['_row']}", f"duplicato: {email}")
            continue
        r["_score"] = score_lead(r, cfg.get("scoring"))
        candidates.append(r)

    candidates.sort(key=lambda r: -r["_score"])
    take = candidates[:top_n]

    ws = wb["Nuovi contatti"]
    next_row = ws.max_row + 1
    for r in take:
        ws.cell(next_row, 1, r["_score"])                    # A Score
        ws.cell(next_row, 2, "NUOVO CONTATTO")               # B Azione
        ws.cell(next_row, 3, r.get("Segmento") or "")        # C
        ws.cell(next_row, 4, r.get("Persona") or "")         # D
        ws.cell(next_row, 5, r.get("Nome") or "")            # E
        ws.cell(next_row, 6, r.get("Azienda") or "")         # F
        ws.cell(next_row, 7, r.get("Ruolo") or "")           # G
        ws.cell(next_row, 8, r.get("Dipartimento") or "")    # H
        ws.cell(next_row, 9, r.get("Città") or r.get("Citta") or "")  # I
        ws.cell(next_row, 10, r.get("Email") or "")          # J
        ws.cell(next_row, 11, r.get("Verification") or "")   # K
        ws.cell(next_row, 12, r.get("Confidence") or "")     # L
        log.record_write("Nuovi contatti", f"riga {next_row}", None,
                         r.get("Email"))
        next_row += 1

    io.save(wb, master_path, apply=apply,
            backup_dir=cfg.get("paths", {}).get("backup", "backup"), log=log)
    log.notes.append(f"candidati: {len(candidates)} · appesi: {len(take)}")
    log.save(cfg.get("paths", {}).get("logs", "logs"))
    return {"appended": len(take), "candidates": len(candidates), "log": log}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lead refill (Componente B)")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--top", type=int, default=100)
    args = ap.parse_args(argv)

    import yaml

    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    rep = refill(cfg["master_path"], cfg["lead_archive"], cfg,
                 apply=args.apply, top_n=args.top)
    print(f"Lead refill: {rep['appended']} appesi su {rep['candidates']} candidati"
          + ("" if args.apply else " [DRY-RUN]"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
