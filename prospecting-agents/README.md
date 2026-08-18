# prospecting-agents

Automazione a **costo zero** del sistema di prospecting B2B (privacy-first,
umano-nel-loop). Trasforma la mattinata operativa da 45-60 min a ~15: i
componenti producono **bozze e report**, l'umano rilegge e preme invio.

## Componenti (ordine C → A → B → D)

| | Modulo | Scopo | Stato |
|---|---|---|---|
| **C** | `verifier/email_verifier.py` | Abbatte il rimbalzo (~9% → ≤3%): pattern per dominio, MX, SMTP-probe opzionale. Non tocca il master. | ✅ dry-run + eval |
| **A** | `scanner/reply_scanner.py` | Classifica le risposte (deterministico → Ollama locale) e aggiorna il Registro; segnala follow-up/riprese maturi. | ✅ + eval |
| **B** | `queue/queue_builder.py` | Batch giornaliero (split A/B/C, cap, esclusioni) + bozze `.eml` + auto-rifornimento con V4 (mai a secco). | ✅ |
| **D** | `triggers/trigger_monitor.py` | Segnali reali sugli enti (Google News RSS, dedup SQLite) → `trigger_oggi.md`. | ✅ |

## Moduli condivisi
- `common/email_matrix.py` — **Matrice V4** ruolo×società: `build_email(nome, azienda, ruolo) -> (subject, body, tag)`. Modulo puro, nessuna AI, testato a snapshot sulle 24 combinazioni.
- `common/io_master.py` — lettura/scrittura sicura del master: backup automatico, protezione colonne-formula, idempotenza, dry-run di default.
- `common/scrubber.py` — PII scrubbing (unico uso Groq ammesso).
- `common/notify.py` — notifiche macOS.

## Uso rapido
```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml       # adatta i path locali (config.yaml è gitignored)

# Verificatore (Componente C) — dry-run, non tocca il master
python -m verifier.email_verifier --config config.yaml
python -m verifier.email_verifier --config config.yaml --smtp   # probe SMTP prudente
# Applica gli esiti al master: blocca i RISCHIO ALTO, corregge i CORREGGERE (conf ≥0.8)
python -m scripts.applica_verifica --config config.yaml                 # dry-run
python -m scripts.applica_verifica --config config.yaml --apply

# Scanner risposte (Componente A) — dry-run di default
python -m scanner.reply_scanner --config config.yaml
python -m scanner.reply_scanner --config config.yaml --apply

# Queue builder (Componente B) — bozze .eml + riepilogo.html in bozze/YYYYMMDD/
python -m queue.queue_builder --config config.yaml
python -m queue.queue_builder --config config.yaml --apply             # abilita refill
python -m queue.queue_builder --config config.yaml --outlook-drafts    # bozze in Outlook (macOS)
python -m queue.queue_builder --config config.yaml --imap-drafts       # bozze in casella via IMAP (ovunque)
python -m queue.lead_refill  --config config.yaml --apply       # rifornimento archivio

# Registrazione invii del giorno nel Registro (fine mattina)
python -m scripts.log_invii --config config.yaml                        # dry-run
python -m scripts.log_invii --config config.yaml --apply
python -m scripts.log_invii --config config.yaml --escludi a@x.it --apply   # salta non inviate

# Trigger monitor (Componente D) — reports/trigger_oggi.md
python -m triggers.trigger_monitor --config config.yaml

# Orchestrazione mattutina (APScheduler, feriali 07:30/07:45/08:00)
python scheduler.py --config config.yaml

# Matrice V4
python -m evals.gen_matrix_snapshots            # rigenera gli snapshot
python -m evals.gen_matrix_snapshots --check    # verifica stabilità

# Test + eval
python -m pytest tests/ -q
python -m evals.eval_verifier
python -m evals.eval_scanner
```

## Come arrivano le bozze in casella
Il queue builder scrive sempre i `.eml` in `bozze/YYYYMMDD/`: quella è la
sorgente, e da sola basta (i file si trascinano nella cartella Bozze di
qualunque client). Per saltare il passaggio manuale ci sono due strade
alternative, **entrambe opzionali e nessuna delle due invia mai**:

| | Flag | Requisiti | Note |
|---|---|---|---|
| AppleScript | `--outlook-drafts` | macOS + Outlook "classico" | Il **nuovo** Outlook per Mac ha perso gran parte del supporto AppleScript: se fallisce, o si torna al vecchio con il toggle *New Outlook*, o si concede Impostazioni → Privacy → Automazione → Terminale → Outlook. |
| IMAP | `--imap-drafts` | Solo la casella | Nessuna dipendenza da macOS né da Outlook installato. `APPEND` con flag `\Draft`. |

L'IMAP è idempotente: ogni bozza ha un `Message-ID` deterministico (giorno +
destinatario + testo), quindi rilanciare il batch salta quelle già in cartella
invece di duplicarle.

Config in `config.yaml` (blocco `imap:`, vedi `config.example.yaml`). La
password **non si scrive nel file**: si indica il nome della variabile
d'ambiente da cui leggerla.

```bash
export IMAP_PASSWORD='...'        # password o app-password
python -m queue.queue_builder --config config.yaml --imap-drafts
```

Se la config manca o il server non risponde, il comando lo dice e non carica
nulla: i `.eml` su disco restano il fallback.

> `drafts_folder` va scritto **esatto**: su una casella in italiano la cartella
> si chiama `Bozze`, non `Drafts`. Se sbagliato il run si ferma subito con il
> motivo, senza caricare bozze a metà.

## Privacy
Il master e ogni dato reale **non entrano nel repo** (`.gitignore`). Vedi
`CLAUDE.md` per le regole non negoziabili.

L'APPEND IMAP non viola la regola 1: i corpi vanno alla **tua casella**, che è
la destinazione naturale della bozza (esattamente dove la mette
`--outlook-drafts`). Nessuna API cloud di terzi vede il testo.
