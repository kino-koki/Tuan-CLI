# -*- coding: utf-8 -*-
"""登录态存储 —— 统一管理 Tuan-CLI 的多账户登录状态。

存储位置: <QXT_HOME>/auth.json (默认 ~/.qingxiaotuan/auth.json)。
结构::
    {
      "version": 1,
      "accounts": {
        "github":   {...账户信息与令牌...},
        "apple":    {...},
        "deepseek": {...}
      }
    }

设计原则:
- 只做「登录态」的落盘与查询, 不感知各提供方的协议细节 (协议在 provider 内)。
- 令牌以明文落盘 (与 gh CLI 的 hosts.yml 一致), 通过文件权限尽量收紧;
  机密性提示见 README「登录与凭证」章节。
- 离线不登录是默认路径: 无 auth.json 或全部账户为空时, 一切本地功能照常。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ..config.loader import home_dir

AUTH_FILE_NAME = "auth.json"
_AUTH_VERSION = 1


def _ensure_secure_permissions(path: Path) -> None:
    """尽力收紧文件权限 (POSIX 生效; Windows 为 best-effort, 失败不报错)。"""
    try:
        if os.name == "posix":
            os.chmod(str(path), 0o600)
    except OSError:
        pass


class AuthStore:
    """登录态存储: 加载/保存/查询/删除各提供方账户。"""

    def __init__(self, home: Optional[Path] = None) -> None:
        home = Path(home) if home is not None else home_dir()
        self.path = home / AUTH_FILE_NAME

    # ------------------------------------------------------------- 基础 IO
    def load(self) -> Dict[str, Any]:
        """读取 auth.json; 不存在/损坏一律返回空结构 (不抛异常)。"""
        try:
            if self.path.exists():
                raw = self.path.read_text(encoding="utf-8")
                data = json.loads(raw)
                if isinstance(data, dict) and isinstance(data.get("accounts"), dict):
                    return data
        except (OSError, ValueError):
            pass
        return {"version": _AUTH_VERSION, "accounts": {}}

    def save(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _ensure_secure_permissions(self.path)

    def _accounts(self, data: Dict[str, Any]) -> Dict[str, Any]:
        accounts = data.setdefault("accounts", {})
        return accounts if isinstance(accounts, dict) else {}

    # ------------------------------------------------------------- 查询
    def get(self, provider: str) -> Optional[dict]:
        data = self.load()
        acc = self._accounts(data).get(provider)
        return dict(acc) if acc else None

    def is_logged_in(self, provider: str) -> bool:
        acc = self.get(provider)
        return bool(acc and acc.get("token"))

    def list_accounts(self) -> Dict[str, dict]:
        """返回 {provider: 账户信息} (不含令牌的展示字段由调用方过滤)。"""
        return {k: dict(v) for k, v in self._accounts(self.load()).items()}

    def list_logged_in(self) -> Dict[str, dict]:
        return {k: v for k, v in self.list_accounts().items() if v.get("token")}

    # ------------------------------------------------------------- 写入
    def set(self, provider: str, account: Dict[str, Any]) -> None:
        data = self.load()
        acc = self._accounts(data)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        prev = acc.get(provider, {})
        account = dict(account)
        account.setdefault("provider", provider)
        account.setdefault("created_at", prev.get("created_at", now))
        account["updated_at"] = now
        acc[provider] = account
        self.save(data)

    def remove(self, provider: str) -> bool:
        """删除某提供方登录态; 返回是否确实存在并删除。"""
        data = self.load()
        acc = self._accounts(data)
        if provider not in acc:
            return False
        del acc[provider]
        self.save(data)
        return True

    def clear(self) -> None:
        data = self.load()
        data["accounts"] = {}
        self.save(data)
