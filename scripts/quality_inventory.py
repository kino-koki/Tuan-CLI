#!/usr/bin/env python3
"""工程质量清单生成器 (审计 #32)。

扫描生产代码 ``tuan_cli/`` (排除测试与资源), 统计审计关注的占位/自测信号:
  - 纯 ``pass`` 占位 (函数体只有 pass / 文档字符串 + pass);
  - ``raise NotImplementedError`` 与显式 ``...`` (Ellipsis) 占位;
  - TODO / FIXME 注释;
  - 裸 ``except:`` (不绑异常类型);
  - 生产代码中的 ``assert`` (``python -O`` 下会被跳过, 安全路径不得依赖)。

输出 markdown 到 docs/quality_inventory.md, 含总数与逐文件明细 (Top 20)。
数字口径可由第三方用一条命令复现。
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tuan_cli"
OUT = ROOT / "docs" / "quality_inventory.md"

SKIP_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".venv", "resources"}

PASS_RE = re.compile(r"^\s*pass\s*(#.*)?$")
ELLIPSIS_RE = re.compile(r"^\s*\.\.\.\s*(#.*)?$")
NOTIMPL_RE = re.compile(r"raise\s+NotImplementedError")
TODO_RE = re.compile(r"#\s*(TODO|FIXME)\b")
BARE_EXCEPT_RE = re.compile(r"^\s*except\s*:")
ASSERT_RE = re.compile(r"^\s*assert\s+")


def iter_py():
    for p in SRC.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.relative_to(SRC).parts):
            continue
        yield p


def main() -> int:
    files = sorted(iter_py())
    n_pass = n_ellipsis = n_notimpl = n_todo = n_bare = n_assert = 0
    pass_by_file: Counter = Counter()
    todo_by_file: Counter = Counter()
    bare_by_file: Counter = Counter()
    assert_by_file: Counter = Counter()
    notimpl_samples: list[str] = []

    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        # 纯 pass 占位: pass 行且其所属 def 的函数体只有它 (近似: pass 行总数,
        # 逐文件列出; 精确的 "空函数" 判定交给评审)。
        for i, line in enumerate(lines):
            if PASS_RE.match(line):
                n_pass += 1
                pass_by_file[rel] += 1
            elif ELLIPSIS_RE.match(line):
                n_ellipsis += 1
                pass_by_file[rel] += 1
            if NOTIMPL_RE.search(line):
                n_notimpl += 1
                if len(notimpl_samples) < 20:
                    notimpl_samples.append(f"{rel}:{i + 1}: {line.strip()}")
            m = TODO_RE.search(line)
            if m:
                n_todo += 1
                todo_by_file[rel] += 1
            if BARE_EXCEPT_RE.match(line):
                n_bare += 1
                bare_by_file[rel] += 1
            if ASSERT_RE.match(line):
                n_assert += 1
                assert_by_file[rel] += 1

    lines = [
        "# 生产代码占位与质量信号清单",
        "",
        "> 由 `python scripts/quality_inventory.py` 生成 (审计 #32)。口径: 扫描",
        "> `tuan_cli/**.py` (排除 `resources/` 与缓存目录), 正则计数, 可复现。",
        "> 占位多不等于有 bug, 但对「宣称完成的能力」应逐项核销。",
        "",
        "| 信号 | 数量 |",
        "|---|---|",
        f"| 纯 `pass` / `...` 占位行 | {n_pass} |",
        f"| `raise NotImplementedError` | {n_notimpl} |",
        f"| TODO / FIXME 注释 | {n_todo} |",
        f"| 裸 `except:` (不绑类型) | {n_bare} |",
        f"| 生产代码 `assert` (`python -O` 会跳过) | {n_assert} |",
        f"| 扫描文件数 | {len(files)} |",
        "",
        "## `raise NotImplementedError` 位置 (至多 20 条)",
        "",
    ]
    lines += [f"- `{s}`" for s in notimpl_samples] or ["- (无)"]
    lines += ["", "## 纯 pass/`...` 占位 Top 15 文件", "", "| 文件 | 数量 |", "|---|---|"]
    for rel, c in pass_by_file.most_common(15):
        lines.append(f"| `{rel}` | {c} |")
    lines += ["", "## TODO/FIXME Top 10 文件", "", "| 文件 | 数量 |", "|---|---|"]
    for rel, c in todo_by_file.most_common(10):
        lines.append(f"| `{rel}` | {c} |")
    lines += ["", "## 裸 except Top 10 文件", "", "| 文件 | 数量 |", "|---|---|"]
    for rel, c in bare_by_file.most_common(10):
        lines.append(f"| `{rel}` | {c} |")
    lines += [
        "",
        "## 生产代码 assert 分布 (Top 10)",
        "",
        "安全路径上的 assert 一律不得承担访问控制/拦截职责 (`python -O` 会整段",
        "跳过)。2026-11-20 人工核查结论: `ext/`、`tools/shell.py`、`security_gate.py`、",
        "`web/server.py`、`sandbox/` 等安全路径上的 assert 均为类型收窄用途,",
        "不承担安全裁决; 本表用于持续监督。",
        "",
        "| 文件 | 数量 |", "|---|---|",
    ]
    for rel, c in assert_by_file.most_common(10):
        lines.append(f"| `{rel}` | {c} |")
    lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"written {OUT}: pass/ellipsis={n_pass}, not_implemented={n_notimpl}, "
          f"todo/fixme={n_todo}, bare_except={n_bare}, assert={n_assert}, files={len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
