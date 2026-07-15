"""Matrice V4 — personalizzazione automatica ruolo × società.

Modulo PURO: nessuna dipendenza esterna, nessuna chiamata AI, nessun I/O.
È il cuore della "resa sui nuovi": due assi (ruolo, società) si combinano in
oggetto + corpo email. Usato sia dallo script di rigenerazione una-tantum sia da
`queue/queue_builder.py` a ogni nuova coda.

Firma pubblica:
    build_email(nome, azienda, ruolo) -> (subject, body, tag)
    tag == "{company_key}·{role_cluster}"  (per audit e per la colonna N `Versione`)

Regole tipografiche (garantite da _apply_typography):
- lettera maiuscola dopo ". "
- virgolette curve (niente virgolette dritte)
- niente doppi spazi
- niente segnaposto non risolti

Le evidenze dell'anno guidano i testi: mail lunghe (respiro, non 70 parole),
anti-obiezione "ho già un consulente", aggancio referral, numero fiscale concreto
sull'aliquota giusta.
"""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Firma standard (mittente reale del sistema di prospecting)
# ---------------------------------------------------------------------------
SIGNATURE = (
    "Nicolò Porru\n"
    "Wealth & Insurance Advisor — Generali Italia\n"
    "Tel +39 331 454 8168 · LinkedIn: linkedin.com/in/nicolò-porru"
)

# ---------------------------------------------------------------------------
# Asse RUOLO
# ---------------------------------------------------------------------------
# NB: l'ordine conta. I pattern C sono controllati prima di DIR, così
# "Deputy Director General" (che contiene "director general") cade in C,
# mentre "Deputy Director" (senza "general") cade in DIR.
_ROLE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("C", (
        "director general", "direttore generale", "segretario generale",
        "secretary general", "ceo", "chief executive", "president", "presidente",
        "amministratore delegato", " vp", "vice president", "vicepresident",
        "coo", "cfo", "chief operating", "chief financial",
    )),
    ("DIR", (
        "deputy director", "vice direttore", "director", "direttore",
        "fire chief", "head of", "capo ", "capo-", "dirigente",
        "deputy", "chief",
    )),
    ("QUAD", (
        "coordinator", "coordinatore", "team leader", "responsabile",
        "manager", "officer", "funzionario",
    )),
    ("STAFF", (
        "employee", "impiegato", "impiegata", "assistant", "assistente",
        "analyst", "analista", "specialist", "specialista", "technical",
        "tecnico", "clerk", "operatore",
    )),
]

# Aliquota marginale implicita per l'esempio fiscale, per cluster.
# (percentuale, deduzione-massima-annua in euro come stringa formattata)
_ROLE_FISCAL: dict[str, tuple[int, str]] = {
    "C":     (43, "2.200"),
    "DIR":   (43, "2.280"),
    "QUAD":  (33, "1.750"),
    "STAFF": (23, "1.220"),
}


def role_cluster(ruolo: str) -> str:
    """Classifica il ruolo in C / DIR / QUAD / STAFF (default QUAD)."""
    r = _norm(ruolo)
    for cluster, needles in _ROLE_PATTERNS:
        for n in needles:
            if n in r:
                return cluster
    return "QUAD"


# ---------------------------------------------------------------------------
# Asse SOCIETÀ
# ---------------------------------------------------------------------------
_COMPANY_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("SICUREZZA", (
        "vigili del fuoco", "corpo nazionale", "carabinieri", "arma dei",
        "guardia di finanza", "polizia", "questura", "prefettura vvf",
    )),
    ("PARTECIPATA", (
        "sace", "gse", "sogei", "rai", "enit", "aeroitalia", "astral",
        "invitalia", "cdp", "cassa depositi",
    )),
    ("ORGINT", (
        "maeci", "esteri", "affari esteri", "ministry of foreign",
        "wfp", "world food", "fao", "ifad", "giz", "idlo", "unido",
        "united nations", "nazioni unite", "unicef", "unhcr", "iom", "oim",
    )),
    ("BANCA", (
        "mps", "monte dei paschi", "intesa", "sanpaolo", "unicredit",
        "bnl", "bnp", "banca", "bank", "bper", "mediobanca",
    )),
    ("PA", (
        "regione", "ministero", "ministeri", "comune", "citta metropolitana",
        "città metropolitana", "provincia", "inps", "inail", "istat",
        "agenzia delle entrate", "asl", "azienda sanitaria", "universita",
        "università",
    )),
    ("CORP", (
        "fendi", "confcommercio", "confindustria", "s.p.a", "spa",
        "s.r.l", "srl", "group", "holding",
    )),
]


def company_key(azienda: str) -> str:
    """Classifica la società in SICUREZZA / PARTECIPATA / ORGINT / BANCA / PA /
    CORP (default PA)."""
    a = _norm(azienda)
    for key, needles in _COMPANY_PATTERNS:
        for n in needles:
            if n in a:
                return key
    return "PA"


