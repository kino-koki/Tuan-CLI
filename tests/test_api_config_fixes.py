# -*- coding: utf-8 -*-
"""API 配置修复回归测试: key 规范化 / tuan -v / 状态栏 env / zen 前缀提示。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.config.loader import normalize_api_key, persist_api_key, read_api_key  # noqa: E402


# ---------------------------------------------------------------- normalize_api_key
class TestNormalizeApiKey:
    @pytest.mark.parametrize("raw,expect", [
        ("  sk-abc123  ", "sk-abc123"),
        ("Bearer sk-abc123", "sk-abc123"),
        ("bearer sk-abc123", "sk-abc123"),
        ("  BEARER  sk-abc123  ", "sk-abc123"),
        ('"sk-abc123"', "sk-abc123"),
        ("'sk-abc123'", "sk-abc123"),
        ("zen_abc123\n这是粘贴的多余行", "zen_abc123"),
        ("nvapi-xyz", "nvapi-xyz"),
        ("", ""),
        ("   ", ""),
    ])
    def test_forms(self, raw, expect):
        assert normalize_api_key(raw) == expect

    def test_zen_key_kept(self):
        assert normalize_api_key("zen_abc123") == "zen_abc123"

    def test_nim_key_kept(self):
        assert normalize_api_key("nvapi-abc123") == "nvapi-abc123"


# ---------------------------------------------------------------- persist 规范化
class TestPersistNormalizes:
    def test_persist_strips_bearer(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TUAN_HOME", str(tmp_path))
        persist_api_key("OPENCODE_ZEN_API_KEY", "Bearer zen_abc123", home=tmp_path)
        assert read_api_key("OPENCODE_ZEN_API_KEY", home=tmp_path) == "zen_abc123"

    def test_persist_strips_whitespace(self, tmp_path):
        persist_api_key("NVIDIA_API_KEY", "  nvapi-abc  ", home=tmp_path)
        assert read_api_key("NVIDIA_API_KEY", home=tmp_path) == "nvapi-abc"


# ---------------------------------------------------------------- tuan -v 不启动 TUI
class TestVerboseFlagCli:
    def test_verbose_alone_prints_version_no_tui(self, tmp_path, monkeypatch, capsys):
        """tuan -v (无子命令) 应打印版本与用法, 不进入交互 TUI。"""
        monkeypatch.setenv("TUAN_HOME", str(tmp_path))
        called = {}

        def fake_fast_chat(args):
            called["fast_chat"] = True
            return 0

        import tuan_cli.cli.parser as parser_mod
        monkeypatch.setattr(sys, "argv", ["tuan", "-v"])
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        # 阻止真实日志配置干扰
        monkeypatch.setattr(parser_mod.sys, "stdin", sys.stdin)
        import tuan_cli.cli.fast_start as fs
        monkeypatch.setattr(fs, "fast_chat", fake_fast_chat)
        # parser.main 内部用 from .fast_start import fast_chat —— 需 patch 目标模块后重载引用
        import importlib
        importlib.reload(parser_mod)
        rc = parser_mod.main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "tuan" in out and "verbose" in out
        assert not called.get("fast_chat"), "tuan -v 不应进入交互 TUI"

    def test_verbose_with_subcommand_ok(self, tmp_path, monkeypatch):
        """tuan -v chat 顶层 -v 搭配子命令仍走子命令 (不误伤正常用法)。"""
        monkeypatch.setenv("TUAN_HOME", str(tmp_path))
        import tuan_cli.cli.parser as parser_mod
        monkeypatch.setattr(sys, "argv", ["tuan", "-v", "models"])
        args = parser_mod.build_parser().parse_args()
        assert args.cmd == "models"
        assert args.verbose == 1


# ---------------------------------------------------------------- 状态栏 env 提示
class TestNoKeyEnv:
    def test_no_key_env_helper(self):
        from tuan_cli.cli.cmd_chat import _no_key_env

        class FakeCfg:
            def get(self, dotted, default=None):
                if dotted == "model.api_key_env":
                    return "NVIDIA_API_KEY"
                return default

        assert _no_key_env(FakeCfg()) == "NVIDIA_API_KEY"

    def test_no_key_env_default(self):
        from tuan_cli.cli.cmd_chat import _no_key_env

        class FakeCfg:
            def get(self, dotted, default=None):
                return default

        assert _no_key_env(FakeCfg()) == "DEEPSEEK_API_KEY"

    def test_tui_renders_env(self):
        """TUI 状态栏用 env 名渲染, i18n 含 {env} 占位。"""
        from tuan_cli.i18n import t
        zh = t("tui.no_key_hint", env="NVIDIA_API_KEY")
        assert "NVIDIA_API_KEY" in zh
        assert "API Key" not in zh or "未配置" in zh  # 不再是无 env 的笼统提示

    def test_all_locales_have_env_placeholder(self):
        import importlib
        import pkgutil
        import tuan_cli.i18n.locales as loc
        for m in pkgutil.iter_modules(loc.__path__):
            if m.name in ("__init__",):
                continue
            mod = importlib.import_module(f"tuan_cli.i18n.locales.{m.name}")
            text = getattr(mod, "STRINGS", {}) or getattr(mod, "MESSAGES", {}) or {}
            # 各 locale 模块导出形式不同, 直接检查模块源码含 {env}
            src = Path(mod.__file__).read_text(encoding="utf-8")
            assert "{env}" in src, f"{m.name} no_key_hint 缺少 {{env}}"


# ---------------------------------------------------------------- zen key 前缀提示
class TestZenKeyHint:
    def test_zen_preset_has_key_hint(self):
        from tuan_cli.models.provider_catalog import get_provider

        zen = get_provider("opencode-zen")
        assert zen is not None
        assert zen.api_key_env == "OPENCODE_ZEN_API_KEY"
        assert "zen_" in (zen.key_hint or "")

    def test_nim_preset_has_key_hint(self):
        from tuan_cli.models.provider_catalog import get_provider

        nim = get_provider("nvidia-nim")
        assert nim is not None
        assert nim.api_key_env == "NVIDIA_API_KEY"
        assert "nvapi-" in (nim.key_hint or "")


# ---------------------------------------------------------------- adapter 双 Bearer 防御
class TestAdapterBearerDefense:
    def test_openai_compat_strips_double_bearer(self):
        from tuan_cli.models.openai_compat import OpenAICompatAdapter

        a = OpenAICompatAdapter("https://example.com/v1", "m", "Bearer sk-abc")
        assert a._api_key == "sk-abc"
        b = OpenAICompatAdapter("https://example.com/v1", "m", "zen_abc")
        assert b._api_key == "zen_abc"
