"""Tuan TUI 配置/侧栏对齐层（第 13 轮）。

逐模块对齐 OpenAI Codex ``codex-rs/tui/src`` 的 ``config_models`` +
``misc`` 两组共 5 个待办模块，纯 Python 独立实现，零 Rust 源码复制。
每个模块 docstring 都列出上游契约与本地化修改点；许可见 ``NOTICE``
第 13 条。

| 上游模块 | 本包模块 | 对齐要点 |
|---|---|---|
| ``additional_dirs.rs`` | ``additional_dirs`` | 4 个早退分支、警告模板原文、**忽略即拒绝的结构化 fail-closed 决策** |
| ``collaboration_modes.rs`` | ``collaboration_modes`` | tui_visible 筛选 / Default 回退 / 循环 next / 2s 发现超时 / ``Some(None)`` 清覆盖 / **发现失败不冒充空列表** |
| ``model_migration.rs`` | ``model_migration`` | 三态 Outcome / 两态菜单 / 强制与可选键位策略 / Ctrl+C·D 退出 / RAII alt screen / **模板单次替换修链式二次替换** |
| ``sidebar_chooser.rs`` | ``sidebar_chooser`` | ``WIDE_WIDTH=58`` / 窄屏双行分页 / ``choice_at`` 命中 / footer 三项 + hide_pane / 短提示逐字 |
| ``sidebar_tab_strip.rs`` | ``sidebar_tab_strip`` | 三态 TabState / ``targets()`` 几何逐值 / add 优先命中 / **hit 与 render 共用几何** |

**本轮最值钱的三条修正**（都不是"对齐"本身）：

1. **链式 replace 二次替换**：上游 ``fill_migration_markdown`` 先 replace
   ``{model_from}`` 再 replace ``{model_to}``；若 ``current_model`` 含字面量
   ``{model_to}``（模型名来自服务端/配置，可被污染），会被二次替换成
   ``target_model``。已实测并改为**单次正则扫描**，替换值不参与后续匹配。
2. **发现失败不能静默当空**：上游 ``collaboration_modes::list()`` 把超时、
   RPC 错误、协议错误一律压成空 Vec + warn（模块头 "Missing discovery
   adds no presets"）。调用方无法区分「没查到」与「查了但没有」，一个网络
   错误会被当成「无需展示模式选择器」。本包用 ``DiscoveryResult`` 显式
   区分 5 种状态，``usable`` 只允许 ok/empty。
3. **``--add-dir`` 不能静默丢弃**：上游只返回一句警告字符串让调用方
   "负责呈现"，忘了打印就等于静默忽略。本包升级为 ``AddDirDecision``
   + ``enforce()``，**忽略即拒绝**，并做路径逃逸/控制字符校验。

另外两条正确性契约：``choice_rows`` 是渲染分页、``choice_at`` 是命中
测试，二者共用同一份几何（防"点第 3 项打开第 2 项"）；``TabStrip.hit``
与 ``render_plan`` 共用 ``targets()``（防"点到的和看到的不一致"）。
两处都提供 ``*_matches_render()`` 自检并进回归集。

**硬约束延续**：``validate()`` 会调用第 12 轮的
``corekit.app.assert_wiring_intact()``，确认本轮没有破坏前 12 轮修好的
6 条既有安全接线。本轮**同样没有替换任何现有运行时对象**。

本地化边界：渲染后端、中文文案、CJK 显示宽度近似（如实标注）、严格字段
白名单、结构化拒绝、单次模板替换。**键位、几何常量、状态机分支、
契约语义不改**。
"""
from __future__ import annotations

from . import (
    additional_dirs, collaboration_modes, model_migration,
    sidebar_chooser, sidebar_tab_strip,
)

__all__ = [
    "additional_dirs", "collaboration_modes", "model_migration",
    "sidebar_chooser", "sidebar_tab_strip",
    "configkit_report", "configkit_validate", "MODULES",
]

MODULES = (
    "additional_dirs", "collaboration_modes", "model_migration",
    "sidebar_chooser", "sidebar_tab_strip",
)


def configkit_report() -> dict:
    """可观测入口：被 ``tuan tui parity`` 消费。"""
    return {
        "modules": len(MODULES),
        "upstream_groups": ["config_models", "misc"],
        "additional_dirs": additional_dirs.constants(),
        "collaboration_modes": collaboration_modes.constants(),
        "model_migration": model_migration.constants(),
        "sidebar_chooser": sidebar_chooser.constants(),
        "sidebar_tab_strip": sidebar_tab_strip.constants(),
    }


