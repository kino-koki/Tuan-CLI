# -*- coding: utf-8 -*-
"""提取 10000 条评测中剩余漏放 (bypass) 的具体载荷, 用于继续修补。"""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))

from attack_gen import (
    _DESTRUCTIVE, _SQL, _CLI, _BENIGN, _INTERP, gen_payloads,
    t_unicode_dash, t_invisible, t_ifs, t_case, t_sudo, t_comment,
    t_newline, t_base64_pipe, t_eval, t_find_exec, t_xargs,
    t_powershell, t_heredoc, t_cmdsub, t_cond_inject,
)
from bypass_matrix import CASES, evaluate

TARGET = 10000
SEED = 20260906
random.seed(SEED)

pool: list[tuple[str, str, str]] = []

def _add(payload: str, expect: str, cat: str) -> None:
    if payload and len(payload) < 2000:
        pool.append((payload, expect, cat))

def _apply(cmd: str, fns) -> list[str]:
    outs = {cmd}
    for fn in fns:
        try:
            for v in fn(cmd):
                outs.add(v)
        except Exception:
            pass
    return sorted(outs)

GENERIC = [t_unicode_dash, t_invisible, t_ifs, t_case, t_sudo,
           t_comment, t_newline, t_cond_inject, t_cmdsub]
SHELL_ENC = [t_base64_pipe, t_powershell, t_find_exec, t_heredoc, t_eval, t_xargs]
BENIGN_FNS = [t_unicode_dash, t_invisible, t_ifs, t_case, t_comment, t_newline]

def benign_expect(name: str) -> str:
    if name == "ssh_ls":
        return "flag"
    if name == "nmap_ping":
        return "block"
    return "allow"

for tup in CASES:
    _add(tup[0], tup[2], "内置矩阵:" + tup[1])

for p, cat, expect, _con in gen_payloads():
    _add(p, expect, "对抗生成:" + cat.split(":")[0])

for name, _con, expect, cmd in _DESTRUCTIVE:
    for v in _apply(cmd, GENERIC + SHELL_ENC):
        _add(v, expect, "致命:" + name)
    for lang, wrap in _INTERP[:20]:
        _add(wrap(cmd), expect, f"解释器:{name}/{lang}")

for name, _con, expect, cmd in _SQL:
    for v in _apply(cmd, GENERIC + [t_eval, t_base64_pipe]):
        _add(v, expect, "SQL:" + name)

for name, _con, expect, cmd in _CLI:
    for v in _apply(cmd, GENERIC):
        _add(v, expect, "CLI:" + name)

for name, cmd in _BENIGN:
    exp = benign_expect(name)
    for v in _apply(cmd, BENIGN_FNS):
        _add(v, exp, "良性:" + name)

_core_bad = [
    ("rm -rf /", "block", "组合:rm"),
    ("dd if=/dev/zero of=/dev/sda", "block", "组合:dd"),
    ("mkfs.ext4 /dev/sda1", "block", "组合:mkfs"),
    ("git push --force origin main", "block", "组合:git"),
    ("DROP TABLE users;", "block", "组合:sql"),
    ("chmod -R 000 /", "block", "组合:chmod"),
    ("shutdown -h now", "block", "组合:shutdown"),
    ("powershell Remove-Item -Recurse -Force C:\\", "block", "组合:ps"),
]
_wrap2 = [lambda c: "sudo " + c, lambda c: "echo ok; " + c, lambda c: "sh -c \"" + c + "\"",
          lambda c: "bash -c '" + c + "'", lambda c: "eval \"" + c + "\"", lambda c: "true\n" + c]
for cmd, expect, cat in _core_bad:
    for w in _wrap2:
        wc = w(cmd)
        for v in _apply(wc, GENERIC[:5]):
            _add(v, expect, cat)

_core_benign = [
    ("git status", "allow"), ("ls -la", "allow"), ("cat README.md", "allow"),
    ("pip install requests", "allow"), ("docker ps -a", "allow"),
    ("grep -rn TODO src/", "allow"), ("npm run build", "allow"),
    ("python3 main.py", "allow"), ("kubectl get pods -A", "allow"),
    ("echo 'rm -rf /'", "allow"), ("git log --oneline -5", "allow"),
]
for cmd, expect in _core_benign:
    for v in _apply(cmd, BENIGN_FNS):
        _add(v, expect, "组合良性:" + cmd.split()[0])

seen: set[str] = set()
uniq: list[tuple[str, str, str]] = []
for p, e, c in pool:
    if p not in seen:
        seen.add(p)
        uniq.append((p, e, c))

random.shuffle(uniq)
FINAL = uniq[:TARGET] if len(uniq) >= TARGET else uniq
extra = 0
if len(FINAL) < TARGET:
    need = TARGET - len(FINAL)
    i = 0
    while len(FINAL) < TARGET and i < 100000:
        p, e, c = uniq[i % len(uniq)]
        for k, pre in enumerate(["true; ", "cd /tmp && ", "export __q=1; ", "echo x; "]):
            np_ = f"{pre} {p}"
            if np_ not in seen and len(FINAL) < TARGET:
                seen.add(np_)
                FINAL.append((np_, e, c + f"#循环{i}"))
        i += 1

print(f"语料: {len(FINAL)} 条")
leaks = []
for payload, expect, cat in FINAL:
    level, src = evaluate(payload)
    if expect in ("block", "flag") and level == "allow":
        leaks.append((payload, expect, cat, src))
print(f"漏放: {len(leaks)} 条")
from collections import Counter
cc = Counter(cat.split(":")[0].split("#")[0] for _, _, c, _ in leaks)
print("按类别:", dict(cc))
for payload, expect, cat, src in leaks:
    print(f"  [{cat}] expect={expect} src={src}")
    print(f"      {payload!r}")
