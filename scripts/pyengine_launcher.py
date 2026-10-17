"""PyInstaller 打包入口 —— 生成随 electron 壳内置的 tuan-engine.exe。

桥 (bridge-server.cjs) 以固定 argv 拉起 Python 引擎::

    <exe> -m tuan_cli.stream_json --input-format stream-json ...

本入口负责:
  1. 剥离 `-m tuan_cli.stream_json` 前缀 (PyInstaller exe 无 `-m` 语义);
  2. 把剩余参数原样转交给 stream_json.__main__.main;
  3. 返回与引擎一致的退出码 (2=启动期非法组合, 1=turn 失败, 0=正常退出)。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def main() -> int:
    # PyInstaller onefile 自解压目录加入模块搜索路径 (收集的子模块在 _MEIPASS 内)。
    if _is_frozen():
        sys.path.insert(0, getattr(sys, "_MEIPASS", ""))  # type: ignore[attr-defined]

    argv = list(sys.argv[1:])
    # 桥以 [exe, '-m', 'tuan_cli.stream_json', ...] 调用: 跳过前两个参数。
    if len(argv) >= 2 and argv[0] == "-m" and argv[1] == "tuan_cli.stream_json":
        argv = argv[2:]

    # 工作目录: 桥传 cwd=会话工作区, 引擎回退 os.getcwd() 作为 add-dir。
    # PyInstaller onefile 解压目录不能当 cwd 用 (会污染), 保持桥给的 cwd 即可。

    from tuan_cli.stream_json.__main__ import main as engine_main

    return engine_main(argv)


if __name__ == "__main__":
    sys.exit(main())
