"""TUI 与 OpenAI Codex CLI 的对齐层（完全相同 + 本地化）。

子模块:
  - ``upstream_spec``  上游可核验事实：规模 / 165 模块树 / 布局常量 / 键位规格
  - ``keymap``         Codex built_in_defaults 键位表 + RuntimeKeymap 解析
  - ``i18n``           Codex 英文文案的本地化（接项目 10 语言 i18n 回退链）
  - ``matrix``         逐模块对齐状态、覆盖率、差距队列

设计边界：键位、布局、组件树、交互契约与上游**完全相同**；
本地化只作用于文案、模型、路径、配色、审批作用域语义与渲染后端。
许可归属见根目录 ``NOTICE`` 第 9 条与 ``THIRD_PARTY_LICENSES/``。
"""
from __future__ import annotations

from . import upstream_spec, keymap, i18n, matrix  # noqa: F401

__all__ = ["upstream_spec", "keymap", "i18n", "matrix",
           "parity_report", "parity_validate"]


def parity_report() -> dict:
    """可观测入口：``tuan tui parity`` 直接消费。"""
    try:
        from .. import inputkit
        ik = inputkit.inputkit_report()
    except Exception as exc:  # noqa: BLE001 - 报告不能因可选层失败而崩
        ik = {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "scale": dict(upstream_spec.SCALE),
        "layout": dict(upstream_spec.LAYOUT_CONSTANTS),
        "keymap": keymap.RuntimeKeymap.defaults().coverage(),
        "i18n": {"languages": list(i18n.available_languages()),
                 "total_keys": i18n.total_keys(),
                 "translated_zh_CN": i18n.translated_count("zh-CN")},
        "inputkit": ik,
        "matrix": matrix.summary(),
        "groups": matrix.group_summary(),
    }


def parity_validate() -> list[str]:
    """自检：组件树、键位、状态覆盖是否自洽。"""
    problems = list(matrix.validate())
    try:
        keymap.RuntimeKeymap.defaults()
    except Exception as exc:  # noqa: BLE001
        problems.append(f"keymap defaults 不可用: {type(exc).__name__}: {exc}")
    for lang in ("en", "zh-CN"):
        if i18n.translated_count(lang) != i18n.total_keys():
            problems.append(f"i18n 语言 {lang} 未覆盖全部 parity 文案")
    try:
        from .. import inputkit
        problems.extend(f"inputkit: {p}" for p in inputkit.inputkit_validate())
    except Exception as exc:  # noqa: BLE001
        problems.append(f"inputkit 自检不可用: {type(exc).__name__}: {exc}")
    return problems
