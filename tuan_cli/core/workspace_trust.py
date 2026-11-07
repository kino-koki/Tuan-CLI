"""Workspace Trust — 项目目录信任系统 (对标 Claude Code 2.1.239 Workspace Trust)。

核心概念:
- 每个项目目录有一个信任级别, 决定 Agent 在该目录中的权限
- 信任级别: trusted | limited | untrusted | unknown
- 首次打开项目时提示用户确认信任
- 信任状态持久化到 TUAN_HOME/workspace_trust.json
- 支持组织级默认信任策略 (managed settings)

安全边界:
- untrusted: 禁止执行 shell 命令, 只读工具可用
- limited: shell 命令需每次确认, 写工具受限
- trusted: 完整权限 (仍受 safety 引擎保护)
"""

from __future__ import annotations

import fnmatch
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


# ---------------------------------------------------------------- E2: 工作区敏感面扫描
# 指纹只覆盖「敏感文件 + 顶层目录结构」, 不扫描源码内容 —— 保证每次 check_trust
# 的开销可控, 也不会因为正常写代码而反复触发降级。
_SCAN_SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "target",
    ".toolchain", ".pytest_cache", ".mypy_cache", ".ruff_cache", "site-packages",
    "vendor", ".next", ".gradle", "Pods", ".dart_tool",
})
_SCAN_MAX_DEPTH = 4           # 相对根的目录深度上限
_SCAN_MAX_ENTRIES = 20000     # 单次扫描条目上限, 超出即判为「无法校验」
_DECAY_RECHECK_SECONDS = 2.0  # check_trust 内指纹重算的最小间隔

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
    fingerprint: str = ""      # E2: 信任确认时的工作区敏感面指纹
    decay_reason: str = ""     # E2: 最近一次自动衰减的原因 (可观测)
    decayed_at: float = 0.0    # E2: 最近一次自动衰减时间

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "level": self.level,
            "trusted_at": self.trusted_at,
            "last_used": self.last_used,
            "project_name": self.project_name,
            "git_remote": self.git_remote,
            "trust_count": self.trust_count,
            "fingerprint": self.fingerprint,
            "decay_reason": self.decay_reason,
            "decayed_at": self.decayed_at,
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
            fingerprint=str(data.get("fingerprint", "")),
            decay_reason=str(data.get("decay_reason", "")),
            decayed_at=float(data.get("decayed_at", 0)),
        )


# ================================================================ 信任管理器

