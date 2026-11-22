"""external_dispatch agent 工具测试 (tuan_cli/tools/dispatch_tool.py)。

离线验证 (镜像 tests/test_tool_ecosystem.py 的内核夹具):
- 插件注册 / ``tools.dispatch.enabled`` 开关 (stub kernel, 不依赖全量装配);
- op=list: 空探测 (全部未安装) → 友好提示指向 `tuan dispatch` / `tuan agents`;
- op=route: dry-run 返回选中代理 + 命令预览, 且不执行 (断言 runner 未被调用);
- op=route dry_run=false: 注入的假 runner 恰被调用一次 (不 spawn 外部进程);
- 非法代理名 / 空 task / 未知 op → "[dispatch] ..." 文本, 不抛原始异常;
- op=status: 探测计数 + 默认路由 + 配置路径;
- 经 ToolRegistry.dispatch_result 的完整分发链路可用。

夹具说明: DispatchToolPlugin 尚未接入 build_kernel() (由父任务负责接线),
测试里手动 register + activate; 探测层 monkeypatch 类级 AgentAdapter.detect,
执行层 monkeypatch dispatch_tool._execute_task —— 全程零外部子进程。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tuan_cli.agents.base import AgentAdapter, AgentInfo
from tuan_cli.app import build_kernel
from tuan_cli.core.agent import Agent
from tuan_cli.tools import dispatch_tool
from tuan_cli.tools.dispatch_tool import DispatchToolPlugin, _dispatch_handler


async def _fake_detect_healthy(self):
    """全部代理探测为「已验证安装」(score=100), 不触 PATH / --version 子进程。"""
    return AgentInfo(id=self.id, name=self.display_name, path="C:/fake-bin",
                     healthy=True, version="1.0.0-fake", score=100)


async def _fake_detect_none(self):
    """全部代理探测为「未安装」。"""
    return AgentInfo(id=self.id, name=self.display_name, healthy=False,
                     reason="not found in PATH", score=0)


@pytest.fixture()
def dispatch_ctx(tmp_path, tuan_home, monkeypatch):
    """build_kernel + Agent 上下文, 手动激活 DispatchToolPlugin (全离线)。"""
    # 默认离线化: 本机探测全部返回未安装 (不 spawn --version 子进程)
    monkeypatch.setattr(AgentAdapter, "detect", _fake_detect_none)

    # DispatchToolPlugin 现已由 build_kernel() 直接注册激活 (真实接入, 插件名
    # tools.external_dispatch); 这里不再手动重复注册, 否则 kernel 抛
    # "插件重复注册: tools.external_dispatch"。
    kernel = build_kernel()

    config = kernel.require("config")
    agent = Agent(kernel=kernel, config=config, workspace=str(tmp_path),
                  confirm=lambda _p: True)
    return SimpleNamespace(kernel=kernel, agent=agent, ctx=agent.ctx,
                           tmp=tmp_path, home=tuan_home)


# ------------------------------------------------------------------ 注册

def test_tool_registered_with_schema(dispatch_ctx):
    tool = dispatch_ctx.kernel.require("tool_registry").get("external_dispatch")
    assert tool is not None
    assert tool.group == "tools"
    assert tool.handler is _dispatch_handler
    props = tool.parameters["properties"]
    assert props["op"]["enum"] == ["list", "route", "status"]
    assert props["mode"]["enum"] == ["chat", "collaboration", "gantong",
                                     "lingma", "boundless"]
    assert "task" in props and "agent" in props and "dry_run" in props
    assert tool.parameters["required"] == []


class _FakeCfg:
    """最小 Config 鸭子类型: 点号路径 get (开关测试用)。"""

    def __init__(self, data):
        self.data = data

    def get(self, key, default=None):
        cur = self.data
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur


class _StubRegistry:
    def __init__(self):
        self.tools = {}

    def register(self, tool):
        self.tools[tool.name] = tool


class _StubKernel:
    def __init__(self, config):
        self._config = config
        self.registry = _StubRegistry()

    def get(self, name):
        return self._config if name == "config" else None

    def require(self, name):
        return self.registry


def test_plugin_enable_disable_toggle():
    # 默认开启 (config 无该键 → default True)
    k1 = _StubKernel(_FakeCfg({}))
    DispatchToolPlugin().activate(k1)
    assert "external_dispatch" in k1.registry.tools
    # 显式关闭 → 不注册
    k2 = _StubKernel(_FakeCfg({"tools": {"dispatch": {"enabled": False}}}))
    DispatchToolPlugin().activate(k2)
    assert "external_dispatch" not in k2.registry.tools


# ------------------------------------------------------------------ op=list

def test_list_empty_discovery_friendly(dispatch_ctx):
    """空探测 (全部未安装): 不崩溃, 逐行标注未安装并给出友好指引。"""
    out = _dispatch_handler(dispatch_ctx.ctx, op="list")
    assert "【外部代理清单】" in out
    assert "可用 0 家" in out
    assert "未安装" in out
    # 友好提示: 指向 tuan dispatch 文档 / tuan agents 列表
    assert "未发现任何受支持的外部代理" in out
    assert "tuan dispatch status" in out
    assert "tuan agents" in out


def test_list_with_installed_agents(dispatch_ctx, monkeypatch):
    """有代理安装: 逐行列出, 含名称/命令/版本与「已验证」徽标。"""
    monkeypatch.setattr(AgentAdapter, "detect", _fake_detect_healthy)
    out = _dispatch_handler(dispatch_ctx.ctx, op="list")
    assert "【外部代理清单】共 9 家, 可用 9 家" in out
    assert "已验证" in out
    assert "Claude Code (claude-code)" in out
    assert "claude/claude-code" in out  # 候选命令
    assert "1.0.0-fake" in out          # 版本


def test_list_is_default_op(dispatch_ctx):
    """op 缺省 → 等价 list。"""
    out = _dispatch_handler(dispatch_ctx.ctx)
    assert "【外部代理清单】" in out


# ------------------------------------------------------------------ op=route (dry-run)

def test_route_dry_run_previews_without_executing(dispatch_ctx, monkeypatch):
    """dry-run: 返回选中代理 + 命令预览, 且绝不调用执行层。"""
    monkeypatch.setattr(AgentAdapter, "detect", _fake_detect_healthy)
    calls = []

    async def _no_exec(task, adapter):
        calls.append((task, adapter))
        return 0, "不应被调用", "ok"

    monkeypatch.setattr(dispatch_tool, "_execute_task", _no_exec)
    out = _dispatch_handler(dispatch_ctx.ctx, op="route",
                            task="修复登录 bug", dry_run=True)
    assert calls == []                       # runner 未被调用 (未执行)
    assert "dry-run, 未执行" in out
    # chat 模式权重最高者 (claude-code, 权重 5) 被自动选中
    assert "claude-code" in out
    assert "claude -p" in out                # 命令预览
    assert "修复登录 bug" in out             # 任务回显
    assert "dry_run=false" in out            # 执行提示


def test_route_auto_and_explicit_agent_same_preview(dispatch_ctx, monkeypatch):
    """显式指定 agent 与 auto 路由命中同一代理时, 预览一致。"""
    monkeypatch.setattr(AgentAdapter, "detect", _fake_detect_healthy)
    auto = _dispatch_handler(dispatch_ctx.ctx, op="route", task="写冒泡排序")
    explicit = _dispatch_handler(dispatch_ctx.ctx, op="route",
                                 task="写冒泡排序", agent="claude-code")
    assert "claude-code" in auto and "claude-code" in explicit
    assert "claude -p" in auto and "claude -p" in explicit


# ------------------------------------------------------------------ op=route (真实执行)

def test_route_real_run_calls_fake_runner_once(dispatch_ctx, monkeypatch):
    """dry_run=false: 走注入的假 runner 恰一次, 不 spawn 真实子进程。"""
    monkeypatch.setattr(AgentAdapter, "detect", _fake_detect_healthy)
    calls = []

    async def fake_exec(task, adapter):
        calls.append((task, adapter))
        return 0, "冒泡排序已写入 sort.py", "ok"

    monkeypatch.setattr(dispatch_tool, "_execute_task", fake_exec)
    out = _dispatch_handler(dispatch_ctx.ctx, op="route", task="写个冒泡排序",
                            agent="claude-code", dry_run=False)
    assert len(calls) == 1                   # 假 runner 恰被调用一次
    task, adapter = calls[0]
    assert adapter.id == "claude-code"
    assert task.prompt == "写个冒泡排序"
    assert "【外部派活·完成】" in out
    assert "claude-code" in out
    assert "状态: ok (exit=0)" in out
    assert "冒泡排序已写入 sort.py" in out


def test_route_real_run_reports_failure(dispatch_ctx, monkeypatch):
    """runner 返回失败状态: 输出带警告行, 不抛异常。"""
    monkeypatch.setattr(AgentAdapter, "detect", _fake_detect_healthy)

    async def fake_exec(task, adapter):
        return 1, "boom", "error"

    monkeypatch.setattr(dispatch_tool, "_execute_task", fake_exec)
    out = _dispatch_handler(dispatch_ctx.ctx, op="route", task="做点事",
                            agent="codex", dry_run=False)
    assert "状态: error (exit=1)" in out
    assert "未正常结束" in out
    assert "boom" in out


# ------------------------------------------------------------------ 容错

def test_route_invalid_agent_rejected(dispatch_ctx, monkeypatch):
    """非法代理名: "[dispatch] 未知代理 ..." 文本, 不抛原始异常。"""
    monkeypatch.setattr(AgentAdapter, "detect", _fake_detect_healthy)
    out = _dispatch_handler(dispatch_ctx.ctx, op="route", task="x",
                            agent="no-such-agent")
    assert out.startswith("[dispatch]")
    assert "未知代理" in out
    assert "no-such-agent" in out
    assert "claude-code" in out              # 可用列表提示


def test_route_requires_task(dispatch_ctx):
    """task 缺失/空白 → 拒绝且不执行。"""
    out = _dispatch_handler(dispatch_ctx.ctx, op="route")
    assert out.startswith("[dispatch]")
    assert "task" in out
    out2 = _dispatch_handler(dispatch_ctx.ctx, op="route", task="   ")
    assert out2.startswith("[dispatch]") and "task" in out2


def test_route_unknown_mode_rejected(dispatch_ctx):
    out = _dispatch_handler(dispatch_ctx.ctx, op="route", task="x", mode="dream")
    assert out.startswith("[dispatch]") and "未知 mode" in out


def test_invalid_op(dispatch_ctx):
    out = _dispatch_handler(dispatch_ctx.ctx, op="bogus")
    assert out.startswith("[dispatch]")
    assert "未知 op" in out
    assert "list/route/status" in out


# ------------------------------------------------------------------ op=status

def test_status_summary(dispatch_ctx, monkeypatch):
    """status: 探测计数 + 默认路由 + 配置路径 + 超时。"""
    monkeypatch.setattr(AgentAdapter, "detect", _fake_detect_healthy)
    out = _dispatch_handler(dispatch_ctx.ctx, op="status")
    assert "【外部派活状态】" in out
    assert "探测代理: 9 家 (可用 9, 版本校验通过 9)" in out
    assert "默认路由 (mode=chat): claude-code" in out   # chat 权重最高
    assert str(dispatch_ctx.home) in out                # 配置目录
    assert "config.yaml" in out                         # 配置文件
    assert "600" in out                                 # 默认超时


def test_status_empty_discovery(dispatch_ctx):
    """status: 空探测时附友好指引, 不崩溃。"""
    out = _dispatch_handler(dispatch_ctx.ctx, op="status")
    assert "探测代理: 9 家 (可用 0" in out
    assert "无可用代理" in out
    assert "tuan dispatch status" in out


# ------------------------------------------------------------------ 分发链路

def test_dispatch_result_end_to_end(dispatch_ctx):
    """经 ToolRegistry.dispatch_result 的完整管线调用 external_dispatch。"""
    payload = json.dumps({"op": "list"})
    result = dispatch_ctx.kernel.require("tool_registry").dispatch_result(
        "external_dispatch", payload, dispatch_ctx.ctx)
    assert result.status == "ok"
    assert "【外部代理清单】" in result.content


def test_timeout_config_override(dispatch_ctx):
    """tools.dispatch.timeout_sec 配置生效于 status 展示。"""
    cfg = dispatch_ctx.kernel.require("config")
    cfg.data.setdefault("tools", {})["dispatch"] = {"timeout_sec": 42}
    out = _dispatch_handler(dispatch_ctx.ctx, op="status")
    assert "执行超时: 42s" in out
