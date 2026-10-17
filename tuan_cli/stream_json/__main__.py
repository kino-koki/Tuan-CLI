"""CLI 入口（``python -m tuan_cli.stream_json``）—— 对齐 cli.tsx 的 headless argv。

壳（electron/bridge-server.cjs）以固定 argv 拉起本进程::

    --input-format stream-json --output-format stream-json --verbose \
    --include-partial-messages --permission-mode bypassPermissions \
    --permission-prompt-tool stdio --add-dir <dir> --model <id>

参数解析后路由到 ``headless.run_headless``。非法组合直接报错退出（exit 2），
与 TS 端 ``gracefulShutdownSync(1)`` 的启动期报错语义一致。
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from .headless import HeadlessConfig, run_headless

_VALID_PERMISSION_MODES = (
    "bypassPermissions",
    "default",
    "plan",
    "acceptEdits",
    "dontAsk",
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tuan_cli-stream-json",
        description="青小团引擎 headless stream-json 驱动器（供 electron 壳拉起）",
    )
    p.add_argument("--input-format", default="stream-json")
    p.add_argument("--output-format", default="stream-json")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--include-partial-messages", action="store_true")
    p.add_argument("--permission-mode", default="bypassPermissions")
    p.add_argument("--permission-prompt-tool", default=None)
    # 壳只传一个 --add-dir；append 兼容重复出现，取第一个。
    p.add_argument("--add-dir", action="append", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--bare", action="store_true",
                   help="CI/纯净模式：不读用户 config.yaml、不挂 MCP（测试用）")
    # ---- 壳（electron/bridge-server.cjs）固定追加的 argv：必须解析、不得报错 ----
    p.add_argument("--thinking", choices=["enabled", "disabled"], default=None,
                   help="壳固定追加（--thinking enabled|disabled）；当前映射到 thinking_enabled")
    p.add_argument("--resume", default=None,
                   help="壳在续作会话时传（--resume <session_id>）；当前记录 session_id 供续作恢复")
    p.add_argument("--resume-session-at", default=None,
                   help="壳在回滚会话时传（--resume-session-at <uuid>）；当前记录不报错")
    p.add_argument("--append-system-prompt", default=None,
                   help="壳把 UI 自定义 system prompt 传进来，追加到青小团系统提示末尾")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    # ---- 非法组合校验（对齐 TS 启动期报错） ----
    if args.input_format != "stream-json":
        sys.stderr.write(
            f"Error: 本驱动器仅支持 --input-format stream-json"
            f"（收到 {args.input_format!r}）\n"
        )
        return 2
    if args.output_format != "stream-json":
        sys.stderr.write(
            f"Error: 本驱动器仅支持 --output-format stream-json"
            f"（收到 {args.output_format!r}）\n"
        )
        return 2
    if args.permission_mode not in _VALID_PERMISSION_MODES:
        sys.stderr.write(
            f"Error: 未知 --permission-mode {args.permission_mode!r}"
            f"（合法值: {', '.join(_VALID_PERMISSION_MODES)}）\n"
        )
        return 2

    add_dir = args.add_dir[0] if args.add_dir else None

    config = HeadlessConfig(
        input_format=args.input_format,
        output_format=args.output_format,
        verbose=args.verbose,
        include_partial_messages=args.include_partial_messages,
        permission_mode=args.permission_mode,
        permission_prompt_tool=args.permission_prompt_tool,
        add_dir=add_dir,
        model=args.model,
        bare=args.bare,
        thinking_enabled=args.thinking == "enabled",
        resume_session_id=args.resume,
        resume_session_at=args.resume_session_at,
        append_system_prompt=args.append_system_prompt,
    )
    return run_headless(config)


if __name__ == "__main__":
    sys.exit(main())
