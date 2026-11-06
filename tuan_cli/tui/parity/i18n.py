"""Codex TUI 文案的本地化层（「完全相同但有自己本地化」的语言部分）。

**键位、布局、组件树、交互契约与上游完全相同**；只有**呈现给人的文字**
本地化。这是刻意划的边界：改文案不会改变行为，改键位就会破坏「完全相同」。

实现策略：
- 优先复用项目已有的 10 语言 i18n（``tuan_cli.i18n.t``，回退链
  当前语言 -> zh-CN -> en -> key 本身）；
- 本模块自带 ``PARITY_MESSAGES`` 作为 parity 专属文案源，en 与 zh-CN
  全量，其余语言提供高频条目，缺失项回退到 en（绝不留空、绝不抛异常）；
- ``pt()`` 先查项目 i18n 的 ``parity.*`` 键（允许上游项目覆盖），再查
  内置表，最后回退 en。

英文串逐字来自上游 ``bottom_pane/approval_overlay.rs`` /
``popup_consts.rs`` / ``ui_consts.rs`` 等处，便于逐条核销。
"""
from __future__ import annotations

from typing import Dict, Optional

# Codex 原文（英文）与本地化译文。key 采用 ``域.动作`` 形式。
PARITY_MESSAGES: Dict[str, Dict[str, str]] = {
    "en": {
        # ---- approval_overlay.rs 的选项标签
        "approval.approve": "Yes",
        "approval.approve_for_session":
            "Yes, and don't ask again for this command in this session",
        "approval.approve_for_prefix":
            "Yes, and allow these permissions for this session",
        "approval.deny": "No",
        "approval.decline": "No, and tell the agent what to do differently",
        "approval.cancel": "Cancel",
        "approval.open_thread": "Open thread",
        "approval.title": "Approval required",
        # ---- popup_consts.rs / footer_hint.rs 的提示行
        "hint.accept_cancel": "Press {accept} to {accept_label} or {cancel} to {cancel_label}",
        "hint.approve_line":
            "Press {y} to approve  ·  {a} for this session  ·  {p} for prefix"
            "  ·  {d} to deny  ·  {n}/Esc to decline  ·  {c} to cancel",
        "hint.confirm_code":
            "High-risk action: type the exact confirmation code {code} to authorize;"
            "  any other input is rejected",
        # ---- ui_consts.rs::transcript_hint
        "hint.transcript": "{shortcut} to view transcript",
        "hint.shortcuts": "{shortcut} for shortcuts",
        # ---- 通用状态
        "status.pending": "Waiting for your decision",
        "status.approved": "Approved",
        "status.denied": "Denied",
        "status.aborted": "Aborted",
    },
    "zh-CN": {
        "approval.approve": "确认，仅本次",
        "approval.approve_for_session": "确认，本会话不再询问此命令",
        "approval.approve_for_prefix": "确认，并允许本会话使用这些权限",
        "approval.deny": "拒绝",
        "approval.decline": "拒绝，并说明希望如何调整",
        "approval.cancel": "中止",
        "approval.open_thread": "打开会话",
        "approval.title": "需要审批",
        "hint.accept_cancel": "按 {accept} {accept_label}，或按 {cancel} {cancel_label}",
        "hint.approve_line":
            "按 {y} 确认  ·  {a} 本会话不再询问  ·  {p} 允许权限前缀"
            "  ·  {d} 拒绝  ·  {n}/Esc 拒绝并调整  ·  {c} 中止",
        "hint.confirm_code":
            "高危操作：必须精确键入确认码 {code} 才授权；其它输入一律拒绝",
        "hint.transcript": "{shortcut} 查看会话记录",
        "hint.shortcuts": "{shortcut} 查看快捷键",
        "status.pending": "等待你的决策",
        "status.approved": "已批准",
        "status.denied": "已拒绝",
        "status.aborted": "已中止",
    },
    # 其余语言提供高频条目；未列条目回退 en（与项目 i18n 的回退链一致）
    "ja": {
        "approval.approve": "はい（今回のみ）",
        "approval.deny": "いいえ",
        "approval.cancel": "中止",
        "hint.transcript": "{shortcut} で履歴を表示",
    },
    "ko": {
        "approval.approve": "예 (이번만)",
        "approval.deny": "아니오",
        "approval.cancel": "중단",
    },
    "es": {
        "approval.approve": "Sí, solo esta vez",
        "approval.deny": "No",
        "approval.cancel": "Cancelar",
    },
    "fr": {
        "approval.approve": "Oui, cette fois seulement",
        "approval.deny": "Non",
        "approval.cancel": "Annuler",
    },
    "de": {
        "approval.approve": "Ja, nur diesmal",
        "approval.deny": "Nein",
        "approval.cancel": "Abbrechen",
    },
    "ru": {
        "approval.approve": "Да, только сейчас",
        "approval.deny": "Нет",
        "approval.cancel": "Отмена",
    },
    "zh-TW": {
        "approval.approve": "確認，僅本次",
        "approval.deny": "拒絕",
        "approval.cancel": "中止",
        "hint.transcript": "{shortcut} 查看會話記錄",
    },
    "pt-BR": {
        "approval.approve": "Sim, apenas desta vez",
        "approval.deny": "Não",
        "approval.cancel": "Cancelar",
    },
}

_DEFAULT_LANG = "en"
_PROJECT_LANG_ALIASES = {"zh_CN": "zh-CN", "zh_TW": "zh-TW", "pt_BR": "pt-BR"}


def _current_lang() -> str:
    try:
        from ...i18n import get_language
        return str(get_language())
    except Exception:  # noqa: BLE001 - i18n 不可用时不影响 parity 文案
        return "zh-CN"   # 项目默认中文，与 i18n/__init__.py 一致


def pt(key: str, *, lang: Optional[str] = None, **kwargs: object) -> str:
    """取本地化文案：项目 i18n -> 当前语言表 -> zh-CN -> en -> key。

    永不抛异常；格式化失败时返回未格式化的原文（不静默变空串）。
    """
    language = _PROJECT_LANG_ALIASES.get(str(lang or ""), lang) or _current_lang()

    # 1) 项目 i18n 覆盖（允许用户在 locale 文件里自定义 parity.*）
    try:
        from ...i18n import t as _t
        override = _t("parity." + key, **kwargs)
        if override and not override.startswith("parity."):
            return str(override)
    except Exception:  # noqa: BLE001
        pass

    # 2) 内置表：当前语言 -> zh-CN -> en
    text: Optional[str] = None
    for candidate in (language, "zh-CN", _DEFAULT_LANG):
        table = PARITY_MESSAGES.get(candidate)
        if table and key in table:
            text = table[key]
            break
    if text is None:
        return key
    try:
        return text.format(**kwargs) if kwargs else text
    except (KeyError, IndexError, ValueError):
        return text


def available_languages() -> tuple[str, ...]:
    return tuple(sorted(PARITY_MESSAGES))


def translated_count(lang: str) -> int:
    return len(PARITY_MESSAGES.get(lang, {}))


def total_keys() -> int:
    return len(PARITY_MESSAGES["en"])
