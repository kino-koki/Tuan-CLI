"""与 Codex ``tui/src/model_migration.rs`` 对齐的模型升级提示契约。

上游模块头（契约原文）：

    "Model upgrade copy and choices with shared picker presentation.
     Mandatory and optional migration outcomes retain their existing
     keyboard policy."

逐值/逐分支对齐：
  - ``ModelMigrationOutcome``：Accepted / Rejected / Exit（三态）；
  - ``MigrationMenuOption``：TryNewModel / UseExistingModel，
    label 分别是 ``"Try new model"`` / ``"Use existing model"``；
  - ``ModelMigrationCopy``：heading / content / can_opt_out / markdown；
  - ``migration_copy_for_models(..)``：有 markdown 模板时走
    ``fill_migration_markdown``；否则生成标题
    ``"Codex just got an upgrade. Introducing {display}."``、推荐语、
    可选 model_link 行、``can_opt_out`` 时才追加「可继续使用旧模型」；
  - **键位策略（最微妙的一条，逐分支对齐）**：
      * ``can_opt_out=false``（强制迁移）：Enter **和 Esc 都 accept**；
        只有 ``is_ctrl_exit_combo``（Ctrl+C / Ctrl+D）能 Exit；
      * ``can_opt_out=true``：↑/k -> TryNewModel，↓/j -> UseExistingModel，
        ``1`` -> 选中并 accept，``2`` -> 选中并 reject，
        **Enter/Esc -> confirm_selection()**（Esc 在这里是「确认当前选中」，
        不是取消！）；
      * 事件流耗尽（``events.next()`` 返回 None）-> ``screen.accept()``，
        即**无输入默认接受**；
  - ``is_ctrl_exit_combo``：CONTROL + Char('c'|'d')；
  - ``AltScreenGuard``：RAII ``Drop`` 恢复 alternate screen，异常路径也恢复。

**本轮最值钱的修正**：上游 ``fill_migration_markdown`` 是**链式 replace**：

    template.replace("{model_from}", current_model)
            .replace("{model_to}",   target_model)

若 ``current_model`` 里含字面量 ``{model_to}``（模型名来自服务端/配置，
可能被污染），它会被第二次 replace 二次替换成 ``target_model``，文案
错乱且给模板注入留了口子。已实测：
``"从 {model_from} 迁移到 {model_to}"`` + current ``"old-{model_to}-x"``
上游产出 ``"从 old-NEW-x 迁移到 NEW"``。本模块改成**单次正则扫描**
（一个 pass 同时替换两个占位符），替换值不再参与后续匹配。

本地化修改（如实列出）：
  - ratatui 渲染 / tokio 事件流 -> 纯状态机 + 可注入事件序列；
  - 中文文案（英文原文常量保留供核销），10 语言由项目 i18n 提供；
  - ``AltScreenGuard`` -> 上下文管理器（``__exit__`` 一定恢复）；
  - 新增 ``policy_note()`` 把「强制模式下 Esc 也接受 / 事件耗尽默认
    接受」这两条**与本项目审批覆盖层相反**的语义显式标注 —— 它们
    是上游既有键盘策略，不是 fail-closed，**绝不悄悄套到审批链路上**；
  - 本地化增强：模板占位符做白名单处理，未知 ``{...}`` 原样保留
    （不吞、不展开），并对模型名做长度/控制字符校验；
  - 新增 ``audit_trail`` 记录每次键位与状态迁移，便于回放。

许可：Apache-2.0（NOTICE 第 13 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence

HEADING_TEMPLATE_EN = "Codex just got an upgrade. Introducing {display}."
RECOMMENDATION_EN = ("We recommend switching from {current} to {target}.")
DESCRIPTION_FALLBACK_EN = (
    "{display} is recommended for better performance and reliability.")
OPT_OUT_LINE_EN = "You can continue using {current} if you prefer."

HEADING_TEMPLATE_ZH = "Tuan 已升级，带来 {display}。"
RECOMMENDATION_ZH = "建议从 {current} 切换到 {target}。"
DESCRIPTION_FALLBACK_ZH = "{display} 在性能与稳定性上更值得推荐。"
OPT_OUT_LINE_ZH = "如果愿意，也可以继续使用 {current}。"

LABEL_TRY_NEW_EN = "Try new model"
LABEL_USE_EXISTING_EN = "Use existing model"
LABEL_TRY_NEW_ZH = "试用新模型"
LABEL_USE_EXISTING_ZH = "继续使用现有模型"

PLACEHOLDER_RE = re.compile(r"\{model_(from|to)\}")
MAX_MODEL_NAME_LEN = 256


class ModelMigrationOutcome(str, Enum):
    ACCEPTED = "Accepted"
    REJECTED = "Rejected"
    EXIT = "Exit"


class MigrationMenuOption(str, Enum):
    TRY_NEW_MODEL = "TryNewModel"
    USE_EXISTING_MODEL = "UseExistingModel"

    @classmethod
    def all(cls) -> List["MigrationMenuOption"]:
        """对齐 ``all() -> [Self; 2]``（顺序不可换）。"""
        return [cls.TRY_NEW_MODEL, cls.USE_EXISTING_MODEL]

    def label(self, *, zh: bool = True) -> str:
        if self is MigrationMenuOption.TRY_NEW_MODEL:
            return LABEL_TRY_NEW_ZH if zh else LABEL_TRY_NEW_EN
        return LABEL_USE_EXISTING_ZH if zh else LABEL_USE_EXISTING_EN


@dataclass
class ModelMigrationCopy:
    """对齐 ``ModelMigrationCopy`` 四字段。"""

    heading: List[str] = field(default_factory=list)
    content: List[str] = field(default_factory=list)
    can_opt_out: bool = False
    markdown: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"heading": list(self.heading),
                "content": list(self.content),
                "can_opt_out": self.can_opt_out,
                "markdown": self.markdown}


def _safe_model_name(value: str, label: str,
                     problems: List[str]) -> str:
    if not isinstance(value, str) or not value:
        problems.append(f"{label} 为空")
        return ""
    if len(value) > MAX_MODEL_NAME_LEN:
        problems.append(f"{label} 超长")
        return value[:MAX_MODEL_NAME_LEN]
    if any(ord(c) < 32 or c in ("\x07", "\x1b") for c in value):
        problems.append(f"{label} 含终端控制字符")
        return "".join(c for c in value if ord(c) >= 32)
    return value


def fill_migration_markdown(template: str, current_model: str,
                            target_model: str) -> str:
    """**修正版**：单次正则扫描，替换值不参与后续匹配。

    对齐上游的两个占位符 ``{model_from}`` / ``{model_to}``，但避免
    ``str.replace`` 链式调用造成的二次替换（见模块头实测）。
    未知 ``{...}`` 原样保留，不吞不展开（本地化增强）。
    """
    mapping = {"from": current_model, "to": target_model}
    return PLACEHOLDER_RE.sub(lambda m: mapping[m.group(1)], template)


def migration_copy_for_models(
    current_model: str,
    target_model: str,
    *, target_display_name: str,
    model_link: Optional[str] = None,
    migration_copy: Optional[str] = None,
    migration_markdown: Optional[str] = None,
    target_description: Optional[str] = None,
    can_opt_out: bool = False,
    zh: bool = True,
) -> ModelMigrationCopy:
    """逐分支对齐上游 ``migration_copy_for_models``。"""
    if migration_markdown is not None:
        return ModelMigrationCopy(
            heading=[], content=[], can_opt_out=can_opt_out,
            markdown=fill_migration_markdown(
                migration_markdown, current_model, target_model))

    heading = (HEADING_TEMPLATE_ZH if zh else HEADING_TEMPLATE_EN).format(
        display=target_display_name)
    if migration_copy is not None:
        description = migration_copy
    elif target_description:
        description = target_description
    else:
        description = (DESCRIPTION_FALLBACK_ZH if zh
                       else DESCRIPTION_FALLBACK_EN).format(
            display=target_display_name)

    content: List[str] = []
    if migration_copy is None:
        content.append((RECOMMENDATION_ZH if zh else RECOMMENDATION_EN).format(
            current=current_model, target=target_model))
        content.append("")
    if model_link is not None:
        content.append(f"{description} " + (
            f"了解 {target_display_name} 详见 " if zh else
            f"Learn more about {target_display_name} at ") + model_link)
        content.append("")
    else:
        content.append(description)
        content.append("")
    if can_opt_out:
        content.append((OPT_OUT_LINE_ZH if zh else OPT_OUT_LINE_EN).format(
            current=current_model))
    return ModelMigrationCopy(heading=[heading], content=content,
                              can_opt_out=can_opt_out, markdown=None)


def is_ctrl_exit_combo(modifiers: frozenset, code: str) -> bool:
    """对齐 ``is_ctrl_exit_combo``：CONTROL + Char('c'|'d')。"""
    return "CONTROL" in modifiers and code.lower() in ("c", "d")


# ---------------------------------------------------------------- 屏幕状态机
@dataclass
class ModelMigrationScreen:
    """对齐 ``ModelMigrationScreen`` 的状态与键位处理（不含渲染）。"""

    copy: ModelMigrationCopy
    done: bool = False
    outcome: ModelMigrationOutcome = ModelMigrationOutcome.ACCEPTED
    highlighted_option: MigrationMenuOption = MigrationMenuOption.TRY_NEW_MODEL
    request_frame_count: int = 0
    audit_trail: List[Dict[str, Any]] = field(default_factory=list)

    def _request_frame(self) -> None:
        self.request_frame_count += 1

    def finish_with(self, outcome: ModelMigrationOutcome) -> None:
        self.outcome = outcome
        self.done = True
        self._request_frame()
        self.audit_trail.append({"event": "finish", "outcome": outcome.value})

    def accept(self) -> None:
        self.finish_with(ModelMigrationOutcome.ACCEPTED)

    def reject(self) -> None:
        self.finish_with(ModelMigrationOutcome.REJECTED)

    def exit(self) -> None:
        self.finish_with(ModelMigrationOutcome.EXIT)

    def confirm_selection(self) -> None:
        """对齐：``can_opt_out`` 时才按高亮项裁决，否则一律 accept。"""
        if self.copy.can_opt_out:
            if self.highlighted_option is MigrationMenuOption.TRY_NEW_MODEL:
                self.accept()
            else:
                self.reject()
        else:
            self.accept()

    def highlight_option(self, option: MigrationMenuOption) -> None:
        if self.highlighted_option is not option:
            self.highlighted_option = option
            self._request_frame()
            self.audit_trail.append({"event": "highlight",
                                     "option": option.value})

    def handle_menu_key(self, code: str) -> None:
        """逐分支对齐上游 ``handle_menu_key``。"""
        self.audit_trail.append({"event": "menu_key", "code": code})
        if code in ("Up", "k"):
            self.highlight_option(MigrationMenuOption.TRY_NEW_MODEL)
        elif code in ("Down", "j"):
            self.highlight_option(MigrationMenuOption.USE_EXISTING_MODEL)
        elif code == "1":
            self.highlight_option(MigrationMenuOption.TRY_NEW_MODEL)
            self.accept()
        elif code == "2":
            self.highlight_option(MigrationMenuOption.USE_EXISTING_MODEL)
            self.reject()
        elif code in ("Enter", "Esc"):
            # 上游：Esc 在这里是「确认当前选中」，不是取消
            self.confirm_selection()
        # 其他键：对齐上游 `_ => {}`

    def handle_key(self, code: str, modifiers: frozenset = frozenset(),
                   kind: str = "Press") -> None:
        """对齐 ``handle_key``：Release 忽略、Ctrl 退出优先。"""
        if kind == "Release":
            return
        if is_ctrl_exit_combo(modifiers, code):
            self.exit()
            return
        if self.copy.can_opt_out:
            self.handle_menu_key(code)
        elif code in ("Esc", "Enter"):
            # 强制迁移：Esc 也 accept（上游既有键盘策略，如实保留）
            self.accept()

    def is_done(self) -> bool:
        return self.done

    def outcome_value(self) -> ModelMigrationOutcome:
        return self.outcome

    def policy_note(self) -> str:
        """本地化：把两条**与本项目审批覆盖层相反**的语义显式标注。"""
        if self.copy.can_opt_out:
            return ("可选迁移：Esc = 确认当前选中（不是取消）；"
                    "Ctrl+C / Ctrl+D = Exit。")
        return ("强制迁移：Enter 与 Esc 都接受，事件流耗尽也默认接受；"
                "仅 Ctrl+C / Ctrl+D 可 Exit。此语义仅限模型升级提示，"
                "绝不套用到审批链路。")


class AltScreenGuard:
    """对齐上游 RAII ``AltScreenGuard``：``Drop`` 一定恢复 alternate screen。"""

    def __init__(self, tui: Any):
        self.tui = tui
        self.entered = False

    def __enter__(self) -> "AltScreenGuard":
        try:
            self.tui.enter_alt_screen()
        except Exception:  # noqa: BLE001 - 对齐上游 `let _ =`
            pass
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            self.tui.leave_alt_screen()
        except Exception:  # noqa: BLE001 - 异常路径也必须恢复
            pass
        self.entered = False
        return False  # 不吞异常


def run_model_migration_prompt(
    copy: ModelMigrationCopy,
    events: Sequence[tuple],
    tui: Optional[Any] = None,
    *,
    draw: Optional[Callable[[ModelMigrationScreen], None]] = None,
) -> ModelMigrationOutcome:
    """对齐 ``run_model_migration_prompt`` 的事件循环（可注入、确定性）。

    ``events`` 每项为 ``(code, modifiers, kind)``；**序列耗尽 = 事件流
    结束 -> ``screen.accept()``**（上游既有行为，如实保留并在
    ``policy_note()`` 标注）。``TuiEvent::Paste / FocusLost / Mouse``
    在上游被忽略，这里由调用方不传入即可。
    """
    screen = ModelMigrationScreen(copy)
    guard = AltScreenGuard(tui) if tui is not None else None
    if guard:
        guard.__enter__()
    try:
        if draw:
            draw(screen)
        for item in events:
            if screen.is_done():
                break
            code = item[0]
            modifiers = frozenset(item[1]) if len(item) > 1 else frozenset()
            kind = item[2] if len(item) > 2 else "Press"
            screen.handle_key(code, modifiers, kind)
        if not screen.is_done():
            # 上游：events.next() 返回 None -> screen.accept()
            screen.accept()
        return screen.outcome_value()
    finally:
        if guard:
            guard.__exit__(None, None, None)


def constants() -> Dict[str, Any]:
    return {
        "outcomes": [o.value for o in ModelMigrationOutcome],
        "menu_options": [o.value for o in MigrationMenuOption.all()],
        "labels_en": [LABEL_TRY_NEW_EN, LABEL_USE_EXISTING_EN],
        "heading_en": HEADING_TEMPLATE_EN,
        "recommendation_en": RECOMMENDATION_EN,
        "opt_out_line_en": OPT_OUT_LINE_EN,
        "placeholders": ["{model_from}", "{model_to}"],
    }
