"""Genera gli snapshot delle 24 combinazioni ruolo×società della Matrice V4.

Uso:
    python -m evals.gen_matrix_snapshots            # rigenera gli snapshot
    python -m evals.gen_matrix_snapshots --check    # verifica senza scrivere

Gli snapshot vivono in evals/matrix_snapshots/{tag}.txt.
Se cambi un hook di common/email_matrix.py, rigenera DI PROPOSITO
(`python -m evals.gen_matrix_snapshots`) e committa il diff: così nessuna
modifica ai testi sfugge alla review.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import email_matrix as em  # noqa: E402

SNAP_DIR = Path(__file__).resolve().parent / "matrix_snapshots"

# Un rappresentante per ciascun asse → 6 × 4 = 24 combinazioni.
COMPANIES: list[tuple[str, str]] = [
    ("SICUREZZA", "Comando Vigili del Fuoco di Roma"),
    ("PARTECIPATA", "GSE"),
    ("ORGINT", "Ministero degli Affari Esteri e della Cooperazione Internazionale"),
    ("BANCA", "Monte dei Paschi di Siena"),
    ("PA", "Regione Lazio"),
    ("CORP", "Fendi S.p.A."),
]
ROLES: list[tuple[str, str, str]] = [
    ("C", "Director General", "Marina Sacco"),
    ("DIR", "Deputy Director", "Luca Bianchi"),
    ("QUAD", "Responsabile Amministrazione", "Elena Rossi"),
    ("STAFF", "Analyst", "Paolo Verdi"),
]


def render(nome: str, azienda: str, ruolo: str) -> str:
    subject, body, tag = em.build_email(nome, azienda, ruolo)
    return (
        f"TAG: {tag}\n"
        f"INPUT: nome={nome!r} azienda={azienda!r} ruolo={ruolo!r}\n"
        f"SUBJECT: {subject}\n"
        f"---\n"
        f"{body}\n"
    )


def all_snapshots() -> dict[str, str]:
    out: dict[str, str] = {}
    for ck, azienda in COMPANIES:
        for rc, ruolo, nome in ROLES:
            subject, body, tag = em.build_email(nome, azienda, ruolo)
            assert tag == f"{ck}·{rc}", f"tag inatteso: {tag} != {ck}·{rc}"
            out[tag] = render(nome, azienda, ruolo)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="verifica senza scrivere")
    args = ap.parse_args()

    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    snaps = all_snapshots()

    if args.check:
        mismatch = []
        for tag, content in snaps.items():
            p = SNAP_DIR / f"{_safe(tag)}.txt"
            if not p.exists() or p.read_text() != content:
                mismatch.append(tag)
        if mismatch:
            print("SNAPSHOT DIVERGENTI:", ", ".join(mismatch))
            return 1
        print(f"OK: {len(snaps)} snapshot allineati.")
        return 0

    for tag, content in snaps.items():
        (SNAP_DIR / f"{_safe(tag)}.txt").write_text(content)
    print(f"Scritti {len(snaps)} snapshot in {SNAP_DIR}")
    return 0


def _safe(tag: str) -> str:
    return tag.replace("·", "_")


if __name__ == "__main__":
    raise SystemExit(main())
