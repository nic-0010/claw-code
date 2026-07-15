"""Riallinea le colonne dorate R/S (Oggetto V4 / Corpo V4) del master alla
Matrice V4 corrente.

Le colonne R/S di ogni foglio `Coda invii*` possono contenere testo stale
(riempito una tantum da uno script vecchio o prima di una modifica alla
matrice). Il queue builder genera comunque la variante C al volo da
common.email_matrix.build_email(), quindi le mail reali sono già corrette; questo
script serve SOLO a far combaciare anche il file Excel con quelle mail.

Per ogni riga con Nome/Azienda/Ruolo valorizzati richiama build_email() (passando
l'Email per la disambiguazione del saluto) e riscrive:
  - R `Oggetto V4 (ruolo×società)`  = subject
  - S `Corpo V4 (ruolo×società)`     = body
  - N `Versione (V4 matrice)`         = tag   (se la colonna esiste)

Regole trasversali: backup prima di ogni scrittura, dry-run di default, --apply
per scrivere davvero, mai scritture su colonne-formula (via common.io_master),
log JSON del run.

Uso:
    python -m scripts.rigenera_colonne_v4 --config config.yaml            # dry-run
    python -m scripts.rigenera_colonne_v4 --config config.yaml --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import email_matrix  # noqa: E402


def _find_col(headers: dict[str, int], *needles: str) -> int | None:
    """Trova la colonna la cui intestazione contiene uno dei needle (case-insensitive)."""
    for name, idx in headers.items():
        low = name.lower()
        if any(n in low for n in needles):
            return idx
    return None


def rigenera(master_path: str | Path, cfg: dict, *, apply: bool):
    """Riscrive R/S (e N) di tutti i fogli `Coda invii*`. Ritorna il RunLog."""
    from common import io_master as io

    log = io.RunLog(component="rigenera_colonne_v4", apply=apply)
    wb = io.load(master_path)

    for sheet in wb.sheetnames:
        if not sheet.startswith("Coda invii"):
            continue
        ws = wb[sheet]
        headers = {str(ws.cell(1, c).value).strip(): c
                   for c in range(1, ws.max_column + 1) if ws.cell(1, c).value}

        col_nome = _find_col(headers, "nome")
        col_az = _find_col(headers, "azienda")
        col_ruolo = _find_col(headers, "ruolo")
        col_email = _find_col(headers, "email")
        col_ogg = _find_col(headers, "oggetto v4")
        col_corpo = _find_col(headers, "corpo v4")
        col_ver = _find_col(headers, "versione")

        if not (col_nome and col_az and col_ruolo and col_ogg and col_corpo):
            log.notes.append(f"{sheet!r}: colonne V4 non trovate, saltato")
            continue

        for r in range(2, ws.max_row + 1):
            nome = ws.cell(r, col_nome).value
            azienda = ws.cell(r, col_az).value
            ruolo = ws.cell(r, col_ruolo).value
            if not (nome and azienda and ruolo):
                continue
            email = ws.cell(r, col_email).value if col_email else None
            subject, body, tag = email_matrix.build_email(
                str(nome), str(azienda), str(ruolo), email=email)
            io.set_cell(ws, r, col_ogg, subject, sheet_name=sheet, log=log)
            io.set_cell(ws, r, col_corpo, body, sheet_name=sheet, log=log)
            if col_ver:
                io.set_cell(ws, r, col_ver, tag, sheet_name=sheet, log=log)

    io.save(wb, master_path, apply=apply,
            backup_dir=cfg.get("paths", {}).get("backup", "backup"), log=log)
    log.save(cfg.get("paths", {}).get("logs", "logs"))
    return log


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Riallinea le colonne R/S V4 del master")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--apply", action="store_true", help="scrive davvero (default: dry-run)")
    args = ap.parse_args(argv)

    import yaml

    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    log = rigenera(cfg["master_path"], cfg, apply=args.apply)
    fogli = {w["sheet"] for w in log.writes}
    print(f"Colonne R/S da aggiornare: {len(log.writes)} celle su {len(fogli)} fogli")
    for note in log.notes:
        print(f"  · {note}")
    if not args.apply:
        print("DRY-RUN: nessuna scrittura (usa --apply). Backup automatico all'apply.")
    else:
        print(f"Scritto. Backup: {log.backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
