"""Pacchetto `queue` del progetto (nome imposto dalla spec § Struttura repo).

ATTENZIONE: il nome oscura il modulo stdlib `queue` quando la root del progetto
è in sys.path (esecuzione con `python -m queue.queue_builder`). Librerie come
urllib3/requests e APScheduler importano `queue` dalla stdlib e si romperebbero.
Per questo ri-esportiamo qui TUTTE le API pubbliche della stdlib: chi importa
`queue` ottiene le classi standard, chi importa `queue.queue_builder` ottiene
il componente.
"""

import importlib.util as _ilu
import os as _os
import sysconfig as _sysconfig

_std_path = _os.path.join(_sysconfig.get_paths()["stdlib"], "queue.py")
_spec = _ilu.spec_from_file_location("_stdlib_queue", _std_path)
_std = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_std)

Queue = _std.Queue
PriorityQueue = _std.PriorityQueue
LifoQueue = _std.LifoQueue
SimpleQueue = _std.SimpleQueue
Empty = _std.Empty
Full = _std.Full
if hasattr(_std, "ShutDown"):          # Python ≥3.13
    ShutDown = _std.ShutDown

__all__ = [n for n in ("Queue", "PriorityQueue", "LifoQueue", "SimpleQueue",
                       "Empty", "Full", "ShutDown") if n in globals()]
