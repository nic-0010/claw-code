"""Test del trigger monitor (Componente D): URL, parsing RSS, dedup SQLite,
angoli suggeriti, report markdown."""

from __future__ import annotations

import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from triggers import trigger_monitor as tm  # noqa: E402

RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Google News</title>
<item><title>GSE, nomina del nuovo direttore generale</title>
<link>https://news.example.it/gse-nomina</link>
<pubDate>Thu, 09 Jul 2026 08:00:00 GMT</pubDate></item>
<item><title>GSE approva il bilancio 2025</title>
<link>https://news.example.it/gse-bilancio</link>
<pubDate>Wed, 08 Jul 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_rss_url_come_da_spec():
    url = tm.rss_url("Regione Lazio")
    assert url.startswith("https://news.google.com/rss/search?q=")
    assert url.endswith("&hl=it&gl=IT&ceid=IT:it")
    q = urllib.parse.unquote(url.split("q=")[1].split("&hl=")[0])
    assert '"Regione Lazio"' in q
    for term in ("nomina", "nomine", "bilancio", '"rinnovo contratto"',
                 "riorganizzazione"):
        assert term in q


def test_parse_feed_fallback_elementtree():
    entries = tm.parse_feed(RSS_SAMPLE)
    assert len(entries) == 2
    assert entries[0]["title"].startswith("GSE, nomina")
    assert entries[0]["link"] == "https://news.example.it/gse-nomina"


def test_dedup_sqlite(tmp_path):
    store = tm.SeenStore(tmp_path / "seen.sqlite")
    link = "https://news.example.it/x"
    assert store.is_new(link)
    store.mark(link, "GSE", "titolo")
    assert not store.is_new(link)
    store.close()
    # persistenza tra run
    store2 = tm.SeenStore(tmp_path / "seen.sqlite")
    assert not store2.is_new(link)
    assert store2.is_new("https://news.example.it/y")
    store2.close()


def test_suggest_angle():
    assert "nomina" in tm.suggest_angle("GSE, nomina del nuovo direttore").lower()
    assert "bilancio" in tm.suggest_angle("Approvato il bilancio 2025").lower()
    assert "contrattuale" in tm.suggest_angle("Rinnovo contratto dei dipendenti").lower()
    assert "riorganizzazione" in tm.suggest_angle("Al via la riorganizzazione").lower()
    assert "generico" in tm.suggest_angle("Notizia qualunque").lower()


def test_write_report(tmp_path):
    triggers = [{"ente": "GSE", "title": "Nomina DG",
                 "link": "https://x.it/1", "angle": "Nuova nomina: contatto."}]
    path = tm.write_report(triggers, tmp_path, today=datetime(2026, 7, 10))
    text = path.read_text(encoding="utf-8")
    assert path.name == "trigger_oggi.md"
    assert "# Trigger del 10/07/2026" in text
    assert "## GSE" in text and "https://x.it/1" in text
    assert "Angolo suggerito" in text


def test_write_report_vuoto(tmp_path):
    path = tm.write_report([], tmp_path)
    assert "Nessun segnale nuovo oggi." in path.read_text(encoding="utf-8")


def test_read_enti(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ranking aziende"
    ws.append(["Azienda", "Score"])
    ws.append(["GSE", 100])
    ws.append(["Regione Lazio", 90])
    ws.append(["MPS", 80])
    p = tmp_path / "m.xlsx"
    wb.save(p)
    assert tm.read_enti(p) == ["GSE", "Regione Lazio", "MPS"]
    assert tm.read_enti(p, max_enti=2) == ["GSE", "Regione Lazio"]
