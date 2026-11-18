#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性: 按 merge 树重建工作区并重放全部冲突解决 (可重复执行)。"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

MERGED = "798ae9cc8c9a1b40d71d7d9202412b7875812d32"
THEIRS = "b5083de3b4fb0de926adf68503addf363a7359f7"
MINE = "cec40522"
TMP = Path(os.environ["TEMP"], "m3")
TMP.mkdir(exist_ok=True)


def git(*args: str, binary: bool = False):
    r = subprocess.run(["git", *args], capture_output=True)
    return r.stdout if binary else r.stdout.decode("utf-8", errors="replace")


# 1) 以 merge 树重建 index + 工作区 (正确处理删除)
subprocess.run(["git", "read-tree", MERGED], check=True)
subprocess.run(["git", "checkout-index", "-f", "-a"], check=True)
print("[1] 工作区已按 merge 树重建")

# 2) 107 个冲突文件: 逐文件文本级三方合并 (base=740f0763)
out = Path(os.environ["TEMP"], "merge_out.txt").read_text(encoding="utf-8", errors="replace")
stages: dict[str, dict[int, str]] = {}
for m in re.finditer(r"^\d{6} ([0-9a-f]{40}) ([123])\t(.+)$", out, re.M):
    stages.setdefault(m.group(3), {})[int(m.group(2))] = m.group(1)

hand = {"pyproject.toml", "CHANGELOG.md", "docs/parity/CAPABILITY-MATRIX.md",
        "tuan_cli/cli/cmd_slash_bridge.py", "README.md"} | {
        f"README_{l}.md" for l in ["de", "es", "fr", "ja", "ko", "pt-BR", "ru", "zh-CN", "zh-GAT"]}
manual = []
for path, st in sorted(stages.items()):
    if 2 not in st or 3 not in st:
        manual.append(path)  # 删除/修改冲突: 保持我方
        continue
    base = git("cat-file", "blob", st[1], binary=True) if 1 in st else b""
    mine = git("cat-file", "blob", st[2], binary=True)
    theirs = git("cat-file", "blob", st[3], binary=True)
    if base == mine:
        merged = theirs
    elif base == theirs:
        merged = mine
    else:
        (TMP / "b").write_bytes(base)
        (TMP / "m").write_bytes(mine)
        (TMP / "t").write_bytes(theirs)
        r = subprocess.run(["git", "merge-file", "-p", str(TMP / "m"), str(TMP / "b"), str(TMP / "t")],
                           capture_output=True)
        merged = r.stdout
        if r.returncode != 0:
            manual.append(path)
            continue
    Path(path).write_bytes(merged)
print(f"[2] 文本级合并完成, 待人工/取远端 {len(manual)} 个")

# 3) 逐文件解析: 深度探针/钩子/codexkit 簇取远端 (B3 XVI 最新), 其余取我方 (0.4.4 较新)
THEIRS_SET = {
    "tuan_cli/parity_claude/catalog.py", "tuan_cli/parity_claude/depth.py", "tuan_cli/parity_claude/matrix.py",
    "tuan_cli/parity_claude/module_probes.py", "tuan_cli/parity_claude/superiority.py",
    "tuan_cli/tui/parity/depth.py", "tuan_cli/tui/parity/matrix.py",
    "tuan_cli/tui/codexkit/__init__.py", "tuan_cli/tui/codexkit/approval_history.py",
    "tuan_cli/tui/codexkit/stream_exec.py", "tuan_cli/tui/runtime_slogans.py",
    "tuan_cli/hooks/exit_semantics.py", "tuan_cli/hooks/input_validation.py", "tuan_cli/hooks/nonprocess.py",
    "tuan_cli/hooks/manager.py", "tuan_cli/hooks/lifecycle.py", "tuan_cli/hooks/__init__.py",
    "tuan_cli/hooks/triggers.py",
    "tests/test_codexkit_depth.py", "tests/test_b2se_background_side_door.py",
    "tests/test_b3xvi_payload_context_gate.py", "tests/test_b3_hooks_extended.py",
    "tests/test_b3ix_session_transaction.py", "tests/test_b3s_triggers.py", "tests/test_b3v_depth.py",
    "tests/test_b3vi_session_binding.py", "tests/test_b3vii_concurrent_sessions.py",
    "tests/test_b3viii_session_lifecycle.py", "tests/test_b3x_agent_sessions.py",
    "tests/test_b3xii_exit_semantics.py", "tests/test_b3xiii_lifecycle.py",
    "tests/test_b3xiv_lifecycle_safety.py", "tests/test_b3xv_nonprocess_semantics.py",
    "tests/test_hooks.py", "tests/test_hooks_events.py",
}
take_theirs = [p for p in manual if p in THEIRS_SET]
take_mine = [p for p in manual if p not in THEIRS_SET]
for f in take_theirs:
    subprocess.run(["git", "checkout", THEIRS, "--", f], check=True)
for f in take_mine:
    subprocess.run(["git", "checkout", MINE, "--", f], check=True)
print(f"[3] 取远端 {len(take_theirs)} 个 (parity/hooks/codexkit 簇), 取我方 {len(take_mine)} 个")
# 4) 版本一致性: __init__.py 里 0.3.4 -> 0.4.4
init = Path("tuan_cli/__init__.py")
s = init.read_text(encoding="utf-8")
s2 = s.replace("0.3.4", "0.4.4")
if s2 != s:
    init.write_text(s2, encoding="utf-8")
    print("[4] __init__.py 版本 0.3.4 -> 0.4.4")
