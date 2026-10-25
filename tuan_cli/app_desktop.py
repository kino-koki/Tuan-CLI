# -*- coding: utf-8 -*-
"""Tuan 桌面客户端专用入口（由 Tauri ShellCommand 直接启动）。

与 CLI 的 `tuan web` 同核，但:
  1. 跳过 argparse —— host/port/workspace 由 Tauri 通过环境变量直接注入
     (TUAN_ENGINE_PORT / TUAN_WORKSPACE / TUAN_PROFILE)
  2. 自动探测端口占用并避让 —— 桌面 App 无命令行提示, 直接选下一个可用端口
  3. 后台静默运行 —— banner 打印到 stderr 供 Tauri 捕获, 不阻塞

启动: python -m tuan_cli.app_desktop
或:   python -c "from tuan_cli.app_desktop import main; main()"

Tauri shell_command 推荐配置:
  TUAN_WORKSPACE="用户工作区绝对路径"
  TUAN_ENGINE_PORT=8137   (默认, 被占时自动 +1 直到找到)
  TUAN_PROFILE=default    (配置 profile, 对应 ~/.tuan/ 下的 profile 目录)
  PYTHONUNBUFFERED=1      (保证 stdout/stderr 实时送到 Tauri)
"""
from __future__ import annotations

import logging
import os
import socket
import sys
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# 桌面端专用的额外环境变量约定
ENV_WORKSPACE = "TUAN_WORKSPACE"
ENV_PORT = "TUAN_ENGINE_PORT"
ENV_PROFILE = "TUAN_PROFILE"
ENV_HOST = "TUAN_ENGINE_HOST"


def _is_port_free(port: int, host: str = "127.0.0.1") -> bool:
    """尝试绑定端口, 成功则释放并返回 True (跨平台兼容)。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _find_free_port(start: int, max_tries: int = 20, host: str = "127.0.0.1") -> int:
    """从 start 开始线性探测, 返回第一个可用端口。"""
    for offset in range(max_tries):
        p = start + offset
        if _is_port_free(p, host):
            return p
    raise RuntimeError(f"端口 {start}-{start + max_tries - 1} 全部被占用")


def main(argv: Optional[list[str]] = None) -> int:
    """桌面入口: 环境变量驱动, 无 argparse。

    Tauri 直接 `python -m tuan_cli.app_desktop` 启动。
    若想快速调试, 也支持 argv 形式:  python -m tuan_cli.app_desktop --port 8137 --workspace /path
    """
    # --- 1. 解析参数 (环境变量优先; 支持少量 argv 方便调试) ---
    port = int(os.environ.get(ENV_PORT, "8137"))
    host = os.environ.get(ENV_HOST, "127.0.0.1")
    workspace = os.environ.get(ENV_WORKSPACE, "").strip()
    profile = os.environ.get(ENV_PROFILE, "default")

    # 调试用 argv: --port / --workspace / --profile
    if argv is None:
        argv = sys.argv[1:]
    it = iter(argv)
    for tok in it:
        if tok in ("--port", "-p"):
            port = int(next(it))
        elif tok == "--workspace":
            workspace = next(it)
        elif tok == "--profile":
            profile = next(it)
        elif tok in ("--host", "-H"):
            host = next(it)

    # --- 2. 端口自动避让 ---
    if not _is_port_free(port, host):
        original = port
        port = _find_free_port(port + 1, host=host)
        sys.stderr.write(f"[tuan-desktop] 端口 {original} 被占用, 改用 {port}\n")

    # --- 3. 解析 workspace ---
    if workspace:
        ws_path = Path(workspace).expanduser().resolve()
        ws_path.mkdir(parents=True, exist_ok=True)
        workspace = str(ws_path)
    else:
        from .paths import default_workspace
        workspace = default_workspace()

    # --- 4. 构建 kernel + web server (复用 cmd_web 逻辑) ---
    try:
        from .app import build_kernel
        from .web import WebServer
        from . import __version__

        kernel = build_kernel(profile)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[tuan-desktop] kernel 构建失败: {exc}\n")
        return 1

    config = kernel.require("config")
    provider = config.get("model.provider", "unknown")
    model = config.get("model.model", "unknown")

    server = WebServer(
        kernel,
        workspace,
        host=host,
        port=port,
        model_label=f"{provider}/{model}",
        engine_label=f"tuan_cli v{__version__} (desktop)",
    )

    # --- 5. 启动 banner (stderr 供 Tauri 捕获) ---
    banner = (
        f"[tuan-desktop] 引擎就绪 · http://{host}:{port}\n"
        f"[tuan-desktop] workspace = {workspace}\n"
        f"[tuan-desktop] model = {provider}/{model}\n"
    )
    sys.stderr.write(banner)
    sys.stderr.flush()

    # 把实际端口写回环境变量 (Tauri 后续可以读回来)
    os.environ[ENV_PORT] = str(port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("[tuan-desktop] 收到中断信号, 退出\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
