# -*- coding: utf-8 -*-
"""qxt login / logout / whoami —— 第三方账户登录 (GitHub / Apple / DeepSeek 网页)。

离线优先: 不登录时一切本地功能照常; 登录只是可选增强。
"""
from __future__ import annotations

import sys
from typing import List, Optional

from ..auth import (
    AuthError,
    AuthStore,
    ProviderNotConfigured,
    get_provider,
    list_providers,
)
from ..ui.plain_console import console


def _print(obj) -> None:
    if sys.stdout.isatty():
        console.print(obj)
    else:
        print(obj)


def _provider_choices() -> List[str]:
    return [p["name"] for p in list_providers()]


def _pick_provider() -> Optional[str]:
    """无参数时交互选择提供方; 非交互环境返回 None。"""
    choices = _provider_choices()
    if not choices:
        return None
    if not sys.stdin.isatty():
        return None
    print("可用登录提供方:")
    for i, name in enumerate(choices, 1):
        meta = {p["name"]: p for p in list_providers()}[name]
        print(f"  {i}. {meta['display_name']} — {meta['description']}")
    try:
        raw = input("选择序号或名称 (回车取消): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    if not raw:
        return None
    if raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(choices):
            return choices[idx - 1]
        return None
    return raw if raw in choices else None


def _resolve_provider(name: Optional[str]) -> Optional[str]:
    if name:
        if name not in _provider_choices():
            _print(f"未知提供方: {name} (可用: {', '.join(_provider_choices())})")
            return None
        return name
    return _pick_provider()


# ---------------------------------------------------------------- 命令


def cmd_login(args) -> int:
    """qxt login [provider] —— 登录第三方账户。"""
    name = _resolve_provider(getattr(args, "provider", None))
    if name is None:
        return 0
    try:
        provider = get_provider(name)
        result = provider.login()
    except ProviderNotConfigured as exc:
        _print(f"[未配置] {exc}")
        return 1
    except AuthError as exc:
        _print(f"[登录失败] {exc}")
        return 1
    except KeyboardInterrupt:
        _print("\n登录已取消。")
        return 1
    _print(f"✅ 已通过 {provider.display_name} 登录: {result.login}")
    if result.extra:
        for k, v in result.extra.items():
            _print(f"   {k}: {v}")
    return 0


def cmd_logout(args) -> int:
    """qxt logout [provider] —— 登出第三方账户 (省略 provider = 全部)。"""
    store = AuthStore()
    name = getattr(args, "provider", None)
    if name:
        if name not in _provider_choices():
            _print(f"未知提供方: {name}")
            return 1
        ok = store.remove(name)
        _print(f"已登出 {name}" if ok else f"{name} 未登录")
    else:
        accounts = store.list_accounts()
        if not accounts:
            _print("当前未登录任何账户。")
            return 0
        store.clear()
        _print(f"已登出全部账户: {', '.join(accounts)}")
    return 0


def cmd_whoami(args) -> int:
    """qxt whoami —— 显示各提供方登录状态。"""
    store = AuthStore()
    rows: List[str] = []
    for p in list_providers():
        acc = store.get(p["name"])
        if acc and acc.get("token"):
            rows.append(
                f"{p['display_name']:<14} 已登录   {acc.get('login', '')}"
                + (f"   (scope: {acc['scope']})" if acc.get("scope") else "")
            )
        else:
            rows.append(f"{p['display_name']:<14} 未登录")
    if not rows:
        _print("当前未登录任何账户 (离线模式)。")
        return 0
    _print("\n".join(rows))
    return 0
