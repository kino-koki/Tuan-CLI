"""诊断 round18 漏判/误杀。"""
import sys
sys.path.insert(0, "g:/Tuan-CLI")
from tuan_cli.ext.safety_redline import is_hard_redline, is_redline

cases = [
    # 误杀
    "find . -name '*.tmp' -delete",
    "find . -name '*.log' -delete",
    "find . -type f -empty -delete",
    # 漏判
    "find . -name '*.log' -exec rm {} +",
    "find /etc -exec chmod 000 {} ;",
    "kill -STOP 1",
    "service iptables stop",
    "sed -i '/EVIL/d' /var/log/auth.log",
]
for c in cases:
    print(f"HARD={is_hard_redline(c)!s:5} RED={is_redline(c)!s:5} | {c}")
