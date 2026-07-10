"""Orchestrazione mattutina con APScheduler (riuso dell'infrastruttura esistente).

Feriali:
  07:30 — Componente D  trigger_monitor   (segnali sugli enti)
  07:45 — Componente A  reply_scanner     (dopo l'aggiornamento dell'export)
  08:00 — Componente B  queue_builder     (bozze del giorno pronte)

Tutti i job girano in DRY-RUN salvo --apply (che abilita le scritture di
scanner e auto-rifornimento — mai l'invio: nessun componente invia email).

Uso:
    python scheduler.py --config config.yaml [--apply]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scheduler mattutino prospecting")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    from apscheduler.schedulers.blocking import BlockingScheduler

    from scanner import reply_scanner
    from triggers import trigger_monitor
    from queue import queue_builder

    apply_flag = ["--apply"] if args.apply else []
    cfg_flag = ["--config", args.config]

    sched = BlockingScheduler(timezone="Europe/Rome")
    sched.add_job(lambda: trigger_monitor.main(cfg_flag),
                  "cron", day_of_week="mon-fri", hour=7, minute=30,
                  id="trigger_monitor")
    sched.add_job(lambda: reply_scanner.main(cfg_flag + apply_flag),
                  "cron", day_of_week="mon-fri", hour=7, minute=45,
                  id="reply_scanner")
    sched.add_job(lambda: queue_builder.main(cfg_flag + apply_flag),
                  "cron", day_of_week="mon-fri", hour=8, minute=0,
                  id="queue_builder")

    print("Scheduler attivo (feriali 07:30 D · 07:45 A · 08:00 B). Ctrl-C per uscire.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