# ---------------------------------------------------------------------------
# Normalizzazione nomi ente per l'oggetto
# ---------------------------------------------------------------------------
# Nomi lunghi/istituzionali → sigla breve leggibile.
_ENTE_SHORT: list[tuple[str, str]] = [
    ("affari esteri", "MAECI"),
    ("esteri", "MAECI"),
    ("world food", "WFP"),
    ("monte dei paschi", "MPS"),
    ("guardia di finanza", "Guardia di Finanza"),
    ("vigili del fuoco", "Vigili del Fuoco"),
    ("cassa depositi", "CDP"),
]
# sigle già brevi da mantenere maiuscole
_ACRONYMS = {
    "maeci", "wfp", "fao", "ifad", "giz", "idlo", "unido", "enit", "gse",
    "sace", "sogei", "rai", "mps", "bnl", "cdp", "inps", "inail", "istat",
    "asl", "vp", "ceo", "coo", "cfo", "astral",
}


def ente_short(azienda: str) -> str:
    """Restituisce una forma breve e leggibile del nome ente per l'oggetto."""
    a = _norm(azienda)
    for needle, short in _ENTE_SHORT:
        if needle in a:
            return short
    raw = (azienda or "").strip()
    if not raw:
        return "il suo ente"
    if raw.lower() in _ACRONYMS or (raw.isupper() and len(raw) <= 8):
        return raw.upper()
    # nome corto: prima parola significativa, capitalizzata
    first = raw.split()[0]
    if first.lower() in _ACRONYMS:
        return first.upper()
    return first[:1].upper() + first[1:]


# ---------------------------------------------------------------------------
# Hook di apertura per società
# ---------------------------------------------------------------------------
def _company_hook(key: str, ente: str) -> str:
    return {
        "SICUREZZA": (
            f"Chi opera nel comparto sicurezza porta un rischio professionale "
            f"che le coperture standard raramente riconoscono, e le tutele di "
            f"comparto lasciano scoperta la posizione personale."
        ),
        "PARTECIPATA": (
            f"In enti come {ente} il welfare aziendale è di buon livello, ma le "
            f"coperture personali restano spesso ferme a quello che si è "
            f"sottoscritto anni fa."
        ),
        "ORGINT": (
            f"Chi lavora in {ente} ha in genere la posizione previdenziale "
            f"italiana sospesa: i contributi maturano fuori dal circuito INPS e "
            f"il montante che si costruirà in Italia va ricostruito a mano."
        ),
        "BANCA": (
            f"In {ente} il tema previdenziale lo padroneggia già; il punto è più "
            f"tecnico: saturare il plafond di deducibilità che oggi resta quasi "
            f"sempre inutilizzato."
        ),
        "PA": (
            f"Dopo le ultime riforme, in enti come {ente} il gap contributivo "
            f"tra ultimo stipendio e prima pensione si è allargato più di quanto "
            f"le stime interne lascino intendere."
        ),
        "CORP": (
            f"In una realtà come {ente} la priorità è duplice: proteggere il "
            f"reddito nella fase attiva e preparare per tempo il passaggio "
            f"generazionale del patrimonio."
        ),
    }[key]


def _role_cut(cluster: str) -> str:
    """Taglio-ruolo che precede l'aggancio società per C e STAFF."""
    if cluster == "C":
        # apertura C: prosegue in minuscolo dopo "Gentile {Cognome}," (stile
        # epistolare italiano); l'hook società segue con la sua maiuscola.
        return (
            "chi ricopre un ruolo come il suo le decisioni importanti le ha "
            "già prese, e di solito bene. Le scrivo proprio per questo: dal "
            "2026 è cambiato un elemento che, per un profilo come il suo, "
            "tocca due aspetti che di solito pesano più della previdenza in "
            "sé — la protezione del patrimonio e la pianificazione del "
            "passaggio. "
        )
    if cluster == "STAFF":
        return (
            "Le scrivo perché è proprio sulle posizioni operative che i piccoli "
            "aggiustamenti fatti per tempo pesano di più nel lungo periodo. "
        )
    return ""


def _fiscal_paragraph(cluster: str) -> str:
    pct, euro = _ROLE_FISCAL[cluster]
    return (
        f"Un dato concreto: con un'aliquota marginale intorno al {pct}%, ogni "
        f"euro versato sulla previdenza integrativa oggi deducibile — fino a "
        f"circa {euro} euro di risparmio d'imposta l'anno sul massimale — le "
        f"torna indietro come minor tassazione. È il modo più efficiente di "
        f"mettere da parte, e in pochi lo sfruttano davvero."
    )


