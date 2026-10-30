"""`tuan personality` —— 人设管理命令。

用法:
    tuan personality              # 列出所有可用人设, 显示当前生效的
    tuan personality list         # 同上
    tuan personality show         # 显示当前人设详情
    tuan personality set <name>   # 设置人设 (写入 USER.md)
    tuan personality auto         # 恢复自动分配
"""

from __future__ import annotations

import json
import sys
from typing import Any

from ..core.personality import (
    PERSONALITY_NAMES,
    list_personalities,
    get_personality_info,
    render_personality_block,
    resolve_personality,
)


def cmd_personality(args: Any) -> int:
    """人设管理命令入口。"""
    cmd = getattr(args, "personality_cmd", "list")

    if cmd == "list":
        return _cmd_personality_list()
    elif cmd == "show":
        return _cmd_personality_show()
    elif cmd == "set":
        name = getattr(args, "name", "")
        return _cmd_personality_set(name)
    elif cmd == "auto":
        return _cmd_personality_auto()
    else:
        print(f"未知子命令: {cmd}")
        print("用法: tuan personality [list|show|set <name>|auto]")
        return 1


def _cmd_personality_list() -> int:
    """列出所有可用人设。"""
    # 获取当前人设
    try:
        from ..app import build_kernel
        kernel = build_kernel()
        config = kernel.require("config")
        memory_store = kernel.get("memory_store")
        current = resolve_personality(config, memory_store)
    except Exception:
        current = ""

    print("=" * 60)
    print("  青小团 人设系统 (Personality System)")
    print("=" * 60)
    print(f"\n  当前人设: {current or '(自动分配)'}\n")
    print(f"  {'人设名':<8} {'Key':<15} {'定位'}")
    print(f"  {'-'*8} {'-'*15} {'-'*30}")

    for p in list_personalities():
        marker = " ★" if p["name"] == current else ""
        print(f"  {p['name']:<8} {p['key']:<15} {p['tagline']}{marker}")

    print(f"\n  设置人设: tuan personality set <人设名>")
    print(f"  恢复自动: tuan personality auto")
    print(f"  优先级: USER.md 人设字段 > config agent.personality > 自动分配")
    return 0


def _cmd_personality_show() -> int:
    """显示当前人设详情。"""
    try:
        from ..app import build_kernel
        kernel = build_kernel()
        config = kernel.require("config")
        memory_store = kernel.get("memory_store")
        current = resolve_personality(config, memory_store)
    except Exception:
        current = ""

    info = get_personality_info(current)
    print("=" * 60)
    print(f"  当前人设: {info['name']} ({info['key']})")
    print(f"  定位: {info['tagline']}")
    print("=" * 60)
    print(f"\n  语气: {', '.join(info['tone'])}")
    print(f"  行为: {'; '.join(info['behaviors'])}")
    print(f"  口头禅: {'; '.join(info['catchphrases'])}")

    # 显示注入文本块预览
    block = render_personality_block(info["name"])
    print(f"\n  {'─' * 40}")
    print(f"  注入文本块 ({len(block)} 字符):")
    print(f"  {'─' * 40}")
    for line in block.splitlines()[:10]:
        print(f"  {line}")
    if len(block.splitlines()) > 10:
        print(f"  ... (共 {len(block.splitlines())} 行)")
    return 0


def _cmd_personality_set(name: str) -> int:
    """设置人设 (写入 USER.md)。"""
    if not name:
        print("用法: tuan personality set <人设名>")
        print(f"可选值: {', '.join(PERSONALITY_NAMES)}")
        return 1

    # 验证人设名
    from ..core.personality import _validate_or_default
    validated = _validate_or_default(name)
    if validated != name and name.lower() not in {
        p["key"] for p in list_personalities()
    }:
        print(f"⚠ 人设名 '{name}' 不是标准人设, 已映射为 '{validated}'")

    # 写入 USER.md
    try:
        from ..app import build_kernel
        kernel = build_kernel()
        config = kernel.require("config")
        memory_store = kernel.get("memory_store")
        if memory_store is None:
            print("✗ 无法获取记忆存储, 人设设置失败")
            return 1
        memory_store.update_user("人设", validated)
        print(f"✓ 人设已设置为: {validated}")
        print(f"  (已写入 USER.md, 下次会话生效)")
        return 0
    except Exception as exc:
        print(f"✗ 人设设置失败: {exc}")
        return 1


def _cmd_personality_auto() -> int:
    """恢复自动分配 (清除 USER.md 人设字段)。"""
    try:
        from ..app import build_kernel
        kernel = build_kernel()
        config = kernel.require("config")
        memory_store = kernel.get("memory_store")
        if memory_store is None:
            print("✗ 无法获取记忆存储")
            return 1
        # 清除 USER.md 中的人设字段
        memory_store.update_user("人设", "")
        current = resolve_personality(config, memory_store)
        print(f"✓ 已恢复自动分配, 当前人设: {current}")
        return 0
    except Exception as exc:
        print(f"✗ 恢复自动分配失败: {exc}")
        return 1
