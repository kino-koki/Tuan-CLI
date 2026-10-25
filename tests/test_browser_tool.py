"""浏览器工具 (Browser Use 集成) 测试。

browser-use 是可选 extra, 本测试套件**故意不安装它**, 用来锁定三件事:
1. 依赖缺失时工具返回安装指引, 而不是让 ImportError 炸掉 Agent 循环;
2. 前置探测函数 (包探测 / Chromium 探测) 语义正确;
3. 未装依赖时 _make_llm 抛出的是 RuntimeError, 便于上层转成用户可读提示。
"""

from __future__ import annotations

import importlib
import sys
from typing import Any
from unittest.mock import patch

import pytest

from tuan_cli.tools.browser import (
    INSTALL_HINT,
    BrowserPlugin,
    _drop_sessions,
    _make_llm,
    _preflight,
    _rel,
    browser_close,
    browser_status,
    browser_task,
    browser_use_available,
    chromium_available,
    chromium_install_hint,
)
from tuan_cli.tools.base import ToolContext


# ------------------------------------------------------- 工具上下文替身


class _Cfg(dict):
    """config.get 语义的最小替身 (dict 本身就有 get)。"""


class _Kernel:
    """kernel.get/require 的最小替身: config 与 tool_registry 各走各的。"""

    def __init__(self, config: Any = None, registry: Any = None) -> None:
        self._config = config
        self._registry = registry

    def get(self, name: str) -> Any:
        return self._config

    def require(self, name: str) -> Any:
        return self._registry


class _FakeRegistry:
    def __init__(self) -> None:
        self.registered = []

    def register(self, tool) -> None:
        self.registered.append(tool)


def _ctx(config: Any = None, registry: Any = None) -> ToolContext:
    return ToolContext(workspace=".", kernel=_Kernel(config, registry))


# ------------------------------------------------------- 前置探测


class TestPreflight:
    def test_browser_use_available_false_or_true(self):
        """探测结果必须是布尔值, 且与 importlib 结论一致。"""
        got = browser_use_available()
        assert isinstance(got, bool)
        spec = importlib.util.find_spec("browser_use")
        assert got is (spec is not None)

    def test_chromium_available_returns_bool(self):
        assert isinstance(chromium_available(), bool)

    def test_chromium_hint_mentions_install(self):
        hint = chromium_install_hint()
        assert "browser-use install" in hint

    def test_preflight_reports_missing_dep_first(self):
        """依赖缺失时, 消息必须是安装指引而不是 Chromium 提示。"""
        with patch("tuan_cli.tools.browser.browser_use_available", return_value=False):
            msg = _preflight()
            assert msg is not None
            assert "browser-use" in msg

    def test_preflight_reports_missing_chromium_second(self):
        with patch("tuan_cli.tools.browser.browser_use_available", return_value=True), \
                patch("tuan_cli.tools.browser.chromium_available", return_value=False):
            msg = _preflight()
            assert msg is not None
            # 缺 Chromium 时的提示必须指向 Chromium 本体, 而不是依赖包
            assert "Chromium" in msg or "chromium" in msg

    def test_preflight_ok(self):
        with patch("tuan_cli.tools.browser.browser_use_available", return_value=True), \
                patch("tuan_cli.tools.browser.chromium_available", return_value=True):
            assert _preflight() is None


# ------------------------------------------------------- 优雅降级 (核心)


