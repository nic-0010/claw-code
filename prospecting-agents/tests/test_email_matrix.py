"""Test della Matrice V4 — invarianti + stabilità snapshot (24 combinazioni)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import email_matrix as em  # noqa: E402
from evals.gen_matrix_snapshots import (  # noqa: E402
    COMPANIES,
    ROLES,
    SNAP_DIR,
    _safe,
    render,
)

ALL_TAGS = [f"{ck}·{rc}" for ck, _ in COMPANIES for rc, _, _ in ROLES]


# --------------------------------------------------------------------------
# Classificazione assi
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "ruolo,expected",
    [
        ("CEO", "C"),
        ("Director General", "C"),
        ("Segretario generale", "C"),
        ("Deputy Director General", "C"),   # contiene "director general" → C
        ("Deputy Director", "DIR"),          # senza "general" → DIR
        ("Fire Chief", "DIR"),
        ("Head of Procurement", "DIR"),
        ("Responsabile Acquisti", "QUAD"),
        ("Team Leader", "QUAD"),
        ("Analyst", "STAFF"),
        ("Impiegato amministrativo", "STAFF"),
        ("qualcosa di ignoto", "QUAD"),      # default
    ],
)
def test_role_cluster(ruolo, expected):
    assert em.role_cluster(ruolo) == expected


@pytest.mark.parametrize(
    "azienda,expected",
    [
        ("Comando Vigili del Fuoco", "SICUREZZA"),
        ("Guardia di Finanza", "SICUREZZA"),
        ("GSE", "PARTECIPATA"),
        ("SACE S.p.A.", "PARTECIPATA"),      # SACE vince su S.p.A.
        ("Ministero degli Affari Esteri", "ORGINT"),
        ("WFP - World Food Programme", "ORGINT"),
        ("Monte dei Paschi di Siena", "BANCA"),
        ("Regione Lazio", "PA"),
        ("Comune di Roma", "PA"),
        ("Fendi S.p.A.", "CORP"),
        ("Ente Ignoto XYZ", "PA"),           # default
    ],
)
def test_company_key(azienda, expected):
    assert em.company_key(azienda) == expected


@pytest.mark.parametrize(
    "azienda,email,expected",
    [
        # dominio autoritativo (nome ente troncato/tradotto o assente)
        ("Deutsche Gesellschaft für Internationale Zusammenarbeit",
         "andrea.von.rauch@giz.de", "ORGINT"),
        ("", "x@wfp.org", "ORGINT"),
        ("", "y@ifad.org", "ORGINT"),
        ("Ministero degli Affari Esteri", "z@esteri.it", "ORGINT"),
        ("Comando Provinciale", "k@vigilfuoco.it", "SICUREZZA"),
        ("", "a@gse.it", "PARTECIPATA"),
        # dominio estero sconosciuto → mai PA italiana → ORGINT
        ("Agenzia Sconosciuta", "p@example.de", "ORGINT"),
        # dominio .it sconosciuto senza match nome → PA
        ("Ente Ignoto", "q@ente-ignoto.it", "PA"),
    ],
)
def test_company_key_da_dominio(azienda, email, expected):
    assert em.company_key(azienda, email) == expected


def test_giz_non_e_pa_end_to_end():
    """Bug grave: GIZ (agenzia tedesca) non deve finire in PA con testo su
    riforme pensionistiche italiane."""
    subject, body, tag = em.build_email(
        "Andrea Von Rauch",
        "Deutsche Gesellschaft für Internationale Zusammenarbeit",
        "Advisor", email="andrea.von.rauch@giz.de")
    assert tag.startswith("ORGINT·")
    assert "(GIZ)" in subject
    assert "Deutsche" not in subject            # niente troncamento "(Deutsche)"
    assert "riforme" not in body.lower() or "gap contributivo" not in body.lower()


def test_ente_short_giz_e_none_per_lunghi():
    assert em.ente_short("Deutsche Gesellschaft für Internationale Zusammenarbeit") == "GIZ"
    # nome lungo e sconosciuto → None (l'oggetto omette la parentesi)
    assert em.ente_short("Agenzia Regionale per la Protezione Ambientale del Lazio") is None
    # nome corto → tenuto intero, non troncato
    assert em.ente_short("Regione Lazio") == "Regione Lazio"


def test_oggetto_senza_parentesi_se_ente_ignoto():
    subject, _, _ = em.build_email(
        "Mario Rossi", "Agenzia Regionale per la Protezione Ambientale del Lazio",
        "Manager", email="mario.rossi@arpa.lazio.it")
    assert "(" not in subject                   # nessuna parentesi troncata


@pytest.mark.parametrize(
    "nome,expected",
    [
        ("Andrea Von Rauch", "Von Rauch"),
        ("Maria De Rossi", "De Rossi"),
        ("Anna Della Valle", "Della Valle"),
        ("Marina Sacco", "Sacco"),              # nessuna particella
        ("Paolo", "Paolo"),
    ],
)
def test_cognome_con_particella(nome, expected):
    assert em._cognome(nome) == expected


def test_ente_short_normalizza_nomi_lunghi():
    assert em.ente_short("Ministero degli Affari Esteri") == "MAECI"
    assert em.ente_short("Monte dei Paschi di Siena") == "MPS"
    assert em.ente_short("GSE") == "GSE"
    assert em.ente_short("") is None


# --------------------------------------------------------------------------
# Firma pubblica
# --------------------------------------------------------------------------
def test_build_email_firma_e_tag():
    subject, body, tag = em.build_email("Marina Sacco", "GSE", "Director General")
    assert tag == "PARTECIPATA·C"
    assert isinstance(subject, str) and isinstance(body, str)
    assert body.startswith("Buongiorno Dott.ssa Sacco,")   # Marina → femminile


# Firma canonica esatta richiesta su OGNI mail (tutte le varianti/cluster).
FIRMA_ATTESA = (
    "Nicolò Porru\n"
    "Wealth & Insurance Advisor — Generali Italia\n"
    "Tel +39 331 454 8168 · LinkedIn: linkedin.com/in/nicolò-porru"
)


def test_firma_esatta_su_tutte_le_24_combinazioni():
    for _, azienda in COMPANIES:
        for _, ruolo, nome in ROLES:
            _, body, _ = em.build_email(nome, azienda, ruolo)
            # firma presente, esatta, e come blocco finale del corpo
            assert FIRMA_ATTESA in body, (azienda, ruolo)
            assert body.rstrip().endswith(FIRMA_ATTESA)
            assert "Wealth & Insurance Advisor" in body
            assert "+39 331 454 8168" in body
            assert "linkedin.com/in/nicolò-porru" in body
            # niente residui della vecchia firma
            assert "Employee Benefits" not in body
            assert "Un saluto," not in body


def test_saluto_maschile():
    _, body, _ = em.build_email("Marco Rossi", "Regione Lazio", "Dirigente",
                                email="marco.rossi@regione.lazio.it")
    assert body.startswith("Buongiorno Dott. Rossi,")


def test_saluto_femminile():
    _, body, _ = em.build_email("Giulia Bianchi", "GSE", "Manager",
                                email="giulia.bianchi@gse.it")
    assert body.startswith("Buongiorno Dott.ssa Bianchi,")


def test_saluto_ambiguo_maschile_dominio_italiano():
    # Andrea su dominio .it → maschile
    _, body, _ = em.build_email("Andrea Colombo", "Comune di Roma", "Funzionario",
                                email="andrea.colombo@comune.roma.it")
    assert body.startswith("Buongiorno Dott. Colombo,")
    # anche senza email → default italiano → maschile
    _, body2, _ = em.build_email("Andrea Colombo", "Comune di Roma", "Funzionario")
    assert body2.startswith("Buongiorno Dott. Colombo,")


def test_saluto_ambiguo_dominio_estero_neutro():
    # Andrea su dominio estero → fallback neutro senza titolo
    _, body, _ = em.build_email("Andrea Von Rauch", "GIZ", "Advisor",
                                email="andrea.von.rauch@giz.de")
    assert body.startswith("Buongiorno Andrea Von Rauch,")
    assert "Dott." not in body.split("\n")[0]
    # altro ambiguo su dominio internazionale
    _, body2, _ = em.build_email("Simone Dupont", "WFP", "Officer",
                                 email="simone.dupont@wfp.org")
    assert body2.startswith("Buongiorno Simone Dupont,")


def test_saluto_nome_straniero_neutro():
    # nome non italiano → mai titolo, indipendentemente dal dominio
    _, body, _ = em.build_email("Esther Law", "FAO", "Analyst",
                                email="esther.law@fao.org")
    assert body.startswith("Buongiorno Esther Law,")
    assert "Dott." not in body.split("\n")[0]


def test_gender_helper():
    assert em.gender("Marco Rossi") == "M"
    assert em.gender("Giulia Bianchi") == "F"
    assert em.gender("Andrea Rossi", "a@x.it") == "M"
    assert em.gender("Andrea Rossi", "a@giz.de") is None
    assert em.gender("Andrea Rossi") == "M"            # dominio assente → italiano
    assert em.gender("Esther Law", "a@fao.org") is None
    # ambigui maschili elencati dalla spec
    for n in ("Andrea", "Simone", "Nicola", "Daniele", "Gabriele",
              "Michele", "Luca", "Mattia", "Elia"):
        assert em.gender(n, "x@ente.it") == "M", n


def test_corpo_c_senza_frasi_non_approvate():
    # le due frasi inventate rimosse non devono comparire in nessuna mail
    for _, azienda in COMPANIES:
        for _, ruolo, nome in ROLES:
            _, body, _ = em.build_email(nome, azienda, ruolo)
            assert "così arriva già con le idee chiare" not in body
            assert "la ringrazio fin d" not in body
    # il testo validato deve restare
    _, body, _ = em.build_email("Marina Sacco", "GSE", "Director General")
    assert "Le anticipo una sintesi di una pagina." in body
    assert "non voglio in alcun modo sostituire chi la segue già".lower() in body.lower()


def test_tag_copre_le_24_combinazioni():
    tags = set()
    for _, azienda in COMPANIES:
        for _, ruolo, nome in ROLES:
            _, _, tag = em.build_email(nome, azienda, ruolo)
            tags.add(tag)
    assert tags == set(ALL_TAGS)
    assert len(tags) == 24


# --------------------------------------------------------------------------
# Invarianti tipografici su TUTTE le combinazioni
# --------------------------------------------------------------------------
def _texts():
    for _, azienda in COMPANIES:
        for _, ruolo, nome in ROLES:
            s, b, _ = em.build_email(nome, azienda, ruolo)
            yield azienda, ruolo, s, b


def test_nessun_segnaposto_non_risolto():
    for azienda, ruolo, s, b in _texts():
        for token in ("[", "]", "⟦", "⟧", "{", "}"):
            assert token not in s, f"segnaposto in subject {azienda}/{ruolo}: {s}"
            assert token not in b, f"segnaposto in body {azienda}/{ruolo}"


def test_niente_doppi_spazi():
    for azienda, ruolo, s, b in _texts():
        assert "  " not in s, f"doppio spazio in subject {azienda}/{ruolo}"
        # nel body i newline sono ok; controlliamo doppi spazi orizzontali
        for line in b.splitlines():
            assert "  " not in line, f"doppio spazio in body {azienda}/{ruolo}: {line!r}"


def test_virgolette_curve():
    for azienda, ruolo, s, b in _texts():
        assert "'" not in s and '"' not in s, f"virgolette dritte in subject {azienda}/{ruolo}"
        assert "'" not in b and '"' not in b, f"virgolette dritte in body {azienda}/{ruolo}"


def test_maiuscola_dopo_punto():
    # dopo ". " non deve mai esserci una minuscola
    pat = re.compile(r"\. ([a-zàèéìòù])")
    for azienda, ruolo, s, b in _texts():
        assert not pat.search(s), f"minuscola dopo punto in subject {azienda}/{ruolo}"
        assert not pat.search(b), f"minuscola dopo punto in body {azienda}/{ruolo}"


# --------------------------------------------------------------------------
# Stabilità snapshot
# --------------------------------------------------------------------------
def test_snapshot_stabili():
    missing = []
    diverged = []
    for ck, azienda in COMPANIES:
        for rc, ruolo, nome in ROLES:
            tag = f"{ck}·{rc}"
            p = SNAP_DIR / f"{_safe(tag)}.txt"
            if not p.exists():
                missing.append(tag)
                continue
            if p.read_text() != render(nome, azienda, ruolo):
                diverged.append(tag)
    assert not missing, f"snapshot mancanti (rigenera): {missing}"
    assert not diverged, (
        f"snapshot divergenti: {diverged}. Se intenzionale, rigenera con "
        f"`python -m evals.gen_matrix_snapshots`."
    )
