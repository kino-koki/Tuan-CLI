"""`qxt compact --verify` —— compact 后存活状态自检 (对标 Claude Code 压缩契约)。

只读: 不执行压缩, 只检查哪些状态能从磁盘/服务重建, 输出报告。
实际的 /compact 对话压缩仍在聊天会话内由 ContextManager 完成。
"""

from __future__ import annotations

import argparse
from pathlib import Path


def cmd_compact(args: argparse.Namespace) -> int:
    from ..config.loader import Config
    from .runtime.session.compact_survival import build_survival_report

    config = Config()
    workspace = str(Path(getattr(args, "workspace", None) or ".")).resolve()

    if getattr(args, "verify", False):
        report = build_survival_report(
            home=config.home,
            workspace=workspace,
            config=config,
            memory_store=None,
            skill_manager=None,
        )
        print(report)
        return 0

    # 未带 --verify: 给出用法提示 (真正的压缩在交互式会话内用 /compact)。
    print("compact 上下文压缩请在交互式会话内输入 /compact。")
    print("如需检查「压缩后哪些状态能从磁盘重建」, 运行: qxt compact --verify")
    return 0
