# -*- coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qingxiaotuan.core.network_guard import NetworkGuard

g = NetworkGuard()
for cmd in ["ssh host", "ssh -T git@github.com", "ssh deploy@host", "ssh host 'ls -la'",
            "nc -zv host 22", "git status", "ssh user@host tail -f /var/log/app.log"]:
    try:
        nd = g.check(cmd)
        print(f"  {cmd!r:50} action={getattr(nd, 'action', '?')}")
    except Exception as e:
        print(f"  {cmd!r:50} ERR {e}")
