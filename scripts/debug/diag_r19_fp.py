"""快速诊断: ln -s / nmap -sn 误杀根因。"""
import sys
sys.path.insert(0, "g:/Tuan-CLI")
from tuan_cli.ext import safety_patterns as sp
from tuan_cli.ext.safety_redline import is_hard_redline
import re

cases = [
    "ln -s /usr/local/bin/app /usr/bin/app",
    "ln -sf /usr/local/bin/python3 /usr/bin/python",
    "nmap -sn 192.168.1.0/24",
    "nmap -p 80 example.com",
    "crontab -e",
    "echo 'x' | crontab -",
    "crontab /tmp/x",
    "cat /etc/crontab",
]
for c in cases:
    pt = sp._mask_mentioned_literals(c)
    for name, arr in [("C", sp._CRITICAL_PATTERNS), ("H", sp._HIGH_PATTERNS), ("M", sp._MEDIUM_PATTERNS)]:
        for p, label in arr:
            try:
                if re.search(p, pt, re.IGNORECASE):
                    print(f"{name} | HARD={is_hard_redline(c)} | {c[:50]}")
                    print(f"     -> {label}")
                    break
            except re.error:
                continue
        else:
            continue
        break
    else:
        print(f"? | HARD={is_hard_redline(c)} | {c[:50]}")