_ANTI_OBJECTION = (
    "Non voglio in alcun modo sostituire chi la segue già: le propongo un "
    "secondo parere gratuito e riservato, senza impegno. Spesso basta un "
    "confronto per capire se la posizione attuale è ancora quella giusta, o se "
    "qualcosa è cambiato nel frattempo."
)

_CTA = (
    "Le va di sentirci nei prossimi giorni? Le anticipo una sintesi di una "
    "pagina."
)

_REFERRAL = (
    "Se invece pensa che il tema riguardi più un suo collega, mi indichi pure a "
    "chi conviene rivolgermi."
)


# ---------------------------------------------------------------------------
# Oggetto
# ---------------------------------------------------------------------------
def _subject(company: str, role: str, ente: str) -> str:
    if company == "BANCA" and role in ("C", "DIR"):
        return "2.280 euro l'anno, dal 2026"
    if company == "ORGINT":
        return f"La sua posizione previdenziale italiana ({ente})"
    if company == "SICUREZZA":
        return "Previdenza e tutele nel comparto sicurezza"
    return f"Un secondo parere sulla sua posizione previdenziale ({ente})"


# ---------------------------------------------------------------------------
# API pubblica
# ---------------------------------------------------------------------------
def build_email(nome: str, azienda: str, ruolo: str,
                email: str | None = None) -> tuple[str, str, str]:
    """Genera (subject, body, tag) per un lead.

    tag == "{company_key}·{role_cluster}"

    `email` (opzionale) serve solo al saluto: per i nomi ambigui (Andrea,
    Nicola…) il titolo maschile vale su dominio italiano; su dominio estero si
    usa il fallback neutro senza titolo.
    """
    company = company_key(azienda)
    role = role_cluster(ruolo)
    ente = ente_short(azienda)

    subject = _subject(company, role, ente)

    opening = _role_cut(role) + _company_hook(company, ente)
    body_parts = [
        _greeting(nome, email),
        opening,
        _fiscal_paragraph(role),
        _ANTI_OBJECTION,
        _CTA,
        _REFERRAL,
    ]
    body = "\n\n".join(body_parts)

    subject = _apply_typography(subject)
    body = _apply_typography(body)
    # La firma è appesa VERBATIM dopo la tipografia: deve restare identica
    # (numero, LinkedIn, capitalizzazione) in ogni mail.
    body = f"{body}\n\n{SIGNATURE}"
    tag = f"{company}·{role}"
    return subject, body, tag