class WorkspaceTrust:
    """项目目录信任管理器。

    用法:
        trust = WorkspaceTrust(Path("~/.tuan"))
        level = trust.check_trust("/path/to/project")
        if level == TrustLevel.UNKNOWN:
            # 提示用户确认
            trust.set_trust("/path/to/project", TrustLevel.TRUSTED)
    """

    def __init__(self, home: Path) -> None:
        self.home = Path(home)
        self._trust_file = self.home / "workspace_trust.json"
        self._records: Dict[str, TrustRecord] = {}
        self._decay_checked: Dict[str, float] = {}  # E2: check_trust 指纹重算节流
        self._last_used_saved: Dict[str, float] = {}  # E2: last_used 落盘节流
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
        """检查目录的信任级别 (主链路入口)。

        E2: 对 trusted 记录自动执行衰减校验。此前 check_for_decay/apply_decay
        只有测试调用, CLI (`cmd_chat.py`) 与 Web (`web/server.py`) 都直接读
        record.level —— 等于「实现了衰减但主链路从未生效」。现在所有调用方
        经由本方法都会拿到衰减后的真实级别; 指纹重算按 2 秒节流, 避免每次
        工具调用都扫盘。需要绕过节流时可直接调 check_for_decay()。
        """
        normalized = self._normalize_path(path)
        record = self._records.get(normalized)
        if record is None:
            return TrustLevel.UNKNOWN
        if record.level != TrustLevel.TRUSTED:
            return record.level
        now = time.time()
        if now - self._decay_checked.get(normalized, 0.0) < _DECAY_RECHECK_SECONDS:
            return record.level
        self._decay_checked[normalized] = now
        # 注意顺序: 必须先完成衰减判定再刷新 last_used, 否则 30 天时间衰减
        # 永远不会触发 (每次 check 都把 last_used 改成 now)。
        reason = self.check_for_decay(path)
        if reason:
            self.apply_decay(path, reason)
            return TrustLevel.LIMITED
        # E2: 主链路此前从未调用 update_last_used(), 于是活跃使用中的工作区
        # 也会在 30 天后被误判为"长期未使用"。这里顺带维护活跃时间, 并按
        # 60 秒节流落盘, 避免每 2 秒一次原子写。
        record.last_used = now
        if now - self._last_used_saved.get(normalized, 0.0) >= 60.0:
            self._save()
            self._last_used_saved[normalized] = now
        return record.level

    def set_trust(self, path: str, level: str, project_name: str = "", git_remote: str = "") -> TrustRecord:
        """设置目录的信任级别。"""
        normalized = self._normalize_path(path)
        now = time.time()
        existing = self._records.get(normalized)

        # E2: 每次确认 trusted 都重新采样工作区敏感面, 作为后续衰减比对的基线。
        # 采样失败不阻塞确认, 指纹留空 -> 下次 check_for_decay 会补建基线。
        fingerprint = ""
        if level == TrustLevel.TRUSTED:
            try:
                fingerprint = self._compute_fingerprint(normalized)
            except Exception:  # noqa: BLE001
                fingerprint = ""
        record = TrustRecord(
            path=normalized,
            level=level,
            trusted_at=now if level == TrustLevel.TRUSTED else (existing.trusted_at if existing else 0),
            last_used=now,
            project_name=project_name or (existing.project_name if existing else ""),
            git_remote=git_remote or (existing.git_remote if existing else ""),
            trust_count=(existing.trust_count + 1) if existing and level == TrustLevel.TRUSTED else 1,
            fingerprint=fingerprint,
            decay_reason="" if level == TrustLevel.TRUSTED else (existing.decay_reason if existing else ""),
            decayed_at=0.0 if level == TrustLevel.TRUSTED else (existing.decayed_at if existing else 0.0),
        )
        self._records[normalized] = record
        self._save()
        self._decay_checked.pop(normalized, None)
        return record

    def update_last_used(self, path: str) -> None:
        """更新最后使用时间 (公开 API; check_trust 已自动维护, 无需主链路手动调)。"""
        normalized = self._normalize_path(path)
        record = self._records.get(normalized)
        if record:
            now = time.time()
            record.last_used = now
            self._save()
            self._last_used_saved[normalized] = now

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

    @classmethod
    def _is_sensitive_path(cls, rel: str, basename: str) -> bool:
        """敏感面判定: 带斜杠的模式匹配相对路径, 其余匹配文件名。"""
        for pattern in cls._SENSITIVE_FILE_PATTERNS:
            if "/" in pattern:
                if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(rel, "*/" + pattern):
                    return True
            elif fnmatch.fnmatch(basename, pattern):
                return True
        return False

    def _compute_fingerprint(self, normalized: str) -> str:
        """采样工作区「敏感面」并给出稳定指纹。

        只看: 顶层目录名集合 + 敏感文件的 (相对路径, size, mtime_ns)。
        不读文件内容、不递归进依赖/构建目录、限深限条目数, 因此每次
        check_trust 的开销有上界。任何无法完成扫描的情况都抛异常, 由
        check_for_decay 统一按 fail-closed 处理 (绝不静默当作"无变化")。
        """
        root = Path(normalized)
        if not root.is_dir():
            raise NotADirectoryError(f"工作区不是目录: {normalized}")

        h = hashlib.sha256()
        entries = 0
        top_dirs: List[str] = []
        for child in sorted(root.iterdir(), key=lambda c: c.name):
            entries += 1
            if entries > _SCAN_MAX_ENTRIES:
                raise RuntimeError("工作区条目数超出扫描上限, 无法校验")
            if child.is_dir() and child.name not in _SCAN_SKIP_DIRS:
                top_dirs.append(child.name)
        h.update(("dirs:" + ",".join(sorted(top_dirs)) + "\n").encode("utf-8"))

        sensitive: List[str] = []
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            rel_dir = os.path.relpath(dirpath, str(root))
            rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
            depth = 0 if not rel_dir else rel_dir.count("/") + 1
            # .git 内部除 config 外无需遍历; 避免大仓库的 refs/objects 拖慢主链路
            if rel_dir == ".git":
                dirnames[:] = []
            elif depth >= _SCAN_MAX_DEPTH:
                dirnames[:] = []
            else:
                dirnames[:] = [d for d in dirnames
                               if d not in _SCAN_SKIP_DIRS and d != "objects"]
            for fn in filenames:
                entries += 1
                if entries > _SCAN_MAX_ENTRIES:
                    raise RuntimeError("工作区条目数超出扫描上限, 无法校验")
                rel = f"{rel_dir}/{fn}" if rel_dir else fn
                if not self._is_sensitive_path(rel, fn):
                    continue
                try:
                    st = os.stat(os.path.join(dirpath, fn))
                except OSError:
                    # 单个文件 stat 失败不能当作"不存在", 记为未知并让指纹变化
                    sensitive.append(f"{rel}|unknown")
                    continue
                sensitive.append(f"{rel}|{st.st_size}|{st.st_mtime_ns}")
        h.update(("files:" + "\n".join(sorted(sensitive)) + "\n").encode("utf-8"))
        return h.hexdigest()

    def check_for_decay(self, path: str) -> Optional[str]:
        """E2: 检查工作区信任是否需要衰减, 返回原因 (None=无需衰减)。

        触发条件:
        1. trusted 记录超过 30 天未使用;
        2. 敏感面指纹与「确认信任时」的基线不一致 (新增/变更 .env、密钥、
           .git/config 或顶层目录结构);
        3. 扫描本身失败 -> **fail-closed 降级**, 不再像旧实现那样 except/pass
           后返回 None (等于静默放行)。

        指纹为空 (老版本记录 / 首次确认时采样失败) 时只补建基线、不降级,
        避免历史记录每次启动都误报。
        """
        normalized = self._normalize_path(path)
        record = self._records.get(normalized)
        if record is None or record.level != TrustLevel.TRUSTED:
            return None

        now = time.time()
        decay_cutoff = now - (self._DECAY_WINDOW_DAYS * 86400)
        if record.last_used < decay_cutoff:
            return (
                f"工作区 {normalized} 已超过 {self._DECAY_WINDOW_DAYS} 天未使用, "
                f"信任级别从 trusted 降为 limited, 请重新确认。"
            )

        try:
            fingerprint = self._compute_fingerprint(normalized)
        except Exception as exc:  # noqa: BLE001
            # fail-closed: 无法证明工作区没变, 就不能继续按 trusted 放行。
            return (
                f"无法校验工作区敏感面 ({type(exc).__name__}), fail-closed "
                f"将 {normalized} 从 trusted 降为 limited, 请重新确认。"
            )

        if not record.fingerprint:
            record.fingerprint = fingerprint
            self._save()
            return None

        if fingerprint != record.fingerprint:
            return (
                f"工作区 {normalized} 的敏感面发生变化 (新增/变更敏感文件或目录结构), "
                f"信任级别从 trusted 降为 limited, 请重新确认。"
            )
        return None

    def apply_decay(self, path: str, reason: str) -> TrustRecord:
        """应用信任衰减: trusted -> limited, 并留下可审计的原因与时间。"""
        normalized = self._normalize_path(path)
        record = self._records.get(normalized)
        if record and record.level == TrustLevel.TRUSTED:
            record.level = TrustLevel.LIMITED
            record.last_used = time.time()
            record.decay_reason = reason
            record.decayed_at = time.time()
            self._save()
            self._decay_checked.pop(normalized, None)
            return record
        if record is None:
            return self.set_trust(path, TrustLevel.LIMITED)
        return record

    def get_project_info(self, path: str) -> Dict[str, Any]:
        """获取项目的信任信息 (供 UI / Web `trust_status` 展示)。

        E2: 先走 check_trust 触发衰减, 保证 Web 端显示的级别与 CLI、沙箱
        实际使用的级别一致 —— 此前 Web 端直接读 record.level, 会显示
        trusted 而 CLI 已降级, 属于危险的口径分裂。
        """
        normalized = self._normalize_path(path)
        level = self.check_trust(path)
        record = self._records.get(normalized)
        if record is None:
            return {
                "path": normalized,
                "trust_level": TrustLevel.UNKNOWN,
                "needs_confirmation": True,
                "decay_reason": "",
                "decayed_at": 0.0,
            }
        return {
            "path": normalized,
            "trust_level": level,
            "project_name": record.project_name,
            "git_remote": record.git_remote,
            "trusted_at": record.trusted_at,
            "last_used": record.last_used,
            "trust_count": record.trust_count,
            "needs_confirmation": level == TrustLevel.UNKNOWN,
            "decay_reason": record.decay_reason,
            "decayed_at": record.decayed_at,
        }
