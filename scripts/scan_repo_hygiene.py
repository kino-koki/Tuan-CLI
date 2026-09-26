"""仓库开源卫生扫描: 敏感信息 / 可疑文件 / 超大二进制 / 异常路径。

用于发布到 GitHub 前的一次性检查 (不提交到仓库本体, 由调用方决定是否保留)。
"""
import re
import sys
import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 已跟踪文件 (git ls-files)
import subprocess
tracked = subprocess.run(
    ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True
).stdout.splitlines()

# 1) 敏感信息
SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{16,}|api[_-]?key[\"'=: ]{1,4}[A-Za-z0-9_-]{12,}"
    r"|password[\"'=: ]{1,4}[A-Za-z0-9!@#$%^&*_-]{8,}"
    r"|secret[\"'=: ]{1,4}[A-Za-z0-9_-]{12,}"
    r"|Bearer\s+[A-Za-z0-9._-]{16,})"
)
SKIP_EXT = {".md", ".pyc", ".lock", ".json", ".schema.json"}
SKIP_GLOB = ["tests/*", "*.example", "config.schema.json",
             "bench/*.json", "README*", "CHANGELOG*", "NOTICE"]

def _skip(p: str) -> bool:
    if any(fnmatch.fnmatch(p, g) for g in SKIP_GLOB):
        return True
    return Path(p).suffix in SKIP_EXT and not p.endswith(".schema.json")

hits = []
for p in tracked:
    if _skip(p):
        continue
    fp = ROOT / p
    try:
        text = fp.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    for i, line in enumerate(text.splitlines(), 1):
        if SECRET_RE.search(line):
            hits.append(f"{p}:{i}: {line.strip()[:120]}")

print("=== 1) 疑似敏感信息 (已跟踪代码, 排除 md/测试/example) ===")
print("\n".join(hits) if hits else "(无)")

# 2) 超大二进制/文件
print("\n=== 2) 已跟踪超大文件 (>2MB) ===")
big = []
for p in tracked:
    fp = ROOT / p
    if fp.is_file() and fp.stat().st_size > 2 * 1024 * 1024:
        big.append(f"{p}: {fp.stat().st_size/1024:.0f} KB")
print("\n".join(big) if big else "(无)")

# 3) 已跟踪但应忽略的运行时/构建产物
print("\n=== 3) 已跟踪的运行时/构建/临时文件 (应 gitignore) ===")
suspect = []
for p in tracked:
    low = p.lower()
    if (".pytest" in low or ".venv" in low or "egg-info" in low
            or low.endswith(".log") or "/__pycache__/" in low
            or low.startswith(".qxt/") or low.startswith("sessions/")
            or low.startswith("audit/") or low.startswith("memories/")
            or low.startswith("cron/") or low.startswith("12345/")):
        suspect.append(p)
print("\n".join(suspect) if suspect else "(无)")

# 4) 非代码顶层文件清单 (供核对)
print("\n=== 4) 顶层文件 ===")
for f in sorted(x.name for x in ROOT.iterdir() if x.is_file()):
    print(f"  {f}")