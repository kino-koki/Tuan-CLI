"""`!` Shell 快捷模式 —— 对标 Claude Code Week 26 的 `!` shell mode。

在 REPL 输入 `!命令` 时直接执行 shell (不经 LLM):
- 复用 ``tools/shell.run_shell`` 的全套安全护栏 (硬红线 / 网络门控 / 严格模式 /
  沙箱选路 / Plan 只读拦截), 危险命令 (rm -rf 等) 同样被拦截, ``!`` 不是豁免通道;
- 输出直接显示在对话中;
- 执行结果以带标记的 user 消息注入 ``agent.messages``, 下一轮 LLM 自动看到
  (上下文注入), 例如 `!pytest tests/ -q` 跑完测试结果直接成为 Agent 的上下文。
"""

from __future__ import annotations

from typing import Any

from ._ui_singleton import ui

_MAX_PREVIEW_LINES = 40


def split_bang_command(text: str) -> str:
    """从 `!xxx` 输入中剥出命令体 (容忍 `! xxx` / `!xxx` / `！xxx` 全角感叹号)。"""
    body = (text or "").strip()
    while body.startswith(("!", "！")):
        body = body[1:]
    return body.strip()


def is_bang_input(text: str) -> bool:
    """REPL 输入是否为 `!` 快捷命令 (前置判断用, 不去掉命令体)。"""
    body = (text or "").strip()
    return bool(body) and body[0] in ("!", "！")


def run_bang_command(agent: Any, text: str, *, display: bool = True) -> str:
    """执行 `!` shell 命令: 显示输出 + 把结果注入下一轮上下文。返回输出文本。"""
    command = split_bang_command(text)
    if not command:
        msg = ("用法: !<命令>  —— 直接在工作区执行 shell (不经 LLM), "
               "结果自动带入下一轮对话; 危险命令仍受安全护栏拦截。")
        if display:
            ui.info(msg)
        return msg

    # 延迟导入: 避免 cli 启动期拉起 tools/shell 的全部依赖
    from ..tools.shell import run_shell

    ctx = getattr(agent, "ctx", None)
    if ctx is None:
        result = "[错误] 当前会话没有可用的工具上下文 (agent.ctx 缺失)。"
    else:
        result = run_shell(ctx, command)

    if display:
        ui.info(f">>> {command}")
        lines = result.splitlines()
        for line in lines[:_MAX_PREVIEW_LINES]:
            ui.info("  " + line)
        if len(lines) > _MAX_PREVIEW_LINES:
            ui.info(f"  ...(共 {len(lines)} 行, 完整输出已注入下一轮上下文)")

    # 上下文注入: 作为 user 消息追加, 下一轮 agent.run() 即可看到本次命令输出。
    # 用括号说明这是 shell 输出而非用户新提问, 避免模型把它当作用户指令执行。
    try:
        agent.messages.append({
            "role": "user",
            "content": (
                "(用户通过 `!` 直接执行了 shell 命令, 以下是真实输出, "
                "后续回答可直接引用该结果)\n"
                f"$ {command}\n{result}"
            ),
        })
    except Exception:  # noqa: BLE001 - 注入失败不应阻断命令本身的展示
        pass

    return f"$ {command}\n{result}"
