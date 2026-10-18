#!/usr/bin/env python3
"""示例 3/3 —— 离线模型演示: 探测本机 Ollama / llama.cpp 本地模型。

场景: 展示「完全离线、无账号」的用法 —— 模型请求不依赖任何云厂商,
数据不离开本机。未安装本地推理服务时输出「未发现」并给出安装指引。

运行::

    python examples/offline_ollama.py

前提 (可选): 安装 Ollama (ollama.com) 或 llama.cpp 后拉取一个模型,
例如 ``ollama pull qwen2.5:7b``。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(args: list[str]) -> str:
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
    print("=== 青小团 · 本地模型探测 ===\n")
    out = run(["models", "local"])
    print(out)
    print("接入步骤 (探测到模型后):")
    print("  1. tuan models set ollama <模型名>    # 选择本地供应商与模型")
    print("  2. tuan                              # 零网络对话, 密钥都不需要")
    print()
    print("如果显示未发现: 安装 Ollama 后执行 ollama pull qwen2.5:7b 再重试。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
