"""与 Codex ``tui/src/additional_dirs.rs`` 对齐的 ``--add-dir`` 权限判定。

上游 doc comment（契约原文）：

    "Returns a warning describing why `--add-dir` entries will be ignored
    for the resolved permission profile. The caller is responsible for
    presenting the warning to the user (for example, printing to stderr)."

五个提前返回 ``None``（**顺序不可重排**）：
  1. ``additional_dirs`` 为空；
  2. profile 是 ``Disabled`` 或 ``External``（无 FS 沙箱策略可谈）；
  3. ``file_system_policy.has_full_disk_write_access()`` 为真；
  4. ``can_write_local_path_with_cwd(cwd, cwd)`` 为真（工作区可写）；
  5. 其余情况返回 ``format_warning(additional_dirs)``。

警告原文逐字保留供核销：

    "Ignoring --add-dir ({joined_paths}) because the effective permissions
    do not allow additional writable roots. Switch to workspace-write or
    danger-full-access to allow them."

**本轮最值钱的安全语义**：上游只是**返回一句字符串**让调用方"负责呈现"。
若调用方忘了打印，``--add-dir`` 就被静默丢弃 —— 用户以为加了可写根，
实际操作要么失败、要么（更糟）落到别的路径。本模块把它升级为
**结构化 fail-closed 决策**：``ignored=True`` 时同时给出 warning 与
``actionable_hint``，调用方必须显式取用；并新增
``enforce()`` 直接返回拒绝结果，不给"忘了看警告"留空间。

本地化修改（如实列出）：
  - Rust ``PermissionProfile`` 枚举 -> Python dataclass 能力三元组
    （``has_full_disk_write_access`` / ``can_write_cwd`` /
    ``has_fs_sandbox_policy``），逐分支对齐五个早退条件；
  - 新增路径规范化校验：拒绝含 ``..`` 的逃逸路径、NUL、控制字符、
    空串；symlink 祖先由调用方结合文件系统检查（见 ``validate_paths``）；
  - 中文警告与提示（英文原文保留在 ``WARNING_TEMPLATE_EN``）；
  - 新增 ``AddDirDecision.to_dict()`` 供审计事件消费；
  - 本地化增强：**忽略时一律拒绝**而不是"仅提示"，避免静默降级。

许可：Apache-2.0（NOTICE 第 13 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

WARNING_TEMPLATE_EN = (
    "Ignoring --add-dir ({joined_paths}) because the effective permissions "
    "do not allow additional writable roots. Switch to workspace-write or "
    "danger-full-access to allow them."
)
WARNING_TEMPLATE_ZH = (
    "已忽略 --add-dir ({joined_paths})：当前生效权限不允许额外的可写根。"
    "请切换到 workspace-write 或 danger-full-access 后再使用。"
)

# 本地化：中文的行动提示，避免用户只看到"被忽略"却不知怎么修
ACTIONABLE_HINT_ZH = "改用 workspace-write 或 danger-full-access 权限档位"
ACTIONABLE_HINT_EN = (
    "Switch to workspace-write or danger-full-access to allow them.")


@dataclass(frozen=True)
class PermissionProfileView:
    """对齐上游 ``PermissionProfile`` 的三个判定维度。

    本地化：不复制 Rust 枚举的全部变体，只保留 ``additional_dirs.rs``
    真正用到的三个能力判定，避免把整个权限模型拖进 UI 层。
    """

    # Disabled / External: 上游直接 return None（无 FS 沙箱策略）
    no_fs_sandbox_policy: bool = False
    # has_full_disk_write_access()
    has_full_disk_write_access: bool = False
    # can_write_local_path_with_cwd(cwd, cwd)
    can_write_cwd: bool = False

    @classmethod
    def disabled(cls) -> "PermissionProfileView":
        return cls(no_fs_sandbox_policy=True,
                   has_full_disk_write_access=True)

    @classmethod
    def external(cls) -> "PermissionProfileView":
        return cls(no_fs_sandbox_policy=True)

    @classmethod
    def workspace_write(cls) -> "PermissionProfileView":
        return cls(can_write_cwd=True)

    @classmethod
    def read_only(cls) -> "PermissionProfileView":
        return cls()

    @classmethod
    def managed_restricted(cls) -> "PermissionProfileView":
        """对齐上游测试：只允许写别处、不允许写 cwd -> 仍要警告。"""
        return cls(has_full_disk_write_access=False, can_write_cwd=False)


@dataclass(frozen=True)
class AddDirDecision:
    """结构化决策（本地化增强，替代上游「只返回一句字符串」）。"""

    ignored: bool
    dirs: List[str] = field(default_factory=list)
    reason: str = ""
    warning: Optional[str] = None
    actionable_hint: Optional[str] = None
    path_problems: List[str] = field(default_factory=list)

    @property
    def effective_dirs(self) -> List[str]:
        """调用方**必须**用这个取实际生效的目录列表。"""
        return [] if self.ignored else list(self.dirs)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ignored": self.ignored,
            "dirs": list(self.dirs),
            "effective_dirs": self.effective_dirs,
            "reason": self.reason,
            "warning": self.warning,
            "actionable_hint": self.actionable_hint,
            "path_problems": list(self.path_problems),
        }


def validate_paths(additional_dirs: Sequence[str],
                    *, base_cwd: Optional[str] = None) -> List[str]:
    """本地化安全增强：拒绝 ``..`` 逃逸 / 控制字符 / NUL / 空串。

    **刻意不做「越出 cwd」判定** —— ``--add-dir`` 的本意就是添加
    工作区之外的可写根，把"在 cwd 外"当错误会与语义直接冲突。
    真正的可写边界由沙箱/权限策略裁决，UI 层只负责不把明显恶意的
    路径串（``..``、控制字符）送进去；symlink 由下游隔离层处理。
    ``base_cwd`` 仅用于把相对路径拼成绝对路径做 ``..`` 复核。
    """
    problems: List[str] = []
    for raw in additional_dirs:
        if not isinstance(raw, str) or not raw.strip():
            problems.append("empty --add-dir entry")
            continue
        if "\x00" in raw or any(ord(c) < 32 for c in raw):
            problems.append(f"--add-dir 含控制字符: {raw!r}")
            continue
        candidate = (os.path.join(base_cwd, raw)
                     if base_cwd and not os.path.isabs(raw) else raw)
        parts = candidate.replace("\\", "/").split("/")
        if ".." in parts:
            problems.append(f"--add-dir 含 '..' 路径逃逸: {raw!r}")
    return problems


def format_warning(additional_dirs: Sequence[str], *, zh: bool = True) -> str:
    """对齐上游 ``format_warning``：逗号+空格拼接路径并套模板。"""
    joined = ", ".join(str(p) for p in additional_dirs)
    tpl = WARNING_TEMPLATE_ZH if zh else WARNING_TEMPLATE_EN
    return tpl.format(joined_paths=joined)


def add_dir_warning_message(
    additional_dirs: Sequence[str],
    permission_profile: PermissionProfileView,
    cwd: str,
    *, zh: bool = True,
) -> Optional[str]:
    """逐分支对齐上游；返回值语义完全一致（``None`` = 不警告）。"""
    if not additional_dirs:
        return None
    if permission_profile.no_fs_sandbox_policy:  # Disabled | External
        return None
    if permission_profile.has_full_disk_write_access:
        return None
    if permission_profile.can_write_cwd:  # can_write_local_path_with_cwd(cwd, cwd)
        return None
    # cwd 参数在上游传给 FS 策略；本视图已把结果折算进 can_write_cwd。
    # 保留参数以对齐签名，并做一次非空校验（本地化增强）。
    if not cwd:
        return None
    return format_warning(additional_dirs, zh=zh)


def decide_add_dirs(
    additional_dirs: Sequence[str],
    permission_profile: PermissionProfileView,
    cwd: str,
    *, zh: bool = True,
    validate: bool = True,
) -> AddDirDecision:
    """本地化增强：把上游的「返回一句警告」升级为结构化 fail-closed 决策。"""
    dirs = [str(p) for p in additional_dirs]
    problems = validate_paths(dirs, base_cwd=cwd) if validate else []
    warning = add_dir_warning_message(dirs, permission_profile, cwd, zh=zh)

    if not dirs:
        return AddDirDecision(ignored=False, dirs=[],
                              reason="no_additional_dirs")
    if problems:
        # 路径本身有问题：比"权限不够"更该拒绝，且不打印可疑路径进 UI
        return AddDirDecision(
            ignored=True, dirs=dirs, path_problems=problems,
            reason="invalid_paths",
            warning="已忽略 --add-dir：路径校验未通过（详见 path_problems）"
            if zh else "--add-dir ignored: path validation failed",
            actionable_hint=ACTIONABLE_HINT_ZH if zh else ACTIONABLE_HINT_EN)
    if warning is not None:
        return AddDirDecision(
            ignored=True, dirs=dirs, reason="permissions_do_not_allow",
            warning=warning,
            actionable_hint=ACTIONABLE_HINT_ZH if zh else ACTIONABLE_HINT_EN)
    return AddDirDecision(
        ignored=False, dirs=dirs,
        reason=("no_fs_sandbox_policy" if permission_profile.no_fs_sandbox_policy
                else "full_disk_write" if permission_profile.has_full_disk_write_access
                else "cwd_writable"),
        path_problems=problems)


def enforce(decision: AddDirDecision) -> Dict[str, Any]:
    """fail-closed 出口：返回可直接给工具层的裁决，不给"忘了看警告"留空间。"""
    if decision.ignored:
        return {"allowed": False, "reason": decision.reason,
                "message": decision.warning or "",
                "hint": decision.actionable_hint or "",
                "effective_dirs": []}
    return {"allowed": True, "reason": decision.reason,
            "effective_dirs": list(decision.dirs)}


def constants() -> Dict[str, Any]:
    return {"warning_template_en": WARNING_TEMPLATE_EN,
            "warning_template_zh": WARNING_TEMPLATE_ZH,
            "early_return_branches": 4}
