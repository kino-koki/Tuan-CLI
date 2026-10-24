"""仓库卫生自查 (本地可跑版): 用 git 检查跟踪文件是否被 .gitignore 误伤。

不联网、不改动仓库 —— 只报告:
1. 被 git 跟踪、但会被 .gitignore 规则排除的文件 (若重新 clone 会丢)
2. 当前工作区里「应忽略但未忽略」的产物 (会污染提交)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
# git 可执行: 优先 PATH (跨机器可移植, 不依赖固定盘符)
GIT = shutil.which("git") or shutil.which("git.exe")
if not GIT:
    print("ERROR: 未找到 git 可执行文件, 请安装 Git 或将其加入 PATH。")
    sys.exit(1)

run = lambda *a: subprocess.run([GIT, *a], cwd=ROOT, capture_output=True, text=True)

# 1) 已跟踪 + 会被 gitignore 排除 (git check-ignore 对已跟踪文件也做规则匹配)
r = run("git", "ls-files")
tracked = [p for p in r.stdout.splitlines() if p.strip()]
ignored_hits = []
if r.returncode != 0:
    print("(git ls-files 失败, 无跟踪清单可查):", r.stderr.strip()[:200])
else:
    for p in tracked:
        if run("git", "check-ignore", "-q", p).returncode == 0:
            ignored_hits.append(p)

print(f"=== 1) 已跟踪但被 .gitignore 规则命中的文件: {len(ignored_hits)} ===")
for p in ignored_hits:
    print("  ", p)

# 2) 未跟踪且未被忽略 (会出现在 git status 里的候选提交)
r = run("git", "status", "--porcelain")
untracked_dirty = []
for line in r.stdout.splitlines():
    st, path = line[:2], line[3:]
    if st == "??":
        if run("git", "check-ignore", "-q", path).returncode != 0:
            untracked_dirty.append(path)

print(f"\n=== 2) 未跟踪且未被忽略 (可能误提交): {len(untracked_dirty)} ===")
for p in untracked_dirty[:80]:
    print("  ", p)
if len(untracked_dirty) > 80:
    print(f"  ... 其余 {len(untracked_dirty) - 80} 条略")
