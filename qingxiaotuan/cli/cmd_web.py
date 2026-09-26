# -*- coding: utf-8 -*-
"""qxt web — 本地 Web 工作台 (DeepSeek-harness 风格)。

启动一个纯标准库的本地服务: 对话流 + 工具调用折叠 + 流式 SSE + 多会话,
无外链 CDN, 断网可用。模型无关, 复用 create_agent 运行时。
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

from ..config import Config
from ..version import __version__

log = logging.getLogger(__name__)


def build_kernel(*a: Any, **k: Any):
    from ..app import build_kernel as _f

    return _f(*a, **k)


def cmd_web(args) -> int:
    """启动本地 Web 工作台。"""
    try:
        kernel = build_kernel(getattr(args, "profile", "default"))
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"Web 工作台启动失败: {exc}\n")
        return 1

    config: Config = kernel.require("config")
    workspace = getattr(args, "workspace", None) or os.getcwd()
    host = getattr(args, "host", None) or "127.0.0.1"
    port = int(getattr(args, "port", 0) or 8090)

    provider = config.get("model.provider", "unknown")
    model = config.get("model.model", "unknown")

    from ..web import WebServer

    server = WebServer(
        kernel, workspace,
        host=host, port=port,
        model_label=f"{provider}/{model}",
        engine_label=f"qingxiaotuan v{__version__}",
    )
    server.serve_forever()
    return 0
