"""Notifiche macOS (best-effort, gratuite). No-op fuori da macOS.

Usato dai componenti per il report a fine run (spec § Componente A/C/D).
"""

from __future__ import annotations

import shutil
import subprocess
import sys


def notify(title: str, message: str) -> bool:
    """Mostra una notifica macOS via osascript. Ritorna True se inviata."""
    if sys.platform != "darwin" or not shutil.which("osascript"):
        return False
    safe_msg = message.replace('"', "'")
    safe_title = title.replace('"', "'")
    script = f'display notification "{safe_msg}" with title "{safe_title}"'
    try:
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
        return True
    except Exception:
        return False
