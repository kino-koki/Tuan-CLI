"""ecosystem agent 工具测试 (tuan_cli/tools/ecosystem_tool.py)。

离线验证:
- 插件注册 / ``tools.ecosystem.enabled`` 开关 (stub kernel, 不依赖全量装配);
- op=scan: 空环境不崩溃且输出友好; tmp 注入的 ~/.claude/skills 能被盘点;
- op=status: 简要状态含 tuan 导出目录;
- op=import_assets: 把 tmp 注入的 Claude/Hermes 资产导入 tuan 主目录;
- op=export_assets: 把 tuan 技能/记忆导出到 tmp 目标目录, 文件真实落盘;
- 非法 op/scope/target → "[ecosystem] ..." 文本, 不抛原始异常;
- 经 ToolRegistry.dispatch_result 的完整分发链路可用。

镜像 tests/test_session_tools.py 的内核夹具 (build_kernel + Agent);
生态探测路径经 claude_home/hermes_home 参数注入 tmp 目录, 不触真实 home
(与 tests/test_ecosystem.py 的 EcosystemProbe.probe(...) 注入手法一致)。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.app import build_kernel
from tuan_cli.core.agent import Agent
from tuan_cli.ecosystem.detect import EcosystemProbe
from tuan_cli.tools.ecosystem_tool import EcosystemToolPlugin, _eco_handler


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture()
def eco_ctx(tmp_path, tuan_home, monkeypatch):
    """build_kernel + Agent 上下文, 额外激活 EcosystemToolPlugin (全离线)。"""
    # 离线化: 不探测真实 CLI (本机可能装了 claude/hermes, --version 子进程慢且不确定)
    monkeypatch.setattr(EcosystemProbe, "_which", staticmethod(lambda cmd: None))
    monkeypatch.setattr(EcosystemProbe, "_run_version", staticmethod(lambda cmd: ""))
    # 不读真实 ~/.hermes
    monkeypatch.delenv("HERMES_HOME", raising=False)

    # EcosystemToolPlugin 现已由 build_kernel() 直接注册激活 (真实接入),
    # 这里不再手动重复注册 —— 否则 kernel 抛 "插件重复注册: tools.ecosystem"。
    kernel = build_kernel()

    config = kernel.require("config")
    # 隔离: 关闭技能运行期对真实 ~/.claude / ~/.hermes 的发现 (影响 export 的 list_all)
    eco = config.data.setdefault("ecosystem", {})
    eco.setdefault("claude_code", {})["enabled"] = False
    eco.setdefault("hermes", {})["enabled"] = False

    agent = Agent(kernel=kernel, config=config, workspace=str(tmp_path),
                  confirm=lambda _p: True)
    return SimpleNamespace(kernel=kernel, agent=agent, ctx=agent.ctx,
                           tmp=tmp_path, home=tuan_home)


# ------------------------------------------------------------------ 注册

def test_tool_registered_with_schema(eco_ctx):
    tool = eco_ctx.kernel.require("tool_registry").get("ecosystem")
    assert tool is not None
    assert tool.group == "tools"
    props = tool.parameters["properties"]
    assert props["op"]["enum"] == ["scan", "status", "import_assets", "export_assets"]
    assert props["scope"]["enum"] == ["all", "skills", "agents", "memory"]
    assert props["target"]["enum"] == ["claude", "hermes", "all"]


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
    EcosystemToolPlugin().activate(k1)
    assert "ecosystem" in k1.registry.tools
    # 显式关闭 → 不注册
    k2 = _StubKernel(_FakeCfg({"tools": {"ecosystem": {"enabled": False}}}))
    EcosystemToolPlugin().activate(k2)
    assert "ecosystem" not in k2.registry.tools


# ------------------------------------------------------------------ scan

def test_scan_empty_home_friendly(eco_ctx):
    """空环境 scan: 不崩溃, 输出友好盘点, 且绝不创建/修改任何目录。"""
    cc = eco_ctx.tmp / "cc_none"
    hh = eco_ctx.tmp / "h_none"
    out = _eco_handler(eco_ctx.ctx, op="scan", claude_home=str(cc), hermes_home=str(hh))
    assert "【生态扫描】" in out
    assert "未找到 ~/.claude" in out and "未找到 ~/.hermes" in out
    assert "技能 0" in out and "agents 0" in out
    # 只读: 未创建任何目录
    assert not cc.exists() and not hh.exists()


def test_scan_detects_fake_claude_skills(eco_ctx):
    """tmp 注入的 ~/.claude/skills (一个 SKILL.md 目录包) → 被盘点出来。"""
    cc = eco_ctx.tmp / "cc"
    _write(cc / "skills" / "demo" / "SKILL.md",
           "---\nname: demo\ndescription: 演示技能\n---\n正文\n")
    out = _eco_handler(eco_ctx.ctx, op="scan", claude_home=str(cc),
                       hermes_home=str(eco_ctx.tmp / "h_none"))
    assert "技能 1" in out
    assert str(cc) in out


# ------------------------------------------------------------------ status

def test_status_shows_tuan_dirs(eco_ctx):
    out = _eco_handler(eco_ctx.ctx, op="status",
                       claude_home=str(eco_ctx.tmp / "cc_none"),
                       hermes_home=str(eco_ctx.tmp / "h_none"))
    assert "【生态状态】" in out
    assert str(eco_ctx.home / "skills") in out
    assert str(eco_ctx.home / "agents") in out
    assert str(eco_ctx.home / "memories") in out


# ------------------------------------------------------------------ import_assets

def test_import_assets_all_from_tmp_homes(eco_ctx):
    """Claude (技能+agent) 与 Hermes (技能+记忆+SOUL) 资产 → 全部导入 tuan 主目录。"""
    tmp = eco_ctx.tmp
    cc, hh = tmp / "cc", tmp / "hermes"
    _write(cc / "skills" / "cc-one.md",
           "---\nname: cc-one\ndescription: 来自 Claude\n---\n正文\n")
    _write(cc / "agents" / "reviewer.md",
           "---\nname: reviewer\ndescription: 审查\n---\n你是审查员\n")
    _write(hh / "skills" / "h-one" / "SKILL.md",
           "---\nname: h-one\ndescription: 来自 Hermes\n---\n正文\n")
    _write(hh / "memories" / "MEMORY.md", "事实一\n§\n事实二\n")
    _write(hh / "memories" / "USER.md", "昵称: 小王\n")
    _write(hh / "SOUL.md", "你是 Hermes\n")

    out = _eco_handler(eco_ctx.ctx, op="import_assets", scope="all", target="all",
                       claude_home=str(cc), hermes_home=str(hh))
    home = eco_ctx.home
    assert (home / "skills" / "cc-one.md").exists()
    assert (home / "skills" / "h-one.md").exists()
    assert (home / "agents" / "reviewer.md").exists()
    assert "事实一" in (home / "memories" / "MEMORY.md").read_text(encoding="utf-8")
    assert (home / "SOUL.md").exists()
    assert "失败" not in out
    assert "合计导入" in out


def test_import_assets_scope_skills_target_claude(eco_ctx):
    """scope=skills + target=claude: 只导入 Claude 技能, 不碰 agents/记忆。"""
    tmp = eco_ctx.tmp
    cc, hh = tmp / "cc", tmp / "hermes"
    _write(cc / "skills" / "cc-one.md",
           "---\nname: cc-one\ndescription: 来自 Claude\n---\n正文\n")
    _write(cc / "agents" / "reviewer.md",
           "---\nname: reviewer\ndescription: 审查\n---\n你是审查员\n")
    _write(hh / "memories" / "MEMORY.md", "事实一\n")

    out = _eco_handler(eco_ctx.ctx, op="import_assets", scope="skills", target="claude",
                       claude_home=str(cc), hermes_home=str(hh))
    assert "技能导入: 1 个" in out
    assert "Agent 导入" not in out and "记忆导入" not in out
    assert (eco_ctx.home / "skills" / "cc-one.md").exists()
    assert not (eco_ctx.home / "agents").exists()
    assert not (eco_ctx.home / "memories" / "MEMORY.md").exists()


# ------------------------------------------------------------------ export_assets

def test_export_skills_to_claude_workspace(eco_ctx):
    """tuan 用户技能 → 导出为可移植目录包到 <workspace>/.claude/skills/。"""
    _write(eco_ctx.home / "skills" / "my-skill.md",
           "---\nname: my-skill\ndescription: 导出测试\n---\n正文内容\n")
    out = _eco_handler(eco_ctx.ctx, op="export_assets", scope="skills", target="claude",
                       claude_home=str(eco_ctx.tmp / "cc_none"),
                       hermes_home=str(eco_ctx.tmp / "h_none"))
    target = eco_ctx.tmp / ".claude" / "skills" / "my-skill" / "SKILL.md"
    # 文件真实落盘 (可移植目录包形态); build_kernel 播种的内置技能也会一并导出,
    # 故只断言目标文件存在 + 导出行, 不锁死总数。
    assert target.exists()
    assert "技能导出 → claude" in out
    assert "合计导出" in out


def test_export_memory_to_hermes(eco_ctx):
    """tuan 记忆 → 导出为 Hermes 可读的 memories/MEMORY.md + USER.md。"""
    from tuan_cli.memory.store import MemoryStore

    store = MemoryStore(eco_ctx.home)
    store.append_memory("导出测试事实", section="测试")
    hh = eco_ctx.tmp / "hermes"
    # 与真实安装一致: Hermes 主目录已存在 (probe 只识别已存在的目录, 与 CLI 同口径)
    hh.mkdir(parents=True, exist_ok=True)
    out = _eco_handler(eco_ctx.ctx, op="export_assets", scope="memory", target="hermes",
                       claude_home=str(eco_ctx.tmp / "cc_none"), hermes_home=str(hh))
    mem = (hh / "memories" / "MEMORY.md").read_text(encoding="utf-8")
    assert "导出测试事实" in mem
    assert (hh / "memories" / "USER.md").exists()
    assert "记忆导出 → hermes" in out


# ------------------------------------------------------------------ 容错

def test_invalid_op_scope_target(eco_ctx):
    ctx = eco_ctx.ctx
    assert "未知 op" in _eco_handler(ctx, op="link")
    assert _eco_handler(ctx, op="bogus").startswith("[ecosystem]")
    assert "未知 scope" in _eco_handler(ctx, op="import_assets", scope="bogus")
    assert "未知 target" in _eco_handler(ctx, op="export_assets", target="bogus")


# ------------------------------------------------------------------ 分发链路

def test_dispatch_result_end_to_end(eco_ctx):
    """经 ToolRegistry.dispatch_result 的完整管线调用 ecosystem 工具。"""
    payload = json.dumps({
        "op": "status",
        "claude_home": str(eco_ctx.tmp / "cc_none"),
        "hermes_home": str(eco_ctx.tmp / "h_none"),
    })
    result = eco_ctx.kernel.require("tool_registry").dispatch_result(
        "ecosystem", payload, eco_ctx.ctx)
    assert result.status == "ok"
    assert "【生态状态】" in result.content
