"""诊断: nmap example.com / ln -s 误杀命中哪条规则。"""
import sys
sys.path.insert(0, "g:/Tuan-CLI")
from tuan_cli.ext import safety_patterns as sp
from tuan_cli.ext.safety_redline import _mask_mentioned_literals
import re

cases = [
    "nmap -p 80 example.com",
    "nmap -sn 192.168.1.0/24",
    "ln -s /usr/local/bin/app /usr/bin/app",
]
for c in cases:
    pt = _mask_mentioned_literals(c)
    found = []
    for name, arr in [("C", sp._CRITICAL_PATTERNS), ("H", sp._HIGH_PATTERNS), ("M", sp._MEDIUM_PATTERNS)]:
        for p, label in arr:
            try:
                if re.search(p, pt, re.IGNORECASE):
                    found.append(f"{name}:{label[:40]}")
            except re.error:
                continue
    print(f"[{c[:45]}]")
    for f in found:
        print(f"    {f}")
