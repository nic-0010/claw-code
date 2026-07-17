# CLAUDE.md — prospecting-agents

Prima di ogni task leggi e rispetta la specifica tecnica del sistema
(`specifica_claude_code.md`, fornita fuori dal repo).

## Regole trasversali NON negoziabili
1. **Privacy**: corpi email e PII dei lead NON lasciano mai la macchina.
   Classificazione testi → Ollama locale. Groq SOLO su testi già anonimizzati
   con `common/scrubber.py`. Nessun dato del master verso API cloud.
2. **Umano nel loop**: nessun componente invia email. Mai. Si producono bozze e report.
3. **Scritture sicure**: prima di ogni modifica al master → backup in `backup/`.
   Mai cancellare righe. Mai scrivere in colonne-formula (vedi
   `common/io_master.FORMULA_COLUMNS`). Ogni run → log JSON in `logs/`.
4. **Dry-run di default**: flag `--apply` esplicito per scrivere davvero.
5. **Eval-first**: prima l'eval set etichettato, poi il codice; niente soglia = niente deploy.
6. **Idempotenza**: rieseguire un componente non crea duplicati né avanzamenti doppi.

## Dati reali fuori dal repo
Il master e ogni dato reale NON sono versionati (vedi `.gitignore`). I path
locali vivono in `config.yaml`, che è **gitignored** (copia da `config.example.yaml`);
così non va mai in conflitto a ogni pull. Il template versionato è `config.example.yaml`.

## Verifica
```
pip install -r requirements.txt
python -m pytest tests/ -q
python -m evals.gen_matrix_snapshots --check   # snapshot V4 allineati
python -m evals.eval_verifier                   # soglie del verificatore
```

## Stato implementazione
- [x] `common/io_master.py` — I/O sicuro (backup, no-formule, idempotenza, dry-run) + test
- [x] `common/email_matrix.py` — Matrice V4 ruolo×società (puro) + 24 snapshot + test
- [x] `verifier/email_verifier.py` — Componente C in dry-run + eval (precision ≥95%)
- [x] `common/scrubber.py`, `common/notify.py`
- [x] Componente A `scanner/reply_scanner.py` + eval (accuracy ≥90%, zero FP su `positiva`)
- [x] Componente B `queue/queue_builder.py` + `queue/lead_refill.py`
- [x] Componente D `triggers/trigger_monitor.py`
- [x] `scheduler.py` — APScheduler feriali 07:30 D · 07:45 A · 08:00 B

Ordine di implementazione dei componenti: **C → A → B → D** (completato).

## Note tecniche
- Il pacchetto `queue/` (nome da spec) ri-esporta le API stdlib in
  `queue/__init__.py`: NON rimuovere quel pass-through, o urllib3/APScheduler
  si rompono quando la root del progetto è in sys.path.
- Lo scanner usa Ollama locale se raggiungibile (`--classifier auto`), con
  fallback euristico deterministico; l'eval gira su entrambi.
- `feedparser` è opzionale: il trigger monitor ha un fallback su xml.etree.
