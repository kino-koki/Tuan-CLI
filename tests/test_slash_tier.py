# -*- coding: utf-8 -*-
"""§2 slash 命令分层 + /mode 语义冲突消解回归测试。

覆盖 tuan_cli/cli/cmd_slash.py 的:
- slash_command_tier() 对核心层/专家层返回正确值
- list_slash_commands() 返回数量 ≥ 55 (全集不变)
- /mode 旧三档别名映射 (standard→collaboration, yolo→boundless, plan→chat)
- /mode 五档新名 (gantong/lingma/chat/boundless/collaboration) 可切换
- /help 按 tier 分组 (核心层置顶)

回归背景: 26.10.23 全天代办 §2 —— 55 个 slash 命令压垮 TUI "/" 菜单,
需分层: 核心层 ≤ 20 直接显示, 专家层折叠需前缀可达。
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------- tier 分层
class TestSlashCommandTier:
    """slash_command_tier() 核心/专家层判定。"""

    def test_core_commands_return_core(self):
        from tuan_cli.cli.cmd_slash import slash_command_tier, CORE_SLASH_COMMANDS
        for name in CORE_SLASH_COMMANDS:
            assert slash_command_tier(name) == "core", f"{name} 应在核心层"

    def test_expert_commands_return_expert(self):
        from tuan_cli.cli.cmd_slash import slash_command_tier, CORE_SLASH_COMMANDS
        expert = [
            "/audit", "/blast", "/budget", "/checkpoint", "/effort",
            "/goal", "/hooks", "/image", "/images", "/impact", "/import",
            "/log", "/mcp-tools", "/more", "/offline", "/provider",
            "/quit", "/resume", "/route", "/sandbox", "/stats", "/subagent",
            "/swarm", "/verify", "/rewind", "/handoff", "/worktree",
            "/workflow", "/code", "/commands", "/personality", "/init",
            "/add-dir", "/clear-images", "/gh-borrow", "/image",
        ]
        for name in expert:
            assert name not in CORE_SLASH_COMMANDS, f"{name} 不应在核心层"
            assert slash_command_tier(name) == "expert", f"{name} 应为专家层"

    def test_unknown_command_returns_expert(self):
        """用户自定义热插拔命令归入 expert, 保证可见性。"""
        from tuan_cli.cli.cmd_slash import slash_command_tier
        assert slash_command_tier("/my-custom-cmd") == "expert"

    def test_tiers_dict_covers_all_commands(self):
        from tuan_cli.cli.cmd_slash import slash_command_tiers, list_slash_commands
        tiers = slash_command_tiers()
        for name in list_slash_commands():
            assert name in tiers, f"{name} 应在 tiers 字典中"
            assert tiers[name] in ("core", "expert", "hidden")

    def test_core_size_at_most_20(self):
        from tuan_cli.cli.cmd_slash import CORE_SLASH_COMMANDS
        assert len(CORE_SLASH_COMMANDS) <= 20, f"核心层 {len(CORE_SLASH_COMMANDS)} 项 > 20"


# ---------------------------------------------------------------- 全集不变
class TestListSlashCommandsUnchanged:
    """list_slash_commands() 返回全集 ≥ 55, 分层不改变它。"""

    def test_returns_at_least_55(self):
        from tuan_cli.cli.cmd_slash import list_slash_commands
        names = list_slash_commands()
        assert len(names) >= 55, f"全集 {len(names)} < 55"

    def test_all_names_have_slash_prefix(self):
        from tuan_cli.cli.cmd_slash import list_slash_commands
        for n in list_slash_commands():
            assert n.startswith("/"), f"{n} 应有 / 前缀"

    def test_core_and_expert_disjoint_and_cover(self):
        """核心 + 专家 = 全集, 且互不相交。"""
        from tuan_cli.cli.cmd_slash import (
            slash_command_tiers, list_slash_commands,
        )
        tiers = slash_command_tiers()
        all_names = list_slash_commands()
        core = [n for n in all_names if tiers.get(n) == "core"]
        expert = [n for n in all_names if tiers.get(n) == "expert"]
        assert not (set(core) & set(expert)), "核心/专家层不应相交"
        assert set(core) | set(expert) == set(all_names), "核心+专家应覆盖全集"


# ---------------------------------------------------------------- /mode 别名
class TestModeAlias:
    """/mode 旧三档别名映射: standard→collaboration, yolo→boundless, plan→chat。

    /mode 现使用 switch_mode (R1-R7 规则校验), 测试需 mock switch_mode 与 current_mode。
    """

    def _handle_mode(self, arg: str):
        """调用 /mode 处理函数, mock switch_mode 捕获切换请求。"""
        captured_info = []
        captured_success = []
        captured_switch = {}

        class FakeUi:
            def info(self, msg):
                captured_info.append(msg)

            def success(self, msg):
                captured_success.append(msg)

            def warning(self, msg):
                captured_info.append(msg)

            def error(self, msg):
                raise AssertionError(f"不应报错: {msg}")

        with patch("tuan_cli.cli.cmd_slash.ui", FakeUi()):
            with patch("tuan_cli.modes.switcher.switch_mode",
                       side_effect=lambda target, force=False: (
                           captured_switch.__setitem__("target", target) or captured_switch.__setitem__("force", force) or (True, "ok")
                       )):
                with patch("tuan_cli.modes.switcher.current_mode", return_value="chat"):
                    from tuan_cli.cli.cmd_slash import _handle_slash
                    class FakeConfig:
                        def get(self, key, default=None):
                            return default
                        def set_user(self, key, value):
                            pass
                    _handle_slash(f"/mode {arg}", None, FakeConfig(), ".")
        return captured_switch, captured_info, captured_success

    def test_standard_maps_to_collaboration(self):
        switch_data, infos, _ = self._handle_mode("standard")
        assert switch_data.get("target") == "standard"
        # 别名提示
        assert any("standard" in m and "collaboration" in m for m in infos)

    def test_yolo_maps_to_boundless(self):
        switch_data, infos, _ = self._handle_mode("yolo")
        assert switch_data.get("target") == "yolo"
        assert any("yolo" in m and "boundless" in m for m in infos)

    def test_plan_maps_to_chat(self):
        switch_data, infos, _ = self._handle_mode("plan")
        assert switch_data.get("target") == "plan"
        assert any("plan" in m and "chat" in m for m in infos)

    def test_new_names_no_alias_hint(self):
        """新五档直接切换, 无别名提示。"""
        for name in ("gantong", "lingma", "chat", "boundless", "collaboration"):
            switch_data, infos, _ = self._handle_mode(name)
            assert switch_data.get("target") == name
            # 不应有别名提示
            assert not any("别名" in m for m in infos), f"{name} 不应触发别名提示"

    def test_old_names_case_insensitive(self):
        """别名映射大小写不敏感。"""
        for arg in ("Standard", "YOLO", "PLAN", "Standard", "Yolo", "Plan"):
            switch_data, infos, _ = self._handle_mode(arg)
            assert switch_data.get("target") is not None

    def test_mode_description_updated(self):
        """_CMD_META["/mode"] 描述已更新。"""
        from tuan_cli.cli.cmd_slash import slash_command_meta
        meta = slash_command_meta()
        desc = meta.get("/mode", "")
        assert "感通" in desc
        assert "灵码" in desc
        assert "闲聊" in desc
        assert "无界" in desc
        assert "协同" in desc
        assert "standard" in desc  # 旧名仍提示可用


# ---------------------------------------------------------------- /mode 五档
class TestModeFiveTiers:
    """/mode 五档新名 (gantong/lingma/chat/boundless/collaboration) 可切换。"""

    def _handle_mode(self, arg: str):
        captured_switch = {}

        class FakeUi:
            def info(self, msg):
                pass

            def success(self, msg):
                pass

            def warning(self, msg):
                pass

            def error(self, msg):
                raise AssertionError(f"不应报错: {msg}")

        with patch("tuan_cli.cli.cmd_slash.ui", FakeUi()):
            with patch("tuan_cli.modes.switcher.switch_mode",
                       side_effect=lambda target, force=False: (
                           captured_switch.__setitem__("target", target) or (True, "ok")
                       )):
                with patch("tuan_cli.modes.switcher.current_mode", return_value="chat"):
                    from tuan_cli.cli.cmd_slash import _handle_slash
                    class FakeConfig:
                        def get(self, key, default=None):
                            return default
                        def set_user(self, key, value):
                            pass
                    _handle_slash(f"/mode {arg}", None, FakeConfig(), ".")
        return captured_switch

    def test_all_five_modes_accepted(self):
        """五档新名均可切换, 不报错。"""
        for mode_name in ("gantong", "lingma", "chat", "boundless", "collaboration"):
            switch_data = self._handle_mode(mode_name)
            assert switch_data.get("target") == mode_name

    def test_all_modes_stored_as_canonical_id(self):
        """映射后的存储值是规范 ID。"""
        expected = {
            "standard": "standard",
            "yolo": "yolo",
            "plan": "plan",
            "gantong": "gantong",
            "lingma": "lingma",
            "chat": "chat",
            "boundless": "boundless",
            "collaboration": "collaboration",
        }
        for arg, expected_id in expected.items():
            switch_data = self._handle_mode(arg)
            assert switch_data.get("target") == expected_id, f"/mode {arg} 应存储 {expected_id}"

    def test_empty_mode_shows_current(self):
        """无参数 /mode 显示当前模式, 不报错。"""
        captured_info = []

        class FakeUi:
            def info(self, msg):
                captured_info.append(msg)

            def success(self, msg):
                captured_info.append(msg)

            def error(self, msg):
                raise AssertionError(f"不应报错: {msg}")

        class FakeConfig:
            def __init__(self):
                self.mode = "collaboration"

            def set_user(self, key, value):
                pass

            def get(self, key, default=None):
                return default

        with patch("tuan_cli.cli.cmd_slash.ui", FakeUi()):
            from tuan_cli.cli.cmd_slash import _handle_slash
            cfg = FakeConfig()
            _handle_slash("/mode", None, cfg, ".")
        assert any("collaboration" in m for m in captured_info)


# ---------------------------------------------------------------- /help 分组
class TestHelpGroupedByTier:
    """/help 按 tier 分组显示: 核心层置顶, 专家层折叠。"""

    def test_help_text_has_core_section(self):
        from tuan_cli.cli.cmd_slash import _HELP
        assert "核心层" in _HELP
        assert "Core" in _HELP

    def test_help_text_has_expert_section(self):
        from tuan_cli.cli.cmd_slash import _HELP
        assert "专家层" in _HELP
        assert "Expert" in _HELP

    def test_core_commands_listed_in_core_section(self):
        """核心层命令出现在核心区段。"""
        from tuan_cli.cli.cmd_slash import _HELP, CORE_SLASH_COMMANDS
        # 找到核心层和专家层之间的分割
        core_section = _HELP.split("── 专家层")[0]
        for name in CORE_SLASH_COMMANDS:
            assert name in core_section, f"{name} 应在核心层区段"

    def test_expert_commands_marked_with_bracket(self):
        """专家层命令带 [...] 折叠标记。"""
        from tuan_cli.cli.cmd_slash import _HELP
        expert_section = _HELP.split("── 专家层")[1]
        for name in ("/audit", "/blast", "/budget", "/checkpoint", "/goal", "/init", "/offline"):
            assert f"[...]{name}" in expert_section, f"{name} 应有 [...] 折叠标记"

    def test_help_core_before_expert(self):
        """核心层区段在专家层区段之前。"""
        from tuan_cli.cli.cmd_slash import _HELP
        core_pos = _HELP.index("核心层")
        expert_pos = _HELP.index("专家层")
        assert core_pos < expert_pos


# ---------------------------------------------------------------- 回归兼容
class TestSlashCompleterTiers:
    """_SlashCompleter 传入 tiers 后空前缀仅返回核心层。"""

    def test_empty_prefix_filters_to_core(self):
        from tuan_cli.tui.tui import _SlashCompleter

        class FakeDoc:
            text_before_cursor = "/"

        words = ["/help", "/model", "/audit", "/blast", "/mode", "/clear"]
        tiers = {
            "/help": "core", "/model": "core", "/mode": "core", "/clear": "core",
            "/audit": "expert", "/blast": "expert",
        }
        comp = _SlashCompleter(words, tiers=tiers)
        items = list(comp.get_completions(FakeDoc(), None))
        # prompt_toolkit 的 Completion.display 是 FormattedText 对象, 取纯文本要用
        # display_text —— 拿 display 直接和字符串比会永远 False。
        displays = [it.display_text for it in items]
        assert "/help" in displays
        assert "/audit" not in displays
        assert "/blast" not in displays

    def test_prefix_searches_all_tiers(self):
        """输入前缀时保留全量匹配 (专家层命令按前字母可达)。"""
        from tuan_cli.tui.tui import _SlashCompleter

        class FakeDoc:
            # 前缀必须是 "/a": "/add-dir" 里没有字母 u, 用 "/au" 的话它按前缀/
            # 子串/子序列任何一种模糊规则都匹配不上, 用例本身就不自洽。
            # "/a" 同时覆盖 "/audit" 与 "/add-dir" 两条专家层命令, 原意不变。
            text_before_cursor = "/a"

        words = ["/help", "/audit", "/add-dir", "/model"]
        tiers = {
            "/help": "core", "/model": "core",
            "/audit": "expert", "/add-dir": "expert",
        }
        comp = _SlashCompleter(words, tiers=tiers)
        items = list(comp.get_completions(FakeDoc(), None))
        # prompt_toolkit 的 Completion.display 是 FormattedText 对象, 取纯文本要用
        # display_text —— 拿 display 直接和字符串比会永远 False。
        displays = [it.display_text for it in items]
        assert "/audit" in displays
        assert "/add-dir" in displays
        assert "/help" not in displays  # 不匹配前缀

    def test_no_tiers_backward_compatible(self):
        """不传 tiers 时保留旧行为: 空输入返回全部命令。"""
        from tuan_cli.tui.tui import _SlashCompleter

        class FakeDoc:
            text_before_cursor = "/"

        words = ["/help", "/model", "/audit"]
        comp = _SlashCompleter(words)  # 不传 tiers
        items = list(comp.get_completions(FakeDoc(), None))
        assert len(items) == 3


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))