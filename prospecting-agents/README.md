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

# Scanner risposte (Componente A) — dry-run di default
python -m scanner.reply_scanner --config config.yaml
python -m scanner.reply_scanner --config config.yaml --apply

# Queue builder (Componente B) — bozze .eml + riepilogo.html in bozze/YYYYMMDD/
python -m queue.queue_builder --config config.yaml
python -m queue.queue_builder --config config.yaml --apply             # abilita refill
python -m queue.queue_builder --config config.yaml --outlook-drafts    # bozze in Outlook (macOS)
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

## Privacy
Il master e ogni dato reale **non entrano nel repo** (`.gitignore`). Vedi
`CLAUDE.md` per le regole non negoziabili.
