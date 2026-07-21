"""Registrazione degli invii del giorno nel master (fine mattina).

Legge le bozze `.eml` di un batch (cartella bozze/YYYYMMDD/), e per ciascuna:
  - appende una riga al foglio "Registro invii": Data invio, Email, Ente/dominio,
    Oggetto, Stato="Nessuna risposta", Variante (dall'header X-Prospecting-Variante);
  - se la bozza è un follow-up/ripresa (header X-Prospecting-Versione = F1/RIPRESA),
    aggiorna la col H "Ultimo invio" del contatto in "Follow-up e riprese" alla
    data di invio (fa avanzare da solo I/J/K via formule del master).

È il pezzo che alimenta il foglio Test A-B da solo.

Regole: backup prima di scrivere, dry-run di default (--apply per scrivere),
idempotente per coppia (email, data), mai colonne-formula (col I del Registro).
Le bozze NON inviate si escludono con --escludi (email separate da virgola, o un
file con un'email per riga).

Uso:
    python -m scripts.log_invii --config config.yaml                 # dry-run, batch di oggi
    python -m scripts.log_invii --config config.yaml --apply
    python -m scripts.log_invii --config config.yaml --bozze bozze/20260716 --apply
    python -m scripts.log_invii --config config.yaml --escludi a@x.it,b@y.it --apply
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime
from email import message_from_bytes
from email.header import decode_header, make_header
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

STATO_INIZIALE = "Nessuna risposta"


def _hdr(msg, name: str) -> str:
    raw = msg.get(name)
    if raw is None:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def _domain(email: str) -> str:
    return email.split("@")[-1].strip().lower() if "@" in email else ""


def _batch_date(bozze_dir: Path, fallback: date) -> date:
    """Deriva la data dal nome cartella YYYYMMDD, altrimenti usa il fallback."""
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", bozze_dir.name)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            pass
    return fallback


def parse_bozze(bozze_dir: Path) -> list[dict]:
    """Legge le .eml e ritorna [{email, oggetto, variante, versione, is_followup}]."""
    out = []
    for eml in sorted(bozze_dir.glob("*.eml")):
        msg = message_from_bytes(eml.read_bytes())
        to = _hdr(msg, "To").strip()
        email = re.search(r"[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}", to)
        email = email.group(0).lower() if email else to.lower()
        versione = _hdr(msg, "X-Prospecting-Versione")
        out.append({
            "file": eml.name,
            "email": email,
            "oggetto": _hdr(msg, "Subject"),
            "variante": _hdr(msg, "X-Prospecting-Variante").strip(),
            "versione": versione,
            "is_followup": versione.strip().upper().startswith(("F1", "F2", "F3", "RIPRESA")),
        })
    return out


def _col(headers: dict[str, int], *needles: str) -> int | None:
    for name, idx in headers.items():
        if any(n in name.lower() for n in needles):
            return idx
    return None


def _header_map(ws) -> dict[str, int]:
    return {str(ws.cell(1, c).value).strip(): c
            for c in range(1, ws.max_column + 1) if ws.cell(1, c).value}


def _existing_registro_keys(ws, col_email: int, col_data: int) -> set[tuple[str, str]]:
    """Coppie (email, YYYY-MM-DD) già presenti nel Registro (idempotenza)."""
    from common import followup

    keys = set()
    for r in range(2, ws.max_row + 1):
        email = str(ws.cell(r, col_email).value or "").strip().lower()
        d = followup._as_date(ws.cell(r, col_data).value)
        if email:
            keys.add((email, d.isoformat() if d else ""))
    return keys


def log_sends(master_path, bozze_dir, cfg, *, apply: bool,
              escludi: set[str] | None = None, today: date | None = None):
    from common import io_master as io

    escludi = {e.strip().lower() for e in (escludi or set()) if e.strip()}
    bozze_dir = Path(bozze_dir)
    today = today or date.today()
    data_invio = _batch_date(bozze_dir, today)

    log = io.RunLog(component="log_invii", apply=apply)
    if not bozze_dir.exists():
        log.notes.append(f"cartella bozze inesistente: {bozze_dir}")
        return {"logged": 0, "skipped": 0, "excluded": 0, "followup_updated": 0,
                "log": log, "rows": []}

    bozze = parse_bozze(bozze_dir)
    wb = io.load(master_path)
    reg = wb["Registro invii"]
    rh = _header_map(reg)
    c_data = _col(rh, "data invio", "data")
    c_email = _col(rh, "email")
    c_ente = _col(rh, "ente", "dominio")
    c_ogg = _col(rh, "oggetto")
    c_stato = _col(rh, "stato")
    c_var = _col(rh, "variante")

    existing = _existing_registro_keys(reg, c_email, c_data)

    # indice Follow-up per email (per aggiornare "Ultimo invio")
    fu_ws = wb["Follow-up e riprese"] if "Follow-up e riprese" in wb.sheetnames else None
    fu_email_col = fu_ultimo_col = None
    fu_rows_by_email: dict[str, list[int]] = {}
    if fu_ws is not None:
        fh = _header_map(fu_ws)
        fu_email_col = _col(fh, "email")
        fu_ultimo_col = _col(fh, "ultimo invio")
        if fu_email_col:
            for r in range(2, fu_ws.max_row + 1):
                em = str(fu_ws.cell(r, fu_email_col).value or "").strip().lower()
                if em:
                    fu_rows_by_email.setdefault(em, []).append(r)

    next_row = reg.max_row + 1
    logged = skipped = excluded = fu_updated = 0
    rows_report = []
    for b in bozze:
        email = b["email"]
        if not email:
            continue
        if email in escludi:
            excluded += 1
            continue
        key = (email, data_invio.isoformat())
        if key in existing:
            skipped += 1
            log.record_skip("Registro invii", email, f"già registrato per {data_invio}")
            continue

        reg.cell(next_row, c_data, datetime(data_invio.year, data_invio.month, data_invio.day))
        reg.cell(next_row, c_email, email)
        if c_ente:
            reg.cell(next_row, c_ente, _domain(email))
        if c_ogg:
            reg.cell(next_row, c_ogg, b["oggetto"])
        if c_stato:
            reg.cell(next_row, c_stato, STATO_INIZIALE)
        if c_var and b["variante"] and b["variante"] != "—":
            reg.cell(next_row, c_var, b["variante"])
        log.record_write("Registro invii", f"riga {next_row}", None, email)
        existing.add(key)
        next_row += 1
        logged += 1
        rows_report.append({**b, "data": data_invio.isoformat()})

        # follow-up/ripresa → aggiorna "Ultimo invio" (idempotente via set_cell)
        if b["is_followup"] and fu_ultimo_col and email in fu_rows_by_email:
            for r in fu_rows_by_email[email]:
                changed = io.set_cell(
                    fu_ws, r, fu_ultimo_col,
                    datetime(data_invio.year, data_invio.month, data_invio.day),
                    sheet_name="Follow-up e riprese", log=log)
                if changed:
                    fu_updated += 1

    io.save(wb, master_path, apply=apply,
            backup_dir=cfg.get("paths", {}).get("backup", "backup"), log=log)
    log.notes.append(
        f"data {data_invio} · registrate {logged} · saltate {skipped} · "
        f"escluse {excluded} · follow-up aggiornati {fu_updated}")
    log.save(cfg.get("paths", {}).get("logs", "logs"))
    return {"logged": logged, "skipped": skipped, "excluded": excluded,
            "followup_updated": fu_updated, "data": data_invio, "log": log,
            "rows": rows_report}


def _load_escludi(arg: str | None) -> set[str]:
    if not arg:
        return set()
    p = Path(arg)
    if p.exists():
        return {line.strip() for line in p.read_text().splitlines() if line.strip()}
    return {e.strip() for e in arg.split(",") if e.strip()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Registra gli invii del giorno (Fase 1.3)")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--bozze", default=None,
                    help="cartella bozze (default: bozze/YYYYMMDD di oggi)")
    ap.add_argument("--escludi", default=None,
                    help="email non inviate (virgole) o file con un'email per riga")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    import yaml

    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    bozze_dir = args.bozze or (
        Path(cfg.get("paths", {}).get("bozze", "bozze")) / f"{date.today():%Y%m%d}")
    res = log_sends(cfg["master_path"], bozze_dir, cfg, apply=args.apply,
                    escludi=_load_escludi(args.escludi))
    print(f"Bozze in {bozze_dir}: da registrare {res['logged']}, "
          f"già presenti {res['skipped']}, escluse {res['excluded']}, "
          f"follow-up aggiornati {res['followup_updated']}")
    for row in res["rows"]:
        print(f"  + {row['data']}  {row['email']:38s}  var={row['variante'] or '-':2s}  "
              f"{row['versione']}")
    if not args.apply:
        print("DRY-RUN: nessuna scrittura (usa --apply). Backup automatico all'apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
