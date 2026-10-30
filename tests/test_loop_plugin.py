"""专项测试: core.loop_plugin —— Loop 插件。

覆盖:
  - LoopPlugin 元数据 (name/version/provides/requires)
  - activate (注册 3 内置 Loop + 按配置设默认 + provide)
  - switch_loop (切换 + unprovide + re-provide + emit)
"""

from __future__ import annotations

import pytest

from tuan_cli.core.kernel import Kernel
from tuan_cli.core.loop_plugin import LoopPlugin
from tuan_cli.core.loop_provider import (
    LoopRegistry,
    ReActLoop,
    PlannerExecuteLoop,
    DevLoopProvider,
)


def _mk_kernel(loop_provider="react"):
    kernel = Kernel()
    # config 服务: 提供 get 方法
    kernel.provide("config", _FakeConfig({"loop.provider": loop_provider}))
    return kernel


class _FakeConfig:
    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


class TestLoopPluginMeta:
    def test_metadata(self):
        assert LoopPlugin.name == "loop.provider"
        assert LoopPlugin.version == "0.1.0"
        assert "loop_registry" in LoopPlugin.provides
        assert "loop_provider" in LoopPlugin.provides
        assert "config" in LoopPlugin.requires


class TestActivate:
    def test_registers_three_builtin_loops(self):
        kernel = _mk_kernel()
        LoopPlugin().activate(kernel)
        registry = kernel.require("loop_registry")
        assert isinstance(registry, LoopRegistry)
        names = [i["name"] for i in registry.list_available()]
        assert names == ["react", "plan_execute", "devloop"]
        assert isinstance(registry.get_current(), ReActLoop)

    def test_default_react_current(self):
        kernel = _mk_kernel()
        LoopPlugin().activate(kernel)
        assert isinstance(kernel.require("loop_provider"), ReActLoop)

    def test_config_selects_plan_execute(self):
        kernel = _mk_kernel(loop_provider="plan_execute")
        LoopPlugin().activate(kernel)
        assert isinstance(kernel.require("loop_provider"), PlannerExecuteLoop)

    def test_config_selects_devloop(self):
        kernel = _mk_kernel(loop_provider="devloop")
        LoopPlugin().activate(kernel)
        assert isinstance(kernel.require("loop_provider"), DevLoopProvider)

    def test_invalid_config_falls_back_react(self):
        kernel = _mk_kernel(loop_provider="nope")
        LoopPlugin().activate(kernel)
        assert isinstance(kernel.require("loop_provider"), ReActLoop)

    def test_owner_is_plugin_name(self):
        kernel = _mk_kernel()
        LoopPlugin().activate(kernel)
        # owner 记录在 ServiceContainer 中
        assert kernel.services._service_owner.get("loop_registry") == "loop.provider"
        assert kernel.services._service_owner.get("loop_provider") == "loop.provider"


class TestSwitchLoop:
    def test_switch_to_valid(self):
        kernel = _mk_kernel()
        plugin = LoopPlugin()
        plugin.activate(kernel)
        events = []
        kernel.on("loop.switched", lambda p: events.append(p))
        plugin.switch_loop(kernel, "plan_execute")
        assert isinstance(kernel.require("loop_provider"), PlannerExecuteLoop)
        assert events == [{"name": "plan_execute"}]

    def test_switch_updates_registry_current(self):
        kernel = _mk_kernel()
        plugin = LoopPlugin()
        plugin.activate(kernel)
        plugin.switch_loop(kernel, "devloop")
        registry = kernel.require("loop_registry")
        assert registry.current_name == "devloop"

    def test_switch_to_unknown_raises(self):
        kernel = _mk_kernel()
        plugin = LoopPlugin()
        plugin.activate(kernel)
        with pytest.raises(ValueError):
            plugin.switch_loop(kernel, "nope")
        # 未切换: 快捷引用仍是 react
        assert isinstance(kernel.require("loop_provider"), ReActLoop)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-p", "no:cacheprovider"]))
