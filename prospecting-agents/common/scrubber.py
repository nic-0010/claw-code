"""PII scrubbing — per l'UNICO uso Groq ammesso (spec § Regole trasversali #1).

Groq può ricevere SOLO testi già anonimizzati con questo scrubber. La
classificazione dei corpi email resta comunque su Ollama locale; questo modulo
serve ai soli casi in cui un testo, già ripulito, può uscire dalla macchina.

`scrub(text) -> (testo_anonimizzato, mappa)` dove la mappa consente il
re-inserimento locale dei placeholder DOPO la risposta del modello cloud.
"""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d .\-]{7,}\d)(?!\d)")
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
_CF_RE = re.compile(r"\b[A-Z]{6}\d{2}[A-EHLMPRST]\d{2}[A-Z]\d{3}[A-Z]\b", re.I)


def scrub(text: str) -> tuple[str, dict[str, str]]:
    """Sostituisce email/telefoni/IBAN/codici fiscali con placeholder.

    Ritorna (testo_pulito, mappa placeholder->valore_originale).
    """
    mapping: dict[str, str] = {}
    counters: dict[str, int] = {}

    def _sub(kind: str, pattern: re.Pattern, s: str) -> str:
        def repl(m: re.Match) -> str:
            counters[kind] = counters.get(kind, 0) + 1
            key = f"[{kind}_{counters[kind]}]"
            mapping[key] = m.group(0)
            return key
        return pattern.sub(repl, s)

    out = text
    out = _sub("EMAIL", _EMAIL_RE, out)
    out = _sub("IBAN", _IBAN_RE, out)
    out = _sub("CF", _CF_RE, out)
    out = _sub("TEL", _PHONE_RE, out)
    return out, mapping


def unscrub(text: str, mapping: dict[str, str]) -> str:
    """Reinserisce i valori originali (in locale, dopo il modello cloud)."""
    for key, val in mapping.items():
        text = text.replace(key, val)
    return text
