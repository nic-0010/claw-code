"""Test del verificatore (Componente C): inferenza pattern, scoring, metriche eval."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from verifier import email_verifier as v  # noqa: E402
from evals.eval_verifier import evaluate, load_csv  # noqa: E402


# --------------------------------------------------------------------------
# Inferenza pattern (pura, senza rete)
# --------------------------------------------------------------------------
def test_candidates_e_detect():
    c = v.candidates("Mario Rossi")
    assert c["nome.cognome"] == "mario.rossi"
    assert c["n.cognome"] == "m.rossi"
    assert c["cognome"] == "rossi"
    assert "nome.cognome" in v.detect_patterns("Mario Rossi", "mario.rossi")
    assert "n.cognome" in v.detect_patterns("Mario Rossi", "m.rossi")
    assert v.detect_patterns("Mario Rossi", "qualcosaltro") == []


def test_name_parts_accenti_e_multipli():
    assert v.name_parts("Nicolò Porru") == ("nicolo", "porru")
    assert v.name_parts("Maria Anna De Rossi") == ("maria", "rossi")
    assert v.name_parts("") == ("", "")


def test_infer_domain_pattern_dominante():
    valids = [
        ("Mario Rossi", "mario.rossi@acme.it"),
        ("Luca Bianchi", "luca.bianchi@acme.it"),
        ("Elena Verdi", "elena.verdi@acme.it"),
        ("Anna Neri", "n.neri@acme.it"),        # outlier
    ]
    pats = v.infer_domain_patterns(valids, min_examples=3)
    assert pats["acme.it"].pattern == "nome.cognome"
    assert pats["acme.it"].confidence == 0.75    # 3 su 4


def test_infer_domain_pattern_dati_insufficienti():
    valids = [("Mario Rossi", "mario.rossi@x.it"), ("Luca Bianchi", "luca.bianchi@x.it")]
    pats = v.infer_domain_patterns(valids, min_examples=3)
    assert pats["x.it"].pattern is None          # <3 esempi


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
def test_score_conforme_ok():
    dp = v.DomainPattern("nome.cognome", 1.0, 5)
    score, sug = v.score_address("Mario Rossi", "mario.rossi@acme.it", "accept_all", dp, True, None)
    assert score == v.OK and sug == ""


def test_score_difforme_suggerisce():
    dp = v.DomainPattern("nome.cognome", 1.0, 5)
    score, sug = v.score_address("Mario Rossi", "m.rossi@acme.it", "accept_all", dp, True, None)
    assert score == v.CORREGGERE
    assert sug == "mario.rossi@acme.it"


def test_score_mx_assente_rischio_alto():
    score, _ = v.score_address("Mario Rossi", "mario.rossi@dead.zz", "valid", None, False, None)
    assert score == v.RISCHIO_ALTO


def test_score_smtp_inesistente_vince():
    dp = v.DomainPattern("nome.cognome", 1.0, 5)
    score, _ = v.score_address("Mario Rossi", "mario.rossi@acme.it", "valid", dp, True, "inesistente")
    assert score == v.RISCHIO_ALTO


def test_score_accept_all_senza_pattern_sconosciuto():
    score, _ = v.score_address("Tizio Caio", "tizio@ignoto.it", "accept_all", None, True, None)
    assert score == v.SCONOSCIUTO


# --------------------------------------------------------------------------
# Eval end-to-end sul set d'esempio → deve passare le soglie
# --------------------------------------------------------------------------
def test_eval_example_passa_le_soglie():
    csv_path = Path(__file__).resolve().parent.parent / "evals" / "emails_labeled.example.csv"
    res = evaluate(load_csv(csv_path))
    assert res["precision_inesistente"] >= 0.95, res
    assert res["recall_inesistente"] >= 0.70, res
    assert res["fp"] == 0, res["errors"]         # nessun lead buono perso
    assert res["pass"] is True
