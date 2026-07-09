"""Test dello scrubber PII (round-trip + copertura tipi)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import scrubber  # noqa: E402


def test_scrub_email_e_roundtrip():
    text = "Scrivi a mario.rossi@acme.it oppure chiama +39 06 12345678."
    clean, mapping = scrubber.scrub(text)
    assert "mario.rossi@acme.it" not in clean
    assert "[EMAIL_1]" in clean
    assert "[TEL_1]" in clean
    assert scrubber.unscrub(clean, mapping) == text


def test_scrub_iban_e_cf():
    text = "IBAN IT60X0542811101000000123456 CF RSSMRA85M01H501Z"
    clean, mapping = scrubber.scrub(text)
    assert "IT60X0542811101000000123456" not in clean
    assert "RSSMRA85M01H501Z" not in clean
    assert scrubber.unscrub(clean, mapping) == text


def test_scrub_niente_pii_invariato():
    text = "Nessun dato personale qui."
    clean, mapping = scrubber.scrub(text)
    assert clean == text
    assert mapping == {}
