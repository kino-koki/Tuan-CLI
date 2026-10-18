#!/usr/bin/env python3
"""示例 2/3 —— 生态互操作演示: 探测本机 Claude Code / Hermes 资产 (只读)。

场景: 展示「不重复造生态」——tuan 能发现本机其他 Agent CLI (Claude Code /
Hermes Agent) 已积累的技能 / 命名 Agent / 记忆 / MCP 配置, 并双向搬运。

运行::

    python examples/ecosystem_scan.py

注意: 纯只读探测。未安装 Claude Code / Hermes 时输出「未发现」, 属正常。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(args: list[str]) -> str:
    """调用仓库内 CLI (优先 .venv, 否则系统 tuan)。"""
    candidates = [
        [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "tuan_cli", *args],
        ["tuan", *args],
    ]
    last_err = ""
    for cmd in candidates:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                                 cwd=ROOT)
            if out.returncode == 0:
                return out.stdout
            last_err = out.stderr
        except FileNotFoundError:
            continue
    return f"(调用失败: {last_err[-300:]})"


def main() -> int:
    print("=== 青小团 · 生态互操作探测 (只读) ===\n")
    # 1) 全量探测: Claude Code / Hermes 安装状态 + 技能 / Agent / 记忆 / MCP 资产
    print(run(["ecosystem", "scan"]))
    # 2) 已发现的技能会直接进入 tuan 的技能搜索路径 —— 本机装过即用
    print("说明: 探测到的技能 / Agent / 记忆 / MCP 配置可用以下命令双向搬运:")
    print("  tuan ecosystem import all        # 拉入 tuan")
    print("  tuan ecosystem export skills --to claude   # 推回 Claude Code")
    print("  tuan ecosystem link               # 反向挂载 (Claude Code 调用 tuan)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
