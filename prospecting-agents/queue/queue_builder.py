"""Componente B — queue builder (autonomia + resa sui NUOVI contatti).

Alle 08:00 le bozze del giorno sono pronte (incluse le V4) e la coda non
finisce mai. L'umano rilegge e invia — NESSUN componente invia email, mai.

Batch del giorno:
  - 12 fredde: dai fogli `Coda invii*` in ordine (Stato=Da inviare, ordine
    riga); esaurite le code, da `Nuovi contatti` (Verification=valid, Score
    desc, saltando Nota valorizzata e i domini_congelati).
  - Split test A/B/C: 4+4+4. A = `Corpo mail` (col Q); B = oggetto/corpo v2 dai
    Template; C = generato al volo con common.email_matrix.build_email().
  - 10 follow-up + 5 riprese da `Follow-up e riprese` per `Tipo azione`,
    Score desc, template F1 / RIPRESA.
  - Cap: max 30 totali · max 3 accept_all · max 8 stesso dominio/giorno.
  - Esclusioni dure: `Non riscrivere` (Nome+Azienda) o Registro con
    Stato ≠ `Nessuna risposta`.

Auto-rifornimento (mai a secco): valid non accodati < soglia_scorta → genera un
nuovo foglio `Coda invii dal GG-MM` con R/S V4 già compilate e flag Nota sui
contatti presi (UNICHE scritture ammesse: append-only + backup).

Render: [Cognome]=ultima parola del Nome, [Ente]=Azienda, [Nome], [mese];
segnaposto irrisolti → ⟦…⟧ così saltano all'occhio.

Output: bozze/YYYYMMDD/*.eml (RFC 822) + riepilogo.html. Su macOS,
--outlook-drafts crea bozze in Outlook via AppleScript (MAI invia).

Uso:
    python -m queue.queue_builder --config config.yaml            # dry-run
    python -m queue.queue_builder --config config.yaml --apply    # abilita refill
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import email_matrix  # noqa: E402

MESI_IT = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
           "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre")


# --------------------------------------------------------------------------
# Render dei segnaposto
# --------------------------------------------------------------------------
_PLACEHOLDER_RE = re.compile(r"\[([^\[\]]+)\]")


def render_placeholders(text: str, nome: str, azienda: str,
                        today: datetime | None = None) -> str:
    """Sostituisce i segnaposto noti; quelli irrisolti diventano ⟦…⟧."""
    today = today or datetime.now()
    cognome = nome.strip().split()[-1] if nome and nome.strip() else ""
    values = {
        "Cognome": cognome,
        "Nome": nome or "",
        "Ente": azienda or "",
        "mese": MESI_IT[today.month - 1],
    }

    def repl(m: re.Match) -> str:
        key = m.group(1)
        v = values.get(key)
        if v:
            return v
        return f"⟦{key}⟧"

    return _PLACEHOLDER_RE.sub(repl, text or "")


# --------------------------------------------------------------------------
# Normalizzazione per match Nome+Azienda (Non riscrivere)
# --------------------------------------------------------------------------
def _norm_key(nome: str | None, azienda: str | None) -> tuple[str, str]:
    def n(s):
        s = unicodedata.normalize("NFKD", str(s or ""))
        s = "".join(c for c in s if not unicodedata.combining(c))
        return " ".join(s.lower().split())
    return n(nome), n(azienda)


def _domain(email: str | None) -> str:
    e = str(email or "")
    return e.split("@")[-1].strip().lower() if "@" in e else ""


# --------------------------------------------------------------------------
# Esclusioni dure
# --------------------------------------------------------------------------
def build_exclusions(wb) -> tuple[set[tuple[str, str]], set[str]]:
    """Ritorna (set Nome+Azienda da Non riscrivere,
                set email dal Registro con Stato ≠ Nessuna risposta)."""
    from common import io_master as io

    non_riscrivere: set[tuple[str, str]] = set()
    if "Non riscrivere" in wb.sheetnames:
        for r in io.read_rows(wb, "Non riscrivere"):
            key = _norm_key(r.get("Nome"), r.get("Azienda"))
            if key[0] or key[1]:
                non_riscrivere.add(key)

    stato_email: set[str] = set()
    if "Registro invii" in wb.sheetnames:
        for r in io.read_rows(wb, "Registro invii"):
            email = str(r.get("Email") or "").strip().lower()
            stato = str(r.get("Stato") or "").strip()
            if email and stato and stato != "Nessuna risposta":
                stato_email.add(email)
    return non_riscrivere, stato_email


def is_excluded(contact: dict, non_riscrivere: set, stato_email: set,
                domini_congelati: set[str]) -> bool:
    email = str(contact.get("email") or "").strip().lower()
    if email in stato_email:
        return True
    if _domain(email) in domini_congelati:
        return True
    if _norm_key(contact.get("nome"), contact.get("azienda")) in non_riscrivere:
        return True
    return False


# --------------------------------------------------------------------------
# Template dalla libreria (foglio Template)
# --------------------------------------------------------------------------
def load_templates(wb) -> list[dict]:
    from common import io_master as io

    if "Template" not in wb.sheetnames:
        return []
    out = []
    ws = wb["Template"]
    # il foglio ha righe di intestazione libere: cerchiamo le righe con
    # Template+Corpo valorizzati
    for r in range(1, ws.max_row + 1):
        t, o, c = ws.cell(r, 1).value, ws.cell(r, 2).value, ws.cell(r, 3).value
        if t and c and str(c).strip():
            out.append({"nome": str(t).strip(), "oggetto": str(o or "").strip(),
                        "corpo": str(c).strip()})
    return out


def pick_template(templates: list[dict], prefix: str, segmento: str = "") -> dict | None:
    """Sceglie il template la cui riga inizia con `prefix`; a parità, quello
    che matcha meglio il segmento."""
    candidates = [t for t in templates if t["nome"].startswith(prefix)]
    if not candidates:
        return None
    if segmento:
        seg = segmento.lower()
        seg_words = [w for w in re.split(r"[ /]+", seg) if len(w) > 2]
        for t in candidates:
            name = t["nome"].lower()
            if any(w in name for w in seg_words):
                return t
    return candidates[0]


# --------------------------------------------------------------------------
# Selezione del batch
# --------------------------------------------------------------------------
def select_batch(wb, cfg: dict, today: datetime | None = None) -> list[dict]:
    """Costruisce il batch del giorno (lista di bozze pronte al render).

    Ogni elemento: {tipo, variante, nome, azienda, ruolo, email, segmento,
                    oggetto, corpo, versione, fonte}
    NON scrive nulla sul master.
    """
    from common import io_master as io

    caps = cfg.get("caps", {})
    cap_tot = caps.get("totale", 30)
    cap_fredde = caps.get("fredde", 12)
    cap_fu = caps.get("follow_up", 10)
    cap_rip = caps.get("riprese", 5)
    cap_accept = caps.get("accept_all", 3)
    cap_domain = caps.get("stesso_dominio", 8)
    domini_congelati = set(cfg.get("domini_congelati") or [])

    non_riscrivere, stato_email = build_exclusions(wb)
    templates = load_templates(wb)

    batch: list[dict] = []
    seen_emails: set[str] = set()
    domain_count: Counter = Counter()
    accept_count = 0

    def try_add(item: dict, verifica: str = "") -> bool:
        nonlocal accept_count
        email = str(item.get("email") or "").strip().lower()
        if not email or email in seen_emails:
            return False
        if len(batch) >= cap_tot:
            return False
        if is_excluded(item, non_riscrivere, stato_email, domini_congelati):
            return False
        dom = _domain(email)
        if domain_count[dom] >= cap_domain:
            return False
        if (verifica or "").lower() == "accept_all":
            if accept_count >= cap_accept:
                return False
            accept_count += 1
        seen_emails.add(email)
        domain_count[dom] += 1
        batch.append(item)
        return True

    # ---- 1) fredde dalle code, in ordine ---------------------------------
    fredde: list[dict] = []
    coda_sheets = [s for s in wb.sheetnames if s.startswith("Coda invii")]
    for sheet in coda_sheets:
        if len(fredde) >= cap_fredde:
            break
        for r in io.read_rows(wb, sheet):
            if len(fredde) >= cap_fredde:
                break
            if str(r.get("Stato") or "").strip() != "Da inviare":
                continue
            item = {
                "tipo": "fredda",
                "fonte": sheet,
                "nome": r.get("Nome") or "",
                "azienda": r.get("Azienda") or "",
                "ruolo": r.get("Ruolo") or "",
                "email": r.get("Email") or "",
                "segmento": r.get("Segmento") or "",
                "oggetto_coda": r.get("Oggetto da usare") or "",
                "corpo_A": r.get("Corpo mail") or "",
                "oggetto_v4": r.get("Oggetto V4 (ruolo×società)") or "",
                "corpo_v4": r.get("Corpo V4 (ruolo×società)") or "",
                "verifica": r.get("Verifica") or "",
            }
            if try_add(item, item["verifica"]):
                fredde.append(item)

    # esaurite le code → Nuovi contatti (valid, Score desc, Nota vuota)
    if len(fredde) < cap_fredde and "Nuovi contatti" in wb.sheetnames:
        rows = [r for r in io.read_rows(wb, "Nuovi contatti")
                if str(r.get("Verification") or "").lower() == "valid"
                and not str(r.get("Nota") or "").strip()]
        rows.sort(key=lambda r: -(r.get("Score") or 0))
        for r in rows:
            if len(fredde) >= cap_fredde:
                break
            item = {
                "tipo": "fredda", "fonte": "Nuovi contatti",
                "nome": r.get("Nome") or "", "azienda": r.get("Azienda") or "",
                "ruolo": r.get("Ruolo") or "", "email": r.get("Email") or "",
                "segmento": r.get("Segmento") or "",
                "oggetto_coda": "", "corpo_A": "",
                "oggetto_v4": "", "corpo_v4": "", "verifica": "valid",
            }
            if try_add(item, "valid"):
                fredde.append(item)

    # ---- split A/B/C sulle fredde (round-robin 4+4+4) ---------------------
    per_var = max(len(fredde) // 3, 1) if fredde else 0
    for i, item in enumerate(fredde):
        variante = "ABC"[min(i // per_var, 2)] if per_var else "A"
        item["variante"] = variante
        if variante == "A":
            corpo = item["corpo_A"]
            oggetto = item["oggetto_coda"]
            if not corpo:
                t = pick_template(templates, "A · CONTROLLO", item["segmento"])
                corpo = t["corpo"] if t else ""
                oggetto = oggetto or (t["oggetto"] if t else "")
            item["oggetto"], item["corpo"] = oggetto, corpo
            item["versione"] = "A"
        elif variante == "B":
            t = pick_template(templates, "B · CHALLENGER V2", item["segmento"])
            item["oggetto"] = t["oggetto"] if t else item["oggetto_coda"]
            item["corpo"] = t["corpo"] if t else ""
            item["versione"] = "B"
        else:  # C → Matrice V4 al volo
            if item["corpo_v4"] and item["oggetto_v4"]:
                item["oggetto"], item["corpo"] = item["oggetto_v4"], item["corpo_v4"]
                tag = ""
            else:
                s, b, tag = email_matrix.build_email(
                    item["nome"], item["azienda"], item["ruolo"])
                item["oggetto"], item["corpo"] = s, b
            item["versione"] = f"C ({tag})" if tag else "C (V4)"

    # ---- 2) follow-up + riprese -------------------------------------------
    if "Follow-up e riprese" in wb.sheetnames:
        rows = io.read_rows(wb, "Follow-up e riprese")
        rows.sort(key=lambda r: -(r.get("Score") or 0))
        n_fu = n_rip = 0
        t_f1 = pick_template(templates, "SEQUENZA · F1")
        t_rip = pick_template(templates, "RIPRESA")
        for r in rows:
            tipo = str(r.get("Tipo azione") or "").strip()
            item = {
                "nome": r.get("Nome") or "", "azienda": r.get("Azienda") or "",
                "ruolo": r.get("Ruolo") or "", "email": r.get("Email") or "",
                "segmento": r.get("Segmento") or "", "variante": "—",
            }
            if tipo.startswith("Follow-up") and n_fu < cap_fu:
                item.update({"tipo": "follow-up", "fonte": "Follow-up e riprese",
                             "oggetto": (t_f1 or {}).get("oggetto", ""),
                             "corpo": (t_f1 or {}).get("corpo", ""),
                             "versione": "F1"})
                if try_add(item):
                    n_fu += 1
            elif tipo.startswith("Ripresa") and n_rip < cap_rip:
                item.update({"tipo": "ripresa", "fonte": "Follow-up e riprese",
                             "oggetto": (t_rip or {}).get("oggetto", ""),
                             "corpo": (t_rip or {}).get("corpo", ""),
                             "versione": "RIPRESA"})
                if try_add(item):
                    n_rip += 1

    # ---- render finale dei segnaposto --------------------------------------
    today = today or datetime.now()
    for item in batch:
        item["oggetto"] = render_placeholders(item.get("oggetto", ""),
                                              item["nome"], item["azienda"], today)
        item["corpo"] = render_placeholders(item.get("corpo", ""),
                                            item["nome"], item["azienda"], today)
    return batch


# --------------------------------------------------------------------------
# Output: .eml + riepilogo.html
# --------------------------------------------------------------------------
def write_outputs(batch: list[dict], cfg: dict, out_root: str | Path | None = None,
                  today: datetime | None = None) -> Path:
    today = today or datetime.now()
    root = Path(out_root or cfg.get("paths", {}).get("bozze", "bozze"))
    out_dir = root / f"{today:%Y%m%d}"
    out_dir.mkdir(parents=True, exist_ok=True)

    sender = f'{cfg.get("sender_name", "")} <{cfg.get("sender_email", "")}>'
    for i, item in enumerate(batch, start=1):
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = item["email"]
        msg["Subject"] = item["oggetto"]
        msg["X-Prospecting-Variante"] = item.get("variante", "")
        msg["X-Prospecting-Versione"] = item.get("versione", "")
        msg.set_content(item["corpo"])
        safe = re.sub(r"[^a-z0-9]+", "_", str(item["email"]).lower()).strip("_")
        (out_dir / f"{i:02d}_{item.get('variante','X')}_{safe}.eml").write_bytes(
            bytes(msg))

    rows_html = "\n".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td>"
        "<td>{}</td><td>{}</td></tr>".format(
            i, html.escape(str(it.get("tipo", ""))),
            html.escape(str(it.get("variante", ""))),
            html.escape(str(it.get("nome", ""))),
            html.escape(str(it.get("azienda", ""))),
            html.escape(str(it.get("email", ""))),
            html.escape(str(it.get("versione", ""))))
        for i, it in enumerate(batch, start=1)
    )
    (out_dir / "riepilogo.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Batch {d}</title>"
        "<h1>Batch del {d} — {n} bozze</h1>"
        "<table border='1' cellpadding='6' cellspacing='0'>"
        "<tr><th>#</th><th>Tipo</th><th>Variante</th><th>Nome</th>"
        "<th>Azienda</th><th>Email</th><th>Versione</th></tr>{rows}</table>"
        .format(d=f"{today:%d/%m/%Y}", n=len(batch), rows=rows_html),
        encoding="utf-8",
    )
    return out_dir


# --------------------------------------------------------------------------
# Auto-rifornimento (UNICHE scritture ammesse: append-only + backup)
# --------------------------------------------------------------------------
CODA_HEADERS = ["Priorità", "Variante test", "Segmento", "N", "Data", "Ora",
                "Azienda", "Nome", "Ruolo", "Email", "Verifica", "Confidenza",
                "Oggetto da usare", "Versione (V4 matrice)", "Stato", "Note",
                "Corpo mail", "Oggetto V4 (ruolo×società)", "Corpo V4 (ruolo×società)"]


def count_valid_not_queued(wb) -> int:
    from common import io_master as io

    if "Nuovi contatti" not in wb.sheetnames:
        return 0
    return sum(
        1 for r in io.read_rows(wb, "Nuovi contatti")
        if str(r.get("Verification") or "").lower() == "valid"
        and not str(r.get("Nota") or "").strip()
    )


def refill_queue(master_path: str | Path, cfg: dict, *, apply: bool,
                 today: datetime | None = None) -> dict:
    """Se i valid non accodati sono sotto soglia_scorta, genera un nuovo foglio
    `Coda invii dal GG-MM` con colonne R/S V4 compilate e flagga la Nota dei
    contatti presi. Append-only + backup (via io_master). Idempotente: se il
    foglio del giorno esiste già non fa nulla."""
    from common import io_master as io

    today = today or datetime.now()
    soglia = cfg.get("soglia_scorta", 60)
    log = io.RunLog(component="queue_refill", apply=apply)

    wb = io.load(master_path)
    n_valid = count_valid_not_queued(wb)
    if n_valid >= soglia:
        log.notes.append(f"scorta OK: {n_valid} valid non accodati (soglia {soglia})")
        return {"created": False, "n_valid": n_valid, "log": log}

    sheet_name = f"Coda invii dal {today:%d-%m}"
    if sheet_name in wb.sheetnames:
        log.notes.append(f"{sheet_name!r} esiste già — idempotenza, nessuna azione")
        return {"created": False, "n_valid": n_valid, "log": log}

    rows = [r for r in io.read_rows(wb, "Nuovi contatti")
            if str(r.get("Verification") or "").lower() == "valid"
            and not str(r.get("Nota") or "").strip()]
    rows.sort(key=lambda r: -(r.get("Score") or 0))
    domini_congelati = set(cfg.get("domini_congelati") or [])
    rows = [r for r in rows if _domain(r.get("Email")) not in domini_congelati]

    # 2 settimane × 12 fredde/giorno (5 gg lavorativi)
    n_take = min(len(rows), 12 * 10)
    ws = wb.create_sheet(sheet_name)
    ws.append(CODA_HEADERS)
    nc = wb["Nuovi contatti"]
    for i, r in enumerate(rows[:n_take], start=1):
        nome, azienda, ruolo = r.get("Nome") or "", r.get("Azienda") or "", r.get("Ruolo") or ""
        s_v4, b_v4, tag = email_matrix.build_email(nome, azienda, ruolo)
        ws.append([
            i, "", r.get("Segmento") or "", i, "", "",
            azienda, nome, ruolo, r.get("Email") or "",
            r.get("Verification") or "", r.get("Confidence") or "",
            "", tag, "Da inviare", "", "", s_v4, b_v4,
        ])
        io.set_cell(nc, r["_row"], "M", f"In coda dal {today:%d/%m}",
                    sheet_name="Nuovi contatti", log=log)

    io.save(wb, master_path, apply=apply,
            backup_dir=cfg.get("paths", {}).get("backup", "backup"), log=log)
    log.notes.append(f"nuova coda {sheet_name!r}: {n_take} contatti, V4 compilate")
    return {"created": True, "sheet": sheet_name, "n": n_take,
            "n_valid": n_valid, "log": log}


def autonomy_days(n_valid: int, per_day: int = 12) -> float:
    return round(n_valid / per_day, 1) if per_day else 0.0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Queue builder (Componente B)")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--apply", action="store_true",
                    help="abilita le scritture dell'auto-rifornimento")
    ap.add_argument("--outlook-drafts", action="store_true",
                    help="crea bozze in Outlook via AppleScript (solo macOS, MAI invia)")
    args = ap.parse_args(argv)

    import yaml
    from common import io_master as io
    from common.notify import notify

    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    master = cfg["master_path"]

    wb = io.load(master, data_only=True)
    batch = select_batch(wb, cfg)
    out_dir = write_outputs(batch, cfg)

    # auto-rifornimento (uniche scritture ammesse)
    refill = refill_queue(master, cfg, apply=args.apply)
    refill["log"].save(cfg.get("paths", {}).get("logs", "logs"))
    n_valid = refill["n_valid"]

    by_var = Counter(i.get("variante", "?") for i in batch)
    print(f"Batch: {len(batch)} bozze in {out_dir} "
          f"(A={by_var.get('A',0)} B={by_var.get('B',0)} C={by_var.get('C',0)})")
    if refill.get("created"):
        print(f"Refill: creato {refill['sheet']!r} con {refill['n']} contatti (V4 pronte)"
              + ("" if args.apply else " [DRY-RUN, non salvato]"))
    print(f"Autonomia residua: scorte lead ~{autonomy_days(n_valid)} giorni al ritmo attuale")

    if args.outlook_drafts:
        _outlook_drafts(batch, cfg)

    notify("Queue builder", f"{len(batch)} bozze pronte in {out_dir}")
    return 0


def _outlook_drafts(batch: list[dict], cfg: dict) -> None:
    """Crea BOZZE in Outlook (macOS, osascript). Non invia mai."""
    import shutil
    import subprocess

    if sys.platform != "darwin" or not shutil.which("osascript"):
        print("--outlook-drafts: disponibile solo su macOS con osascript.")
        return
    for item in batch:
        subj = item["oggetto"].replace('"', "'")
        body = item["corpo"].replace('"', "'").replace("\n", "\\n")
        script = (
            'tell application "Microsoft Outlook"\n'
            f'  set newMsg to make new outgoing message with properties '
            f'{{subject:"{subj}", plain text content:"{body}"}}\n'
            f'  make new recipient at newMsg with properties '
            f'{{email address:{{address:"{item["email"]}"}}}}\n'
            "  open newMsg\n"
            "end tell"
        )
        subprocess.run(["osascript", "-e", script], capture_output=True)


if __name__ == "__main__":
    raise SystemExit(main())
