"""Test del queue builder (Componente B): batch, split A/B/C, cap, esclusioni,
render, output .eml, auto-rifornimento con V4, lead refill."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from queue import queue_builder as qb  # noqa: E402
from queue import lead_refill as lr  # noqa: E402
from common import io_master as io  # noqa: E402

TODAY = datetime(2026, 7, 10)


# --------------------------------------------------------------------------
# Fixture: master sintetico completo
# --------------------------------------------------------------------------
def make_master(tmp_path: Path, n_coda: int = 15, n_nuovi: int = 10) -> Path:
    wb = openpyxl.Workbook()

    reg = wb.active
    reg.title = "Registro invii"
    reg.append(["Data invio", "Email", "Ente/dominio", "Oggetto", "Stato",
                "Azione consigliata", "Risposta associata", "Preview risposta",
                "Gg lav da invio", "Variante"])
    # un contatto con stato ≠ Nessuna risposta → escluso dai batch
    reg.append(["", "escluso.registro@enteX.it", "enteX.it", "", "Rifiuto / non interessato",
                "", "", "", "", ""])

    nr = wb.create_sheet("Non riscrivere")
    nr.append(["Score", "Nome", "Azienda", "", "", "", "", "", "Email"])
    nr.append([0, "Bruno Vietato", "Ente Blocco", "", "", "", "", "", ""])

    coda = wb.create_sheet("Coda invii dal 07-07")
    coda.append(qb.CODA_HEADERS)
    for i in range(1, n_coda + 1):
        coda.append([i, "", "PA / ente pubblico", i, "", "",
                     f"Ente{i}", f"Nome{i} Cognome{i}", "Manager",
                     f"nome{i}.cognome{i}@ente{i}.it", "valid", 90,
                     f"Oggetto {i}", "", "Da inviare", "",
                     f"Corpo A del contatto {i}, gentile [Cognome] di [Ente].",
                     "", ""])

    nc = wb.create_sheet("Nuovi contatti")
    nc.append(["Score", "Azione", "Segmento", "Persona", "Nome", "Azienda", "Ruolo",
               "Dipartimento", "Città", "Email", "Verification", "Confidence", "Nota"])
    for i in range(1, n_nuovi + 1):
        nc.append([100 + i, "NUOVO", "PA / ente pubblico", "Quadro",
                   f"Nuovo{i} Contatto{i}", f"NuovoEnte{i}", "Responsabile",
                   "Dip", "Roma", f"nuovo{i}.contatto{i}@nuovoente{i}.it",
                   "valid", 90, ""])

    fu = wb.create_sheet("Follow-up e riprese")
    fu.append(["Score", "Segmento", "Persona", "Nome", "Azienda", "Ruolo",
               "Email", "Ultimo invio", "Gg lavorativi", "Tipo azione", "Template"])
    for i in range(1, 13):
        tipo = "Follow-up standard" if i <= 8 else "Ripresa contatto"
        fu.append([50 + i, "PA", "Q", f"Fu{i} Cog{i}", f"FuEnte{i}", "Manager",
                   f"fu{i}@fuente{i}.it", "", "", tipo, ""])

    tpl = wb.create_sheet("Template")
    tpl.append(["Template", "Oggetto", "Corpo"])
    tpl.append(["A · CONTROLLO — fredda PA / ente pubblico",
                "Breve confronto su previdenza", "Gentile [Cognome], corpo A per [Ente]."])
    tpl.append(["B · CHALLENGER V2 — fredda PA / ente pubblico",
                "Previdenza: cosa cambia dal 2026", "Gentile [Cognome], corpo B per [Ente]."])
    tpl.append(["SEQUENZA · F1 — bump nel thread (giorno 3-4)",
                "RE: [oggetto originario]", "Gentile [Cognome], torno sul tema."])
    tpl.append(["RIPRESA — contatti >25 gg",
                "Previdenza integrativa: cosa cambia nel 2026",
                "Gentile [Cognome], la ricontatto dopo qualche settimana."])

    path = tmp_path / "master.xlsx"
    wb.save(path)
    return path


CFG = {
    "caps": {"totale": 30, "fredde": 12, "follow_up": 10, "riprese": 5,
             "accept_all": 3, "stesso_dominio": 8},
    "domini_congelati": ["sace.it"],
    "soglia_scorta": 60,
    "sender_email": "io@me.it", "sender_name": "Io",
    "paths": {"backup": "backup", "logs": "logs", "bozze": "bozze"},
}


def _load(master):
    return io.load(master, data_only=True)


# --------------------------------------------------------------------------
# Batch: dimensioni, split, cap, esclusioni
# --------------------------------------------------------------------------
def test_batch_12_fredde_10_fu_5_riprese(tmp_path):
    master = make_master(tmp_path)
    batch = qb.select_batch(_load(master), CFG, today=TODAY)
    fredde = [b for b in batch if b["tipo"] == "fredda"]
    fu = [b for b in batch if b["tipo"] == "follow-up"]
    rip = [b for b in batch if b["tipo"] == "ripresa"]
    assert len(fredde) == 12
    assert len(fu) == 8          # solo 8 follow-up maturi nel fixture
    assert len(rip) == 4         # 4 riprese nel fixture
    assert len(batch) <= 30


def test_split_abc_4_4_4(tmp_path):
    master = make_master(tmp_path)
    batch = qb.select_batch(_load(master), CFG, today=TODAY)
    fredde = [b for b in batch if b["tipo"] == "fredda"]
    from collections import Counter
    c = Counter(b["variante"] for b in fredde)
    assert c == {"A": 4, "B": 4, "C": 4}


def test_variante_c_usa_matrice_v4(tmp_path):
    master = make_master(tmp_path)
    batch = qb.select_batch(_load(master), CFG, today=TODAY)
    cs = [b for b in batch if b.get("variante") == "C"]
    assert cs
    for b in cs:
        assert b["versione"].startswith("C (")
        assert "secondo parere" in b["corpo"].lower()   # blocco anti-obiezione V4
        assert "⟦" not in b["corpo"]                     # niente segnaposto irrisolti


def test_esclusione_registro_e_non_riscrivere(tmp_path):
    master = make_master(tmp_path, n_coda=3)
    wb = openpyxl.load_workbook(master)
    coda = wb["Coda invii dal 07-07"]
    # contatto presente nel Registro con stato ≠ Nessuna risposta
    coda.append([99, "", "PA", 99, "", "", "EnteX", "Tizio Caio", "Manager",
                 "escluso.registro@enteX.it", "valid", 90, "", "", "Da inviare",
                 "", "corpo", "", ""])
    # contatto in Non riscrivere (match Nome+Azienda)
    coda.append([98, "", "PA", 98, "", "", "Ente Blocco", "Bruno Vietato", "Manager",
                 "bruno.vietato@enteblocco.it", "valid", 90, "", "", "Da inviare",
                 "", "corpo", "", ""])
    wb.save(master)
    batch = qb.select_batch(_load(master), CFG, today=TODAY)
    emails = {b["email"].lower() for b in batch}
    assert "escluso.registro@entex.it" not in emails
    assert "bruno.vietato@enteblocco.it" not in emails


def test_zero_contatti_in_blacklist_nel_batch(tmp_path):
    """Test automatico richiesto dalla spec (§B Done)."""
    master = make_master(tmp_path)
    wb = _load(master)
    batch = qb.select_batch(wb, CFG, today=TODAY)
    non_riscrivere, stato_email = qb.build_exclusions(wb)
    for b in batch:
        assert b["email"].lower() not in stato_email
        assert qb._norm_key(b["nome"], b["azienda"]) not in non_riscrivere


def test_cap_accept_all(tmp_path):
    master = make_master(tmp_path, n_coda=0)
    wb = openpyxl.load_workbook(master)
    coda = wb["Coda invii dal 07-07"]
    for i in range(1, 9):
        coda.append([i, "", "PA", i, "", "", f"E{i}", f"N{i} C{i}", "Manager",
                     f"n{i}.c{i}@e{i}.it", "accept_all", 60, "", "", "Da inviare",
                     "", "corpo", "", ""])
    wb.save(master)
    cfg = {**CFG, "caps": {**CFG["caps"], "fredde": 12}}
    batch = qb.select_batch(_load(master), cfg, today=TODAY)
    accept = [b for b in batch if b["tipo"] == "fredda" and b["fonte"].startswith("Coda")]
    assert len(accept) <= 3 + 12  # sanity
    n_accept = sum(1 for b in batch if b.get("verifica") == "accept_all")
    assert n_accept <= 3


def test_cap_stesso_dominio(tmp_path):
    master = make_master(tmp_path, n_coda=0, n_nuovi=0)
    wb = openpyxl.load_workbook(master)
    coda = wb["Coda invii dal 07-07"]
    for i in range(1, 13):
        coda.append([i, "", "PA", i, "", "", "StessoEnte", f"P{i} Q{i}", "Manager",
                     f"p{i}.q{i}@stessodominio.it", "valid", 90, "", "",
                     "Da inviare", "", "corpo", "", ""])
    wb.save(master)
    batch = qb.select_batch(_load(master), CFG, today=TODAY)
    fredde = [b for b in batch if b["tipo"] == "fredda"]
    assert len(fredde) == 8      # cap stesso_dominio


def test_fallback_a_nuovi_contatti_quando_code_esaurite(tmp_path):
    master = make_master(tmp_path, n_coda=2, n_nuovi=20)
    batch = qb.select_batch(_load(master), CFG, today=TODAY)
    fredde = [b for b in batch if b["tipo"] == "fredda"]
    assert len(fredde) == 12
    assert sum(1 for b in fredde if b["fonte"] == "Nuovi contatti") == 10


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------
def test_render_placeholders():
    out = qb.render_placeholders(
        "Gentile [Cognome] di [Ente], ci vediamo a [mese] il [GG] alle [HH:MM].",
        "Mario Rossi", "ACME", today=TODAY)
    assert "Gentile Rossi di ACME" in out
    assert "a luglio" in out
    assert "⟦GG⟧" in out and "⟦HH:MM⟧" in out    # irrisolti evidenziati


# --------------------------------------------------------------------------
# Output .eml + riepilogo
# --------------------------------------------------------------------------
def test_write_outputs_eml_e_riepilogo(tmp_path):
    master = make_master(tmp_path)
    batch = qb.select_batch(_load(master), CFG, today=TODAY)
    out_dir = qb.write_outputs(batch, CFG, out_root=tmp_path / "bozze", today=TODAY)
    emls = sorted(out_dir.glob("*.eml"))
    assert len(emls) == len(batch)
    # ogni .eml è RFC822 apribile
    from email import message_from_bytes
    msg = message_from_bytes(emls[0].read_bytes())
    assert msg["To"] and msg["Subject"] and msg.get_payload()
    assert (out_dir / "riepilogo.html").exists()
    html_text = (out_dir / "riepilogo.html").read_text(encoding="utf-8")
    assert f"{len(batch)} bozze" in html_text


# --------------------------------------------------------------------------
# Auto-rifornimento
# --------------------------------------------------------------------------
def test_refill_sotto_soglia_crea_coda_con_v4(tmp_path):
    master = make_master(tmp_path, n_nuovi=10)     # 10 valid < soglia 60
    res = qb.refill_queue(master, CFG, apply=True, today=TODAY)
    assert res["created"] is True
    wb = openpyxl.load_workbook(master)
    sheet = f"Coda invii dal {TODAY:%d-%m}"
    assert sheet in wb.sheetnames
    ws = wb[sheet]
    assert [c.value for c in ws[1]] == qb.CODA_HEADERS
    # R/S V4 compilate
    assert ws.cell(2, 18).value            # Oggetto V4
    assert "secondo parere" in str(ws.cell(2, 19).value).lower()
    # Nota flaggata sui contatti presi
    nc = wb["Nuovi contatti"]
    assert str(nc.cell(2, 13).value).startswith("In coda dal")


def test_refill_sopra_soglia_non_fa_nulla(tmp_path):
    master = make_master(tmp_path, n_nuovi=10)
    cfg = {**CFG, "soglia_scorta": 5}              # 10 valid ≥ 5
    res = qb.refill_queue(master, cfg, apply=True, today=TODAY)
    assert res["created"] is False


def test_refill_idempotente(tmp_path):
    master = make_master(tmp_path, n_nuovi=10)
    qb.refill_queue(master, CFG, apply=True, today=TODAY)
    res2 = qb.refill_queue(master, CFG, apply=True, today=TODAY)
    assert res2["created"] is False                # il foglio del giorno esiste già
    wb = openpyxl.load_workbook(master)
    assert sum(1 for s in wb.sheetnames
               if s == f"Coda invii dal {TODAY:%d-%m}") == 1


def test_refill_dry_run_non_scrive(tmp_path):
    master = make_master(tmp_path, n_nuovi=10)
    before = master.read_bytes()
    res = qb.refill_queue(master, CFG, apply=False, today=TODAY)
    assert res["created"] is True                  # avrebbe creato...
    assert master.read_bytes() == before           # ...ma non ha scritto


def test_simulazione_svuotamento_genera_coda_v4(tmp_path):
    """Spec §B Done: svuotando le code, il sistema genera da solo la coda
    successiva con le V4 pronte — nessuna mattina senza batch."""
    master = make_master(tmp_path, n_coda=0, n_nuovi=15)
    res = qb.refill_queue(master, CFG, apply=True, today=TODAY)
    assert res["created"] and res["n"] == 15
    batch = qb.select_batch(_load(master), CFG, today=TODAY)
    fredde = [b for b in batch if b["tipo"] == "fredda"]
    assert len(fredde) == 12                       # batch pieno dalla nuova coda


# --------------------------------------------------------------------------
# Lead refill dall'archivio
# --------------------------------------------------------------------------
def test_lead_refill_dedupe_e_append(tmp_path):
    master = make_master(tmp_path, n_nuovi=3)
    arch = openpyxl.Workbook()
    ws = arch.active
    ws.append(["Nome", "Azienda", "Ruolo", "Email", "Verification", "Segmento"])
    ws.append(["Nuovo1 Contatto1", "NuovoEnte1", "Manager",
               "nuovo1.contatto1@nuovoente1.it", "valid", "PA"])   # dup email
    ws.append(["Franca Neri", "Ente Nuovissimo", "Director General",
               "franca.neri@nuovissimo.it", "valid", "PA"])        # nuovo
    ws.append(["Bruno Vietato", "Ente Blocco", "Manager",
               "bruno.v@enteblocco.it", "valid", "PA"])            # dup Nome+Azienda
    arch_path = tmp_path / "archivio.xlsx"
    arch.save(arch_path)

    res = lr.refill(master, arch_path, CFG, apply=True, top_n=10)
    assert res["appended"] == 1
    wb = openpyxl.load_workbook(master)
    nc = wb["Nuovi contatti"]
    last = nc.max_row
    assert nc.cell(last, 10).value == "franca.neri@nuovissimo.it"
    assert nc.cell(last, 2).value == "NUOVO CONTATTO"
    assert (nc.cell(last, 1).value or 0) >= 150    # score da Director General
