"""Componente D — trigger monitor (ultimo).

Segnali reali sugli enti di `Ranking aziende` → mail agganciate a eventi (le
più efficaci in assoluto). Per ogni ente interroga Google News RSS con la query
della spec (nomina, nomine, bilancio, "rinnovo contratto", riorganizzazione),
deduplica per hash del link (SQLite) e produce `reports/trigger_oggi.md`
(ente · titolo · link · angolo suggerito) + notifica macOS.

Niente AI in v1; in v2 Ollama proporrà la frase d'aggancio da innestare
nella V4. Schedule consigliato: 07:30.

Parsing feed: usa `feedparser` se installato, altrimenti un fallback integrato
su xml.etree (Google News è RSS 2.0 standard) — zero dipendenze obbligatorie.

Uso:
    python -m triggers.trigger_monitor --config config.yaml
    python -m triggers.trigger_monitor --config config.yaml --max-enti 10
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

QUERY_TERMS = '(nomina OR nomine OR bilancio OR "rinnovo contratto" OR riorganizzazione)'


def rss_url(ente: str) -> str:
    """URL Google News RSS per un ente, come da spec."""
    q = f'"{ente}" {QUERY_TERMS}'
    return ("https://news.google.com/rss/search?q="
            + urllib.parse.quote(q)
            + "&hl=it&gl=IT&ceid=IT:it")


# --------------------------------------------------------------------------
# Parsing del feed (feedparser se c'è, altrimenti ElementTree)
# --------------------------------------------------------------------------
def parse_feed(content: bytes | str) -> list[dict]:
    """Ritorna [{title, link, published}] dal contenuto XML del feed."""
    try:
        import feedparser  # type: ignore

        feed = feedparser.parse(content)
        return [{"title": e.get("title", ""), "link": e.get("link", ""),
                 "published": e.get("published", "")} for e in feed.entries]
    except ImportError:
        pass
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    root = ET.fromstring(content)
    out = []
    for item in root.iter("item"):
        out.append({
            "title": (item.findtext("title") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
            "published": (item.findtext("pubDate") or "").strip(),
        })
    return out


def fetch_feed(ente: str, timeout_s: int = 10) -> list[dict]:
    import requests

    resp = requests.get(rss_url(ente), timeout=timeout_s,
                        headers={"User-Agent": "Mozilla/5.0 (trigger-monitor)"})
    resp.raise_for_status()
    return parse_feed(resp.content)


# --------------------------------------------------------------------------
# Dedup per hash del link (SQLite)
# --------------------------------------------------------------------------
def link_hash(link: str) -> str:
    return hashlib.sha256((link or "").strip().encode()).hexdigest()


class SeenStore:
    """Persistenza degli hash già visti (idempotenza tra run)."""

    def __init__(self, db_path: str | Path):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS seen "
            "(hash TEXT PRIMARY KEY, ente TEXT, title TEXT, first_seen TEXT)"
        )
        self.conn.commit()

    def is_new(self, link: str) -> bool:
        h = link_hash(link)
        cur = self.conn.execute("SELECT 1 FROM seen WHERE hash=?", (h,))
        return cur.fetchone() is None

    def mark(self, link: str, ente: str, title: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO seen VALUES (?,?,?,?)",
            (link_hash(link), ente, title, datetime.now().isoformat()),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


# --------------------------------------------------------------------------
# Angolo suggerito (regole semplici, niente AI in v1)
# --------------------------------------------------------------------------
_ANGLES = (
    (("nomina", "nomine", "nominato", "nominata", "nuovo direttore",
      "nuovo presidente"),
     "Nuova nomina: primo contatto al nuovo dirigente o al suo staff — "
     "finestra ideale per un confronto sulla posizione personale."),
    (("bilancio", "utile", "risultati"),
     "Bilancio pubblicato: aggancio sul buon momento dell'ente e sul "
     "consolidare anche la pianificazione personale."),
    (("rinnovo contratto", "contratto", "ccnl"),
     "Rinnovo contrattuale: aggancio sull'adeguamento retributivo e su cosa "
     "conviene destinare a previdenza deducibile."),
    (("riorganizzazione", "fusione", "accorpamento"),
     "Riorganizzazione in corso: incertezza = momento giusto per un secondo "
     "parere su coperture e previdenza personale."),
)


def suggest_angle(title: str) -> str:
    t = (title or "").lower()
    for needles, angle in _ANGLES:
        if any(n in t for n in needles):
            return angle
    return ("Segnale generico sull'ente: usare come apertura di attualità "
            "prima dell'aggancio V4 della matrice.")


# --------------------------------------------------------------------------
# Lettura enti + report
# --------------------------------------------------------------------------
def read_enti(master_path: str | Path, max_enti: int | None = None) -> list[str]:
    from common import io_master as io

    wb = io.load(master_path, data_only=True)
    if "Ranking aziende" not in wb.sheetnames:
        return []
    rows = io.read_rows(wb, "Ranking aziende")
    if not rows:
        return []
    # la colonna dell'ente ha intestazioni variabili nel master reale
    # ("Azienda/ente", "Azienda", "Ente", "Nome"): match per prefisso,
    # altrimenti la prima colonna del foglio.
    headers = [k for k in rows[0].keys() if k != "_row"]
    col = next(
        (h for h in headers
         if h.lower().startswith(("azienda", "ente", "nome"))),
        headers[0] if headers else None,
    )
    if col is None:
        return []
    enti = []
    for r in rows:
        v = str(r.get(col) or "").strip()
        if v:
            enti.append(v)
    if max_enti:
        enti = enti[:max_enti]
    return enti


def write_report(triggers: list[dict], reports_dir: str | Path,
                 today: datetime | None = None) -> Path:
    today = today or datetime.now()
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "trigger_oggi.md"

    lines = [f"# Trigger del {today:%d/%m/%Y}", ""]
    if not triggers:
        lines.append("Nessun segnale nuovo oggi.")
    for t in triggers:
        lines += [
            f"## {t['ente']}",
            f"- **{t['title']}**",
            f"- {t['link']}",
            f"- *Angolo suggerito*: {t['angle']}",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run(master_path: str | Path, reports_dir: str | Path, db_path: str | Path,
        max_enti: int | None = None, per_ente: int = 3) -> list[dict]:
    enti = read_enti(master_path, max_enti)
    store = SeenStore(db_path)
    triggers: list[dict] = []
    for ente in enti:
        try:
            entries = fetch_feed(ente)
        except Exception as exc:
            print(f"  [WARN] feed {ente!r}: {type(exc).__name__}")
            continue
        n = 0
        for e in entries:
            if n >= per_ente:
                break
            if not e["link"] or not store.is_new(e["link"]):
                continue
            store.mark(e["link"], ente, e["title"])
            triggers.append({"ente": ente, "title": e["title"],
                             "link": e["link"], "angle": suggest_angle(e["title"])})
            n += 1
    store.close()
    write_report(triggers, reports_dir)
    return triggers


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Trigger monitor (Componente D)")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--max-enti", type=int, default=None)
    args = ap.parse_args(argv)

    import yaml
    from common.notify import notify

    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    reports_dir = cfg.get("paths", {}).get("reports", "reports")
    db_path = Path(cfg.get("paths", {}).get("logs", "logs")) / "triggers_seen.sqlite"

    triggers = run(cfg["master_path"], reports_dir, db_path, args.max_enti)
    msg = f"{len(triggers)} segnali nuovi → {reports_dir}/trigger_oggi.md"
    print(msg)
    notify("Trigger monitor", msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