def configkit_validate() -> list[str]:
    """自检：常量、契约、几何一致性与**既有安全接线**。"""
    problems: list[str] = []

    # ---- 逐值常量核销
    ad = additional_dirs.constants()
    if "Switch to workspace-write or danger-full-access" not in \
            ad["warning_template_en"]:
        problems.append("additional_dirs 警告模板不等于上游原文")
    if ad["early_return_branches"] != 4:
        problems.append("additional_dirs 早退分支数不是 4")
    cm = collaboration_modes.constants()
    if cm["timeout_secs"] != 2:
        problems.append("collaboration_modes 发现超时不是 2s")
    if cm["request_prefix"] != "collaboration-mode-list-":
        problems.append("collaboration_modes 请求 id 前缀不对")
    if cm["mask_fields"] != ["name", "mode", "model", "reasoning_effort",
                             "developer_instructions"]:
        problems.append("collaboration_modes mask 字段白名单不对")
    mm = model_migration.constants()
    if mm["outcomes"] != ["Accepted", "Rejected", "Exit"]:
        problems.append("ModelMigrationOutcome 三态不对")
    if mm["labels_en"] != ["Try new model", "Use existing model"]:
        problems.append("迁移菜单两个英文 label 不对")
    if mm["placeholders"] != ["{model_from}", "{model_to}"]:
        problems.append("迁移模板占位符不对")
    sc = sidebar_chooser.constants()
    if sc["wide_width"] != 58 or sc["chat_tab"] != " Side chat ":
        problems.append("sidebar_chooser WIDE_WIDTH / CHAT_TAB 不对")
    if sc["chat_tab_width"] != 11:
        problems.append("CHAT_TAB 宽度不是 11")
    if sc["resize_short_hint"] != "←/→ resize · Enter/Esc done":
        problems.append("短 resize 提示不等于上游原文")
    st = sidebar_tab_strip.constants()
    if (st["plus_width"], st["right_reserve"], st["add_label"]) != \
            (3, 1, " + "):
        problems.append("sidebar_tab_strip 几何常量不对")

    # ---- 安全契约核销
    # 1) 链式 replace 二次替换已修
    tpl = "从 {model_from} 迁移到 {model_to}"
    cur, tgt = "old-{model_to}-x", "NEW"
    out = model_migration.fill_migration_markdown(tpl, cur, tgt)
    if "{model_to}" not in out or "old-NEW-x" in out:
        problems.append("迁移模板仍存在链式二次替换")

    # 2) 发现失败不冒充空
    def boom(_rid, _params):
        raise RuntimeError("network down")
    r = collaboration_modes.discover(requester=boom)
    if r.usable or r.status is not collaboration_modes.DiscoveryStatus.UNAVAILABLE:
        problems.append("发现失败被当成可用空列表")
    r2 = collaboration_modes.discover(
        requester=lambda rid, params: {"data": []})
    if r2.status is not collaboration_modes.DiscoveryStatus.EMPTY or not r2.usable:
        problems.append("真正的空列表被误判")

    # 3) --add-dir 忽略即拒绝
    d = additional_dirs.decide_add_dirs(
        ["/tmp/extra"], additional_dirs.PermissionProfileView.read_only(),
        "/tmp/project")
    if not d.ignored or additional_dirs.enforce(d)["allowed"] is not False:
        problems.append("read-only 下 --add-dir 未 fail-closed")
    d2 = additional_dirs.decide_add_dirs(
        ["/tmp/extra"],
        additional_dirs.PermissionProfileView.workspace_write(),
        "/tmp/project")
    if d2.ignored or additional_dirs.enforce(d2)["effective_dirs"] != ["/tmp/extra"]:
        problems.append("workspace-write 下 --add-dir 被错误忽略")
    d3 = additional_dirs.decide_add_dirs(
        ["../escape"], additional_dirs.PermissionProfileView.workspace_write(),
        "/tmp/project")
    if not d3.ignored or d3.reason != "invalid_paths":
        problems.append("路径逃逸未被拒绝")

    # 4) 几何一致性：hit 与 render 共用 targets
    area = sidebar_tab_strip.Rect(0, 0, 40, 1)
    ts = sidebar_tab_strip.TabStrip(ids=("a", "b", "c"),
                                    selected="b", tab_width=11)
    label = lambda i, ident: f" Side {i+1} "
    problems.extend(f"tab_strip: {p}" for p in
                    ts.hit_test_matches_render(
                        area, sidebar_tab_strip.TabState.ABSENT,
                        sidebar_tab_strip.TabState.ACTIVE, label))
    ca = sidebar_tab_strip.Rect(0, 0, 80, 20)
    problems.extend(f"sidebar_chooser: {p}" for p in
                    sidebar_chooser.hit_test_matches_render(ca, ["s1", "s2"], 1))

    # 5) 强制迁移 Esc 也 accept（上游既有策略，如实保留但必须可核验）
    forced = model_migration.ModelMigrationCopy(can_opt_out=False)
    screen = model_migration.ModelMigrationScreen(forced)
    screen.handle_key("Esc")
    if screen.outcome_value() is not model_migration.ModelMigrationOutcome.ACCEPTED:
        problems.append("强制迁移 Esc 语义异常")
    screen2 = model_migration.ModelMigrationScreen(
        model_migration.ModelMigrationCopy(can_opt_out=True))
    screen2.handle_key("2")
    if screen2.outcome_value() is not model_migration.ModelMigrationOutcome.REJECTED:
        problems.append("可选迁移 2 -> reject 语义异常")

    # ---- 硬约束：既有安全接线（第 12 轮引入，本轮延续）
    try:
        from ..corekit.app import assert_wiring_intact
        w = assert_wiring_intact()
        if not w.intact:
            problems.extend(f"既有安全接线: {p}" for p in w.problems)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"既有安全接线校验不可用: {type(exc).__name__}: {exc}")
    return problems