class TestGracefulDegradation:
    """缺依赖 / 缺 LLM 凭据都不能抛异常, 必须返回可读文本。"""

    def test_browser_task_no_deps_returns_install_hint(self):
        with patch("tuan_cli.tools.browser.browser_use_available", return_value=False):
            out = browser_task(task="打开 example.com", ctx=_ctx(_Cfg()), max_steps=5)
        assert isinstance(out, str)
        assert "browser-use" in out
        assert "tuan-cli[browser]" in out

    def test_browser_task_no_chromium_returns_hint(self):
        with patch("tuan_cli.tools.browser.browser_use_available", return_value=True), \
                patch("tuan_cli.tools.browser.chromium_available", return_value=False):
            out = browser_task(task="打开 example.com", ctx=_ctx(_Cfg()))
        assert isinstance(out, str)
        assert "Chromium" in out or "chromium" in out

    def test_browser_task_empty_task_rejected(self):
        with patch("tuan_cli.tools.browser.browser_use_available", return_value=True), \
                patch("tuan_cli.tools.browser.chromium_available", return_value=True):
            out = browser_task(task="   ", ctx=_ctx(_Cfg()))
        assert isinstance(out, str)
        assert "task" in out

    def test_browser_task_missing_llm_key_is_readable(self):
        """前置通过但 LLM 凭据全缺时, 返回文本而不是抛 RuntimeError。"""
        with patch("tuan_cli.tools.browser.browser_use_available", return_value=True), \
                patch("tuan_cli.tools.browser.chromium_available", return_value=True), \
                patch("tuan_cli.tools.browser._make_llm",
                      side_effect=RuntimeError("未找到可用的浏览器 LLM 凭据")):
            out = browser_task(task="去 example.com 抓标题", ctx=_ctx(_Cfg()))
        assert isinstance(out, str)
        assert "初始化浏览器失败" in out
        assert "LLM 凭据" in out

    def test_browser_status_without_deps(self):
        """依赖全缺时给出一句话指引, 不抛异常。"""
        with patch("tuan_cli.tools.browser.browser_use_available", return_value=False), \
                patch("tuan_cli.tools.browser.chromium_available", return_value=False):
            out = browser_status(_ctx(_Cfg()))
        assert isinstance(out, str)
        assert "browser-use" in out
        assert "未安装" in out

    def test_browser_status_full_report(self):
        cfg = _Cfg({"tools.browser.llm": "openai:gpt-4.1-mini", "tools.browser.headless": True})
        with patch("tuan_cli.tools.browser.browser_use_available", return_value=True), \
                patch("tuan_cli.tools.browser.chromium_available", return_value=True):
            out = browser_status(_ctx(cfg))
        assert isinstance(out, str)
        assert "openai:gpt-4.1-mini" in out
        assert "已找到" in out

    def test_browser_close_no_sessions(self):
        _drop_sessions()
        out = browser_close(_ctx(_Cfg()))
        assert isinstance(out, str)
        assert "0" in out

    def test_make_llm_unknown_family_raises(self, monkeypatch):
        """既不是已知 family、又没有任何环境变量, 必须报可读错误。"""
        for k in ("BROWSER_USE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        with pytest.raises(RuntimeError) as ei:
            _make_llm("not-a-real-family")
        msg = str(ei.value)
        assert "not-a-real-family" in msg or "LLM 凭据" in msg

    def test_make_llm_openai_without_key_raises(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(RuntimeError) as ei:
            _make_llm("openai:gpt-4.1-mini")
        assert "OPENAI_API_KEY" in str(ei.value)


# ------------------------------------------------------- 工具注册


class TestPluginRegistration:
    def test_browser_extra_declared(self):
        import pathlib
        import tomllib
        text = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"
        data = tomllib.loads(text.read_text(encoding="utf-8"))
        extras = data["project"]["optional-dependencies"]
        assert "browser" in extras
        assert any("browser-use" in d for d in extras["browser"])
        # 版本区间要限定上界, 防止大版本破坏
        assert any("<1.0" in d for d in extras["browser"])

    def test_plugin_registers_three_tools_when_enabled(self):
        reg = _FakeRegistry()
        BrowserPlugin().activate(_Kernel(_Cfg({"tools.browser.enabled": True}), reg))
        names = sorted(t.name for t in reg.registered)
        assert names == ["browser_close", "browser_status", "browser_task"]

    def test_plugin_disables_via_config(self):
        reg = _FakeRegistry()
        BrowserPlugin().activate(_Kernel(_Cfg({"tools.browser.enabled": False}), reg))
        assert reg.registered == []

    def test_plugin_default_enabled_when_config_absent(self):
        reg = _FakeRegistry()
        BrowserPlugin().activate(_Kernel(None, reg))
        # 无配置时默认启用
        assert len(reg.registered) == 3

    def test_browser_task_registered_non_readonly(self):
        """浏览器能执行 JS、下载文件, 不能标 read_only (否则 Plan 模式会误放行)。"""
        reg = _FakeRegistry()
        BrowserPlugin().activate(_Kernel(_Cfg({"tools.browser.enabled": True}), reg))
        by_name = {t.name: t for t in reg.registered}
        assert by_name["browser_task"].read_only is False
        assert by_name["browser_status"].read_only is True
        assert by_name["browser_close"].read_only is False
        assert all(t.group == "browser" for t in reg.registered)
        # browser_task 的参数 schema 必须是合法的 JSON Schema 对象
        params = by_name["browser_task"].parameters
        assert params["type"] == "object"
        assert "task" in params["properties"]
        assert params["required"] == ["task"]

    def test_plugin_in_builtin_list(self):
        from tuan_cli.tools import builtin_tool_plugins
        plugins = builtin_tool_plugins()
        assert any(isinstance(p, BrowserPlugin) for p in plugins)

    def test_telemetry_opted_out(self):
        """激活插件必须关闭 Browser Use 的匿名遥测。"""
        import os
        old = os.environ.pop("ANONYMIZED_TELEMETRY", None)
        try:
            reg = _FakeRegistry()
            BrowserPlugin().activate(_Kernel(_Cfg({"tools.browser.enabled": True}), reg))
            assert os.environ.get("ANONYMIZED_TELEMETRY") == "false"
        finally:
            if old is None:
                os.environ.pop("ANONYMIZED_TELEMETRY", None)
            else:
                os.environ["ANONYMIZED_TELEMETRY"] = old


# ------------------------------------------------------- 报告工具函数


class TestReportHelpers:
    def test_rel_inside_workspace(self):
        ws = str(pathlib_abs())
        inside = str(pathlib_abs() / "shot.png")
        assert _rel(inside, ws) == "shot.png"

    def test_rel_outside_workspace_falls_back(self):
        assert _rel("/tmp/x.png", "/nowhere") == "/tmp/x.png"

    def test_rel_empty_workspace(self):
        assert _rel("/tmp/x.png", "") == "/tmp/x.png"


def pathlib_abs():
    import pathlib
    return pathlib.Path("/w")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