# ---------------------------------------------------------------------------
# Helper interni
# ---------------------------------------------------------------------------
def _norm(s: str | None) -> str:
    """lowercase + rimozione accenti, per matching robusto."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def _cognome(nome: str | None) -> str:
    """[Cognome] = ultima parola del Nome."""
    if not nome or not nome.strip():
        return "Dottore"
    return nome.strip().split()[-1]


# ---------------------------------------------------------------------------
# Genere dal nome di battesimo (per il saluto)
# ---------------------------------------------------------------------------
# Nomi italiani MASCHILI ma ambigui fuori dall'Italia (Andrea/Nicola femminili
# altrove, Simone femminile in FR/DE, ecc.): maschili SOLO su dominio .it;
# su dominio estero → fallback neutro senza titolo.
_AMBIGUOUS_MALE = {
    "andrea", "simone", "nicola", "daniele", "gabriele", "michele",
    "luca", "mattia", "elia", "emanuele", "raffaele",
}

# Maschili non ambigui (lista di nomi comuni, normalizzati senza accenti).
_MALE = {
    "alessandro", "alessio", "alberto", "aldo", "alfredo", "angelo", "antonio",
    "arturo", "bruno", "carlo", "carmine", "cesare", "ciro", "claudio",
    "corrado", "cristian", "cristiano", "dario", "davide", "diego", "domenico",
    "edoardo", "emilio", "enrico", "enzo", "ettore", "fabio", "fabrizio",
    "federico", "ferdinando", "filippo", "flavio", "francesco", "franco",
    "gaetano", "giacomo", "gianluca", "gianmarco", "gianni", "gino", "giordano",
    "giorgio", "giovanni", "giuliano", "giulio", "giuseppe", "graziano",
    "gregorio", "guido", "ignazio", "jacopo", "leonardo", "lorenzo", "luciano",
    "ludovico", "luigi", "manuel", "marco", "mariano", "mario", "massimiliano",
    "massimo", "matteo", "maurizio", "mauro", "mirko", "nino", "oreste",
    "orlando", "osvaldo", "ottavio", "paolo", "pasquale", "patrizio", "piero",
    "pietro", "renato", "renzo", "riccardo", "roberto", "rocco", "rodolfo",
    "ruggero", "salvatore", "samuele", "sandro", "sergio", "silvio", "stefano",
    "tommaso", "ubaldo", "umberto", "valerio", "vincenzo", "vito", "vittorio",
    "walter",
}

# Femminili comuni (inclusi quelli in -e come Beatrice, Irene, Agnese).
_FEMALE = {
    "adele", "adriana", "agnese", "alba", "alessandra", "alessia", "alice",
    "ambra", "angela", "anna", "annamaria", "antonella", "arianna", "assunta",
    "aurora", "barbara", "beatrice", "benedetta", "bianca", "bruna", "camilla",
    "carla", "carlotta", "carmela", "caterina", "cecilia", "chiara", "clara",
    "claudia", "cristina", "daniela", "debora", "diana", "donatella", "elena",
    "eleonora", "elisa", "elisabetta", "emanuela", "emma", "enrica", "erica",
    "eugenia", "federica", "fernanda", "fiorella", "flavia", "franca",
    "francesca", "gabriella", "gaia", "gemma", "giada", "gianna", "ginevra",
    "gioia", "giorgia", "giovanna", "giulia", "giuliana", "giuseppina",
    "grazia", "ilaria", "irene", "isabella", "katia", "laura", "letizia",
    "lidia", "liliana", "lina", "linda", "lisa", "livia", "loredana", "lorena",
    "lucia", "luciana", "ludovica", "luisa", "maddalena", "manuela", "mara",
    "marcella", "margherita", "maria", "mariangela", "marina", "marta",
    "martina", "matilde", "melania", "michela", "milena", "mirella", "monica",
    "nadia", "natalia", "nicoletta", "noemi", "ornella", "paola", "patrizia",
    "piera", "raffaella", "rachele", "rebecca", "renata", "rita", "roberta",
    "romina", "rosa", "rosanna", "rossana", "rossella", "sabrina", "samantha",
    "sandra", "sara", "serena", "silvana", "silvia", "simona", "sofia", "sonia",
    "stefania", "susanna", "teresa", "tiziana", "valentina", "valeria",
    "vanessa", "vera", "veronica", "vittoria", "viviana",
}


def _first_name(nome: str | None) -> str:
    """Nome di battesimo = prima parola del campo Nome, normalizzata."""
    if not nome or not nome.strip():
        return ""
    return _norm(nome.strip().split()[0])


def _is_italian_domain(email: str | None) -> bool | None:
    """True se il dominio email è .it, False se estero, None se assente/ignoto."""
    e = (email or "").strip().lower()
    if "@" not in e:
        return None
    dom = e.split("@")[-1]
    if not dom or "." not in dom:
        return None
    return dom.endswith(".it")


def gender(nome: str | None, email: str | None = None) -> str | None:
    """Deduce il genere dal nome di battesimo: 'M', 'F' o None (ignoto/straniero).

    I nomi ambigui (Andrea, Nicola…) sono maschili solo se il dominio è italiano
    o assente; su dominio estero → None (fallback neutro)."""
    first = _first_name(nome)
    if not first:
        return None
    if first in _AMBIGUOUS_MALE:
        return "M" if _is_italian_domain(email) in (True, None) else None
    if first in _MALE:
        return "M"
    if first in _FEMALE:
        return "F"
    return None


def _greeting(nome: str | None, email: str | None = None) -> str:
    """Saluto con genere: 'Buongiorno Dott. Rossi,' / 'Buongiorno Dott.ssa Rossi,'
    oppure, per nomi stranieri/ignoti, 'Buongiorno Nome Cognome,' senza titolo."""
    g = gender(nome, email)
    if g == "M":
        return f"Buongiorno Dott. {_cognome(nome)},"
    if g == "F":
        return f"Buongiorno Dott.ssa {_cognome(nome)},"
    full = (nome or "").strip()
    return f"Buongiorno {full}," if full else "Buongiorno,"


_STRAIGHT_APOS = "'"
_CURLY_APOS = "’"        # '
_CURLY_OPEN = "“"        # "
_CURLY_CLOSE = "”"       # "


def _apply_typography(text: str) -> str:
    """Applica le regole tipografiche non negoziabili.

    - virgolette curve (apostrofi e doppie)
    - maiuscola dopo ". "
    - niente doppi spazi
    """
    # apostrofi dritti -> curvi
    text = text.replace(_STRAIGHT_APOS, _CURLY_APOS)
    # doppie dritte -> curve alternate (apertura/chiusura)
    out = []
    open_next = True
    for ch in text:
        if ch == '"':
            out.append(_CURLY_OPEN if open_next else _CURLY_CLOSE)
            open_next = not open_next
        else:
            out.append(ch)
    text = "".join(out)
    # niente doppi spazi (preserva i newline)
    text = re.sub(r"[ \t]{2,}", " ", text)
    # maiuscola dopo ". "
    text = re.sub(
        r"(\. )([a-zàèéìòùáéíóú])",
        lambda m: m.group(1) + m.group(2).upper(),
        text,
    )
    return text
