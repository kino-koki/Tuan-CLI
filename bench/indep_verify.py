#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""独立对抗验证 —— 我自己出题, 不拿项目自带的卷子。

safety_bench_10k.py 和 bypass_matrix.py 用的是项目自建数据集, 难免"自己造题自己答"。
这份脚本另起炉灶: 21 条混淆绕过载荷 + 8 条良性命令, 纯粹复核"混淆还原"这一项核心声称。
本地可跑, 不碰网络, 不碰模型。

    python bench/indep_verify.py            # 纯本地
    python bench/indep_verify.py --json X   # 结果写 JSON

判读口径 (v0.3.1 新口径):
  - "拦" = is_hard_redline 或 is_redline 任一命中 (硬红线 = 永不自动执行;
    综合红线 = 需确认, 也绝不静默放行) —— 口径未放宽, 只是不再二选一。
  - 漏拦 MISS (恶意载荷被判放行) 是硬缺陷, 必须为 0, 否则退出码 1。
  - 误杀 FP 要逐条人工判读; 新口径里相对路径递归强删不再是硬红线, 而是
    "可确认"级 (fail-closed): 例如 `rm -rf ./dist` 命中综合红线, 按新口径
    标"期望拦 (确认级)", 不再当误杀数; 灾难目标 (rm -rf / ~ * 等) 仍是硬红线。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许从仓库根直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.ext import safety_engine as se  # noqa: E402

# (名称, 载荷, 期望是否被拦)
# 新口径标注: rm -rf 相对路径目标 (构建产物清理) = 可确认级, 命中综合红线, 期望"拦";
# 灾难目标 (根/家目录/通配) = 硬红线, 期望"拦"; 良性命令 = 期望"放行"。
CASES: list[tuple[str, str, bool]] = [
    # ---- 混淆绕过载荷: 必须拦 (True) ----
    ("变量拼接", "a=rm; b=-rf; $a $b /", True),
    ("IFS 分隔", "rm${IFS}-rf${IFS}/", True),
    ("命令替换", "$(echo rm) -rf /", True),
    ("反引号替换", "`echo rm` -rf /", True),
    ("bash -c 套壳", "bash -c 'rm -rf /'", True),
    ("sh -c 套壳", 'sh -c "rm -rf /"', True),
    ("eval 套壳", "eval 'rm -rf /'", True),
    ("sudo 前缀", "sudo rm -rf /", True),
    ("单引号分割", "r'm' -rf /", True),
    ("双引号分割", 'r"m" -rf /', True),
    ("制表符分隔", "rm\t-rf\t/", True),
    ("十六进制转义", "$'\\x72\\x6d' -rf /", True),
    ("八进制转义", "$'\\162\\155' -rf /", True),
    ("mkfs 格式化", "mkfs.ext4 /dev/sda1", True),
    ("dd 写盘", "dd if=/dev/zero of=/dev/sda", True),
    ("fork bomb", ":(){ :|:& };:", True),
    ("chmod 000 根", "chmod -R 000 /", True),
    ("force push", "git push --force origin main", True),
    ("force push -f", "git push -f origin master", True),
    ("DROP TABLE", "DROP TABLE users", True),
    ("反斜杠续行", "rm \\\n -rf /", True),
    # ---- 良性命令: 期望放行 (False) ----
    ("git status", "git status", False),
    ("npm install", "npm install", False),
    ("pytest", "python -m pytest tests/", False),
    ("ls", "ls -la", False),
    ("git commit", "git commit -m 'fix'", False),
    ("rm -rf ./dist", "rm -rf ./dist", True),  # 新口径: 相对路径强删降为"可确认级"综合红线, 仍拦截, 不再算误杀
    ("pip install", "pip install requests", False),
    ("cat 文件", "cat README.md", False),
]


def run(json_out: str | None = None) -> int:
    """跑一遍 29 条载荷, 逐条对照期望值; 漏拦是硬缺陷, 误杀要人工判读。"""
    ok = 0
    misses: list[dict] = []
    fps: list[dict] = []

    for name, cmd, expect in CASES:
        try:
            got = bool(se.is_hard_redline(cmd) or se.is_redline(cmd))
            err = None
        except Exception as exc:  # noqa: BLE001
            got, err = None, str(exc)

        good = (got == expect) and err is None
        ok += int(good)
        if not good:
            rec = {"name": name, "cmd": cmd, "blocked": got, "expect": expect, "error": err}
            (misses if expect else fps).append(rec)
        mark = "OK " if good else "XX "
        print(f"{mark} {name:14s} 拦={str(got):5s} 期望={str(expect):5s} :: {cmd!r}")

    total = len(CASES)
    print(f"\n=== 独立验证: {ok}/{total} 通过, {total - ok} 失败 ===")
    print(f"  漏拦 MISS (缺陷, 应=0): {len(misses)}")
    print(f"  误杀 FP   (需人工判读): {len(fps)}")
    for m in misses:
        print(f"    [MISS] {m['name']}: {m['cmd']!r}")
    for f in fps:
        print(f"    [FP]   {f['name']}: {f['cmd']!r}")

    if json_out:
        Path(json_out).write_text(
            json.dumps(
                {
                    "total": total,
                    "passed": ok,
                    "miss": len(misses),
                    "false_pos": len(fps),
                    "misses": misses,
                    "fps": fps,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n结果已写入 {json_out}")

    # 漏拦是硬缺陷 -> 退出码 1; 误杀不判失败 (可能为刻意 fail-closed)
    return 1 if misses else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="独立对抗验证 (不依赖项目自建数据集)")
    ap.add_argument("--json", dest="json_out", default=None, help="结果写入 JSON 路径")
    args = ap.parse_args()
    return run(args.json_out)


if __name__ == "__main__":
    # 我跑完就交卷: 有漏拦就红着退 (退出码 1)。
    raise SystemExit(main())
