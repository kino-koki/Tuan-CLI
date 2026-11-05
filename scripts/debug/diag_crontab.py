"""诊断 crontab 规则修复: 验证读取放行 + 持久化仍拦。"""
import sys
sys.path.insert(0, "g:/Tuan-CLI")
from tuan_cli.ext.safety_redline import is_hard_redline, is_redline
from tuan_cli.ext.safety_score import SafetyEngine

_engine = SafetyEngine()
cases = [
    # 应放行 (读取 crontab 文件)
    ("cat /etc/crontab", "ALLOW"),
    ("cp /etc/crontab /tmp/backup", "ALLOW"),
    ("crontab -l", "ALLOW"),
    ("less /etc/crontab", "ALLOW"),
    # 应拦 (持久化写入)
    ("crontab -e", "block"),
    ("echo '* * * * * /tmp/evil' | crontab -", "block"),
    ("crontab /tmp/malicious", "block"),
    ("crontab -u root /tmp/x", "block"),
]
for cmd, expected in cases:
    if expected == "ALLOW":
        actual = "ALLOW" if not is_hard_redline(cmd) and not is_redline(cmd) else "BLOCK"
    else:
        r = _engine.score({"command": cmd})
        actual = "block" if r.get("risk") in ("critical", "high") else "flag"
    status = "OK" if (expected == "ALLOW" and actual == "ALLOW") or (expected == "block" and actual in ("block", "flag")) else "FAIL"
    print(f"  {status:4} [{expected:5}->{actual:5}] {cmd[:70]}")
