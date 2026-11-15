"""tuan safe 共享底座: 仓库根定位。

所有子命令模块共用这里的路径解析: pip 安装的包里没有 bench/, 只能靠
``TUAN_REPO_ROOT`` 指定; 未指定才回退到「包位置向上三级」。
"""
from __future__ import annotations

import os
from pathlib import Path


def _repo_root() -> Path:
    # 先认环境变量指的路 (pip 装完的包里没有 bench/, 只能靠它);
    # 没设才回退到「我住在哪」的包位置猜测。
    raw = os.environ.get("TUAN_REPO_ROOT")
    if raw:
        p = Path(raw).expanduser().resolve()
        if not p.is_dir():
            raise FileNotFoundError(
                f"环境变量 TUAN_REPO_ROOT={p} 指向的目录不存在, 请改指仓库根 (含 bench/)")
        return p
    return Path(__file__).resolve().parents[3]
