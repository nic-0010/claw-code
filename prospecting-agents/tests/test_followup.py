"""Test del calcolo maturità follow-up in Python (common/followup)."""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import followup as f  # noqa: E402

TODAY = date(2026, 7, 10)   # venerdì


def test_networkdays_base():
    # lun-ven stessa settimana
    assert f.networkdays(date(2026, 7, 6), date(2026, 7, 10)) == 5
    # weekend escluso: ven→lun = 2 (ven, lun)
    assert f.networkdays(date(2026, 7, 10), date(2026, 7, 13)) == 2
    # stesso giorno feriale
    assert f.networkdays(TODAY, TODAY) == 1
    # sabato singolo
    assert f.networkdays(date(2026, 7, 11), date(2026, 7, 11)) == 0


def test_gg_lavorativi_replica_formula():
    # MAX(NETWORKDAYS(H,TODAY())-1, 0)
    assert f.gg_lavorativi(datetime(2026, 7, 10), TODAY) == 0     # stesso giorno
    assert f.gg_lavorativi(datetime(2026, 6, 25), TODAY) == 11
    assert f.gg_lavorativi(datetime(2026, 5, 20), TODAY) == 37
    assert f.gg_lavorativi(None, TODAY) is None
    assert f.gg_lavorativi("", TODAY) is None


def test_tipo_azione_soglie():
    assert f.tipo_azione(datetime(2026, 7, 9), TODAY) == f.IN_ATTESA      # gg 0 (<4)
    assert f.tipo_azione(datetime(2026, 6, 25), TODAY) == f.FOLLOW_UP     # gg 11 (4-25)
    assert f.tipo_azione(datetime(2026, 5, 20), TODAY) == f.RIPRESA       # gg 37 (>25)
    assert f.tipo_azione(None, TODAY) is None                            # nessuna azione


def test_tipo_azione_confine_esatto():
    # gg == 4 → follow-up (non più "in attesa"); gg == 25 → follow-up; gg == 26 → ripresa
    # troviamo date che danno esattamente quei gg lavorativi
    def with_gg(target):
        d = TODAY
        # cammina indietro finché gg_lavorativi raggiunge target
        from datetime import timedelta
        while f.gg_lavorativi(datetime.combine(d, datetime.min.time()), TODAY) < target:
            d = d - timedelta(days=1)
        return datetime.combine(d, datetime.min.time())
    assert f.tipo_azione(with_gg(4), TODAY) == f.FOLLOW_UP
    assert f.tipo_azione(with_gg(25), TODAY) == f.FOLLOW_UP
    assert f.tipo_azione(with_gg(26), TODAY) == f.RIPRESA


def test_as_date_formati():
    assert f._as_date(datetime(2026, 7, 10, 9, 0)) == date(2026, 7, 10)
    assert f._as_date(date(2026, 7, 10)) == date(2026, 7, 10)
    assert f._as_date("2026-07-10") == date(2026, 7, 10)
    assert f._as_date("10/07/2026") == date(2026, 7, 10)
    assert f._as_date(None) is None
    assert f._as_date("non una data") is None
