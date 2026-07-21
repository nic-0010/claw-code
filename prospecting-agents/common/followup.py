"""Calcolo in Python della maturità follow-up/riprese — indipendente dalle
cache delle formule Excel.

Bug verificato sul campo: dopo un salvataggio via openpyxl i valori cached delle
colonne-formula spariscono, quindi leggere `Tipo azione` (col J, formula) dà
vuoto e il builder vede 0 follow-up. La verità sta nella colonna H `Ultimo
invio` (data, scrivibile): da lì si ricalcola tutto, con le STESSE soglie delle
formule del master.

Formule replicate (foglio "Follow-up e riprese"):
    I `Gg lavorativi` = MAX(NETWORKDAYS(H, TODAY()) - 1, 0)
    J `Tipo azione`   = IF(I<4, "In attesa (<4 gg)",
                          IF(I>25, "Ripresa contatto", "Follow-up standard"))
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

IN_ATTESA = "In attesa (<4 gg)"
FOLLOW_UP = "Follow-up standard"
RIPRESA = "Ripresa contatto"


def _as_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


def networkdays(start: date, end: date) -> int:
    """Come Excel NETWORKDAYS: giorni feriali (lun-ven) tra start e end, estremi
    inclusi. Negativo se end < start."""
    if start == end:
        return 1 if start.weekday() < 5 else 0
    sign = 1
    if end < start:
        start, end, sign = end, start, -1
    days = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            days += 1
        d += timedelta(days=1)
    return sign * days


def gg_lavorativi(ultimo_invio, today: date | None = None) -> int | None:
    """Col I: MAX(NETWORKDAYS(ultimo_invio, today) - 1, 0). None se data assente."""
    d = _as_date(ultimo_invio)
    if d is None:
        return None
    today = today or date.today()
    return max(networkdays(d, today) - 1, 0)


def tipo_azione(ultimo_invio, today: date | None = None) -> str | None:
    """Col J calcolata in Python. None se `Ultimo invio` è vuoto (nessuna azione)."""
    gg = gg_lavorativi(ultimo_invio, today)
    if gg is None:
        return None
    if gg < 4:
        return IN_ATTESA
    if gg > 25:
        return RIPRESA
    return FOLLOW_UP
