"""斜杠命令 —— 会话导入导出域 (/export /import)。

拆分自 cmd_slash.py: 会话 Markdown 导出与导入。
"""

from __future__ import annotations

from ._ui_singleton import ui


def _cmd_export(agent, arg: str) -> None:
    """/export [filename] — 导出会话为 Markdown 文件。"""
    import os
    from datetime import datetime

    if not agent.messages:
        ui.info("当前会话为空, 无法导出。")
        return

    # 默认文件名: 会话标题 + 时间戳
    default_name = f"chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    filename = arg.strip() if arg.strip() else default_name
    if not filename.endswith(".md"):
        filename += ".md"

    # 生成 Markdown
    lines = ["# 青小团会话记录", ""]
    lines.append(f"> 导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 消息数: {len(agent.messages)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for msg in agent.messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            lines.append("## 你")
            lines.append("")
            lines.append(content)
            lines.append("")
        elif role == "assistant":
            lines.append("## 青小团")
            lines.append("")
            lines.append(content)
            lines.append("")

    # 写入文件
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        ui.success(f"已导出到: {os.path.abspath(filename)} ({len(agent.messages)} 条消息)")
    except Exception as exc:  # noqa: BLE001
        ui.error(f"导出失败: {exc}")


def _cmd_import(agent, arg: str) -> None:
    """/import <file> — 导入 Markdown 对话。"""
    import os

    if not arg.strip():
        ui.info("用法: /import <文件路径> — 导入 Markdown 格式的对话记录")
        return

    filepath = arg.strip()
    if not os.path.exists(filepath):
        ui.error(f"文件不存在: {filepath}")
        return

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as exc:  # noqa: BLE001
        ui.error(f"读取文件失败: {exc}")
        return

    # 简单解析 Markdown: 按 ## 角色 分割
    import re
    parts = re.split(r"^## (你|青小团)", content, flags=re.MULTILINE)

    imported = 0
    i = 1  # 跳过文件头
    while i < len(parts) - 1:
        role_label = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""

        if role_label == "你":
            role = "user"
        elif role_label == "青小团":
            role = "assistant"
        else:
            i += 2
            continue

        if body:
            agent.messages.append({"role": role, "content": body})
            imported += 1
        i += 2

    if imported > 0:
        ui.success(f"已导入 {imported} 条消息到当前会话。")
    else:
        ui.info("未解析到有效消息。文件格式应为: ## 你 / ## 青小团 交替的 Markdown。")
