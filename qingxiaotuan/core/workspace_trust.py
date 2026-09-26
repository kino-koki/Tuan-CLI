"""Workspace Trust — 项目目录信任系统 (对标 Claude Code 2.1.239 Workspace Trust)。

核心概念:
- 每个项目目录有一个信任级别, 决定 Agent 在该目录中的权限
- 信任级别: trusted | limited | untrusted | unknown
- 首次打开项目时提示用户确认信任
- 信任状态持久化到 QXT_HOME/workspace_trust.json
- 支持组织级默认信任策略 (managed settings)

安全边界:
- untrusted: 禁止执行 shell 命令, 只读工具可用
- limited: shell 命令需每次确认, 写工具受限
- trusted: 完整权限 (仍受 safety 引擎保护)
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


# ================================================================ 信任级别

class TrustLevel:
    TRUSTED = "trusted"       # 完整权限
    LIMITED = "limited"       # 受限权限 (shell 需确认)
    UNTRUSTED = "untrusted"   # 只读
    UNKNOWN = "unknown"       # 未评估 (首次打开)


# ---------------------------------------------------------------- fail-closed 裁决


def is_action_allowed(level: str, action: str) -> bool:
    """fail-closed 动作裁决: 未知/非预期级别一律拒绝。

    - trusted:   允许一切 (仍受 safety 引擎约束)
    - limited:   仅允许只读类动作 (read/plan)
    - 其它:     拒绝
    """
    if level == TrustLevel.TRUSTED:
        return True
    if level == TrustLevel.LIMITED:
        return action in ("read", "plan")
    # untrusted / unknown / 任意未知值 → 保守拒绝
    return False


def consult_for_shell(level: str, command: str) -> "tuple[str, str]":
    """为 shell 执行提供 fail-closed 裁决, 返回 (action, reason)。

    action ∈ {allow, confirm, deny}。本函数不替代 safety 引擎的红线判定,
    而是从「工作区信任」维度做额外门禁 —— untrusted 工作区直接禁止 shell,
    unknown 必须确认, limited 对非良性命令要求确认。
    """
    if level == TrustLevel.UNTRUSTED:
        return ("deny", "工作区为 untrusted, 禁止执行 shell 命令")
    if level == TrustLevel.UNKNOWN:
        return ("confirm", "工作区信任级别未知, 需用户确认后方可执行 shell")
    if level == TrustLevel.LIMITED:
        try:
            from ..ext.safety_engine import is_benign_dev_command
            if not is_benign_dev_command(command):
                return ("confirm", "工作区为 limited 信任, 非良性命令需确认")
        except Exception:  # noqa: BLE001
            return ("confirm", "工作区为 limited 信任, 无法评估命令安全性, 需确认")
    return ("allow", "")


# ================================================================ 信任记录

@dataclass
class TrustRecord:
    """单个目录的信任记录。"""
    path: str
    level: str = TrustLevel.UNKNOWN
    trusted_at: float = 0.0
    last_used: float = 0.0
    project_name: str = ""
    git_remote: str = ""       # git remote URL (用于识别项目)
    trust_count: int = 0       # 累计信任次数

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "level": self.level,
            "trusted_at": self.trusted_at,
            "last_used": self.last_used,
            "project_name": self.project_name,
            "git_remote": self.git_remote,
            "trust_count": self.trust_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrustRecord":
        return cls(
            path=str(data.get("path", "")),
            level=str(data.get("level", TrustLevel.UNKNOWN)),
            trusted_at=float(data.get("trusted_at", 0)),
            last_used=float(data.get("last_used", 0)),
            project_name=str(data.get("project_name", "")),
            git_remote=str(data.get("git_remote", "")),
            trust_count=int(data.get("trust_count", 0)),
        )


# ================================================================ 信任管理器

class WorkspaceTrust:
    """项目目录信任管理器。

    用法:
        trust = WorkspaceTrust(Path("~/.qingxiaotuan"))
        level = trust.check_trust("/path/to/project")
        if level == TrustLevel.UNKNOWN:
            # 提示用户确认
            trust.set_trust("/path/to/project", TrustLevel.TRUSTED)
    """

    def __init__(self, home: Path) -> None:
        self.home = Path(home)
        self._trust_file = self.home / "workspace_trust.json"
        self._records: Dict[str, TrustRecord] = {}
        self._load()

    def _load(self) -> None:
        if self._trust_file.exists():
            try:
                data = json.loads(self._trust_file.read_text(encoding="utf-8"))
                for path, record in data.items():
                    self._records[path] = TrustRecord.from_dict(record)
            except Exception:
                self._records = {}

    def _save(self) -> None:
        from .atomicio import atomic_write_text
        data = {path: r.to_dict() for path, r in self._records.items()}
        atomic_write_text(
            self._trust_file,
            json.dumps(data, ensure_ascii=False, indent=2),
        )

    def _normalize_path(self, path: str) -> str:
        """规范化路径 (resolve symlinks, expanduser)。"""
        try:
            return str(Path(path).expanduser().resolve())
        except Exception:
            return str(Path(path).resolve())

    def check_trust(self, path: str) -> str:
        """检查目录的信任级别。"""
        normalized = self._normalize_path(path)
        record = self._records.get(normalized)
        if record is None:
            return TrustLevel.UNKNOWN
        return record.level

    def set_trust(self, path: str, level: str, project_name: str = "", git_remote: str = "") -> TrustRecord:
        """设置目录的信任级别。"""
        normalized = self._normalize_path(path)
        now = time.time()
        existing = self._records.get(normalized)

        record = TrustRecord(
            path=normalized,
            level=level,
            trusted_at=now if level == TrustLevel.TRUSTED else (existing.trusted_at if existing else 0),
            last_used=now,
            project_name=project_name or (existing.project_name if existing else ""),
            git_remote=git_remote or (existing.git_remote if existing else ""),
            trust_count=(existing.trust_count + 1) if existing and level == TrustLevel.TRUSTED else 1,
        )
        self._records[normalized] = record
        self._save()
        return record

    def update_last_used(self, path: str) -> None:
        """更新最后使用时间。"""
        normalized = self._normalize_path(path)
        record = self._records.get(normalized)
        if record:
            record.last_used = time.time()
            self._save()

    def is_trusted(self, path: str) -> bool:
        """快速检查是否已信任。"""
        return self.check_trust(path) == TrustLevel.TRUSTED

    def is_readonly(self, path: str) -> bool:
        """快速检查是否只读。"""
        return self.check_trust(path) == TrustLevel.UNTRUSTED

    def list_trusted(self) -> List[TrustRecord]:
        """列出所有已信任的目录。"""
        return [r for r in self._records.values() if r.level == TrustLevel.TRUSTED]

    def remove(self, path: str) -> bool:
        """移除信任记录。"""
        normalized = self._normalize_path(path)
        if normalized in self._records:
            del self._records[normalized]
            self._save()
            return True
        return False

    def cleanup(self, max_age_days: int = 90) -> int:
        """清理长期未使用的信任记录。"""
        cutoff = time.time() - (max_age_days * 86400)
        stale = [p for p, r in self._records.items()
                 if r.last_used < cutoff and r.level != TrustLevel.TRUSTED]
        for p in stale:
            del self._records[p]
        if stale:
            self._save()
        return len(stale)

    # ---------------------------------------------------------------- E2: 信任自动衰减

    # 敏感文件模式: 当这些文件出现时, 信任应降级并提示复核
    _SENSITIVE_FILE_PATTERNS = (
        ".env", ".env.local", ".env.production",
        ".git/config",  # git remote 变更可能意味项目归属变化
        "id_rsa", "id_ed25519", "*.pem", "*.key",
        "credentials.json", "service-account*.json",
    )

    # 信任衰减时间窗口: 超过此时间未使用的 trusted 工作区, 降级为 limited
    _DECAY_WINDOW_DAYS = 30

    def check_for_decay(self, path: str) -> Optional[str]:
        """E2: 检查工作区信任是否需要衰减。

        返回衰减原因 (None=无需衰降)。
        触发条件:
        1. 工作区出现新的敏感文件 (.env / 密钥 / git config)
        2. 信任时间过长且长期未使用 (>30天)
        """
        normalized = self._normalize_path(path)
        record = self._records.get(normalized)
        if record is None or record.level != TrustLevel.TRUSTED:
            return None

        now = time.time()

        # 条件 2: 长期未使用衰减
        decay_cutoff = now - (self._DECAY_WINDOW_DAYS * 86400)
        if record.last_used < decay_cutoff:
            return (
                f"工作区 {normalized} 已超过 {self._DECAY_WINDOW_DAYS} 天未使用, "
                f"信任级别从 trusted 降为 limited, 请重新确认。"
            )

        # 条件 1: 敏感文件检测
        try:
            project_dir = Path(normalized)
            if not project_dir.is_dir():
                return None
            sensitive_found = []
            for pattern in self._SENSITIVE_FILE_PATTERNS:
                if '*' in pattern:
                    # glob 模式
                    for f in project_dir.glob(pattern):
                        if f.is_file():
                            sensitive_found.append(str(f.name))
                else:
                    # 精确匹配 (含子目录)
                    for f in project_dir.rglob(pattern):
                        if f.is_file():
                            sensitive_found.append(str(f.relative_to(project_dir)))
            if sensitive_found:
                # 检查这些文件是否是新增的 (不在上次信任时存在)
                # 简化: 如果文件存在且记录的 trusted_at 早于文件 mtime, 则认为是新增
                new_sensitive = []
                for fp in sensitive_found:
                    try:
                        full = project_dir / fp
                        mtime = full.stat().st_mtime
                        if mtime > record.trusted_at:
                            new_sensitive.append(fp)
                    except OSError:
                        pass
                if new_sensitive:
                    return (
                        f"工作区 {normalized} 出现新的敏感文件: {', '.join(new_sensitive[:5])}, "
                        f"信任级别从 trusted 降为 limited, 请重新确认。"
                    )
        except Exception:  # noqa: BLE001
            pass

        return None

    def apply_decay(self, path: str, reason: str) -> TrustRecord:
        """应用信任衰减: 将 trusted 降为 limited 并记录原因。"""
        normalized = self._normalize_path(path)
        record = self._records.get(normalized)
        if record and record.level == TrustLevel.TRUSTED:
            record.level = TrustLevel.LIMITED
            record.last_used = time.time()
            self._save()
            return record
        # 如果没有记录, 创建一个新的 limited 记录
        return self.set_trust(path, TrustLevel.LIMITED)

    def get_project_info(self, path: str) -> Dict[str, Any]:
        """获取项目的信任信息 (供 UI 展示)。"""
        normalized = self._normalize_path(path)
        record = self._records.get(normalized)
        if record is None:
            return {
                "path": normalized,
                "trust_level": TrustLevel.UNKNOWN,
                "needs_confirmation": True,
            }
        return {
            "path": normalized,
            "trust_level": record.level,
            "project_name": record.project_name,
            "git_remote": record.git_remote,
            "trusted_at": record.trusted_at,
            "last_used": record.last_used,
            "trust_count": record.trust_count,
            "needs_confirmation": record.level == TrustLevel.UNKNOWN,
        }
