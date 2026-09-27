"""生态互操作层 (qingxiaotuan.ecosystem) 测试。

覆盖: 探测/盘点、技能双向桥接、Hermes 记忆/人格桥接、Claude Code Agent 桥接、
MCP 配置互导、MCP Server 协议 (initialize / tools/list / tools/call / 错误处理)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qingxiaotuan.ecosystem.agents_bridge import export_to_claude, import_claude_agents
from qingxiaotuan.ecosystem.detect import EcosystemProbe
from qingxiaotuan.ecosystem.mcp_import import (
    export_to_claude_mcp_json,
    export_to_hermes_config,
    import_mcp_servers,
    parse_claude_mcp_json,
    parse_hermes_config,
)
from qingxiaotuan.ecosystem.mcp_server import McpToolServer
from qingxiaotuan.ecosystem.memory_bridge import (
    export_to_hermes,
    import_hermes_memory,
    parse_hermes_entries,
)
from qingxiaotuan.ecosystem.skills_bridge import (
    export_skills,
    find_skill_files,
    import_skills,
)
from qingxiaotuan.memory.store import MemoryStore
from qingxiaotuan.skills.manager import SkillManager


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- detect

def test_probe_finds_injected_paths(tmp_path: Path):
    cc_home = tmp_path / "cc"
    hermes_home = tmp_path / "hermes"
    ws = tmp_path / "ws"
    _write(cc_home / "skills" / "cc-skill.md",
           "---\nname: CCSkill\ndescription: cc\n---\nbody\n")
    _write(hermes_home / "skills" / "h-skill" / "SKILL.md",
           "---\nname: HSkill\ndescription: h\n---\nbody\n")
    _write(hermes_home / "memories" / "MEMORY.md", "事实条目\n§\n另一条\n")
    _write(hermes_home / "SOUL.md", "你是…")
    _write(ws / ".claude" / "agents" / "reviewer.md",
           "---\nname: reviewer\ndescription: 审查\n---\n提示\n")

    probe = EcosystemProbe.probe(str(ws), claude_home=str(cc_home), hermes_home=str(hermes_home))
    assert probe.claude_home == cc_home
    assert probe.hermes_home == hermes_home
    summary = probe.summarize()
    assert summary["claude_code"].skills == 1
    assert summary["claude_code"].agents == 1
    assert summary["hermes"].skills == 1
    assert summary["hermes"].memories == 1
    assert summary["hermes"].soul is True


def test_probe_without_paths_is_empty(tmp_path: Path):
    probe = EcosystemProbe.probe(str(tmp_path / "none"), claude_home=str(tmp_path / "x"), hermes_home=str(tmp_path / "y"))
    assert probe.claude_home is None
    assert probe.hermes_home is None
    assert probe.summarize()["claude_code"].skills == 0


def test_probe_ignores_hidden_staging_skill_dirs(tmp_path: Path):
    """Claude 官方安装的 .xxx-stage-* 暂存目录不应被计为用户技能 (真实机 bug 回归)。"""
    cc_home = tmp_path / "cc"
    _write(cc_home / "skills" / "tabbit" / "SKILL.md",
           "---\nname: Tabbit\ndescription: t\n---\nb\n")
    _write(cc_home / "skills" / ".tabbit-stage-BFD2E9FE83F7C6E96" / "SKILL.md",
           "---\nname: TabbitStage\ndescription: 暂存\n---\nb\n")
    probe = EcosystemProbe.probe(None, claude_home=str(cc_home), hermes_home=str(tmp_path / "h"))
    assert probe.summarize()["claude_code"].skills == 1


def test_probe_mcp_servers_counted_per_ecosystem(tmp_path: Path):
    """MCP servers 应分生态统计: claude 只计项目 .mcp.json, hermes 只计 config.yaml (真实机 bug 回归)。"""
    ws = tmp_path / "ws"
    hermes_home = tmp_path / "hermes"
    _write(ws / ".mcp.json", '{"mcpServers": {"qxt": {"command": "qxt", "args": []}}}')
    _write(hermes_home / "config.yaml",
           "mcp:\n  servers:\n    zhipu:\n      command: \"zhipu-mcp\"\n      args: []\n")
    probe = EcosystemProbe.probe(str(ws), claude_home=str(tmp_path / "cc"), hermes_home=str(hermes_home))
    summary = probe.summarize()
    assert summary["claude_code"].mcp_servers == 1
    assert summary["hermes"].mcp_servers == 1


def test_find_skill_files_both_forms(tmp_path: Path):
    d = tmp_path / "skills"
    _write(d / "single.md", "---\nname: Single\ndescription: s\n---\nb\n")
    _write(d / "pkg" / "SKILL.md", "---\nname: Pkg\ndescription: p\n---\nb\n")
    _write(d / "SKILL.md", "ignored 根级不属于技能文件\n")
    found = find_skill_files([d])
    assert len(found) == 2


# ---------------------------------------------------------------- skills bridge

def test_import_skills_from_claude_and_hermes(tmp_path: Path):
    home = tmp_path / "qxt"
    cc_home = tmp_path / "cc"
    hermes_home = tmp_path / "hermes"
    _write(cc_home / "skills" / "cc-one.md",
           "---\nname: CC-One\ndescription: from claude\n---\nbody\n")
    _write(hermes_home / "skills" / "h-one" / "SKILL.md",
           "---\nname: H-One\ndescription: from hermes\n---\nbody\n")
    probe = EcosystemProbe.probe(None, claude_home=str(cc_home), hermes_home=str(hermes_home))
    mgr = SkillManager(home)
    result = import_skills(mgr, probe, sources=("claude_code", "hermes"))
    assert "cc-one" in [s.slug for s in mgr.list_all()]
    assert "h-one" in [s.slug for s in mgr.list_all()]
    assert len(result.imported) == 2


def test_export_skills_portable_package(tmp_path: Path):
    class _NoEcoConfig:
        """隔离测试: 关闭生态发现, 只导出 tmp home 里的用户技能。"""

        def get(self, key, default=None):
            if key == "ecosystem.claude_code.enabled" or key == "ecosystem.hermes.enabled":
                return False
            return default

    home = tmp_path / "qxt"
    mgr = SkillManager(home, config=_NoEcoConfig())
    mgr.save("Portable Skill", "可移植技能", "正文")
    dest = tmp_path / "out"
    result = export_skills(mgr, dest)
    assert result.imported == ["portable-skill"]
    skill_md = dest / "portable-skill" / "SKILL.md"
    assert skill_md.exists()
    text = skill_md.read_text(encoding="utf-8")
    assert "name: Portable Skill" in text
    assert "正文" in text
    # qxt 专有计数字段不应污染可移植 frontmatter
    assert "use_count" not in text


# ---------------------------------------------------------------- memory bridge

def test_parse_hermes_entries_splits_sections():
    text = "条目一\n\n§\n条目二\n\n§\n\n条目三"
    entries = parse_hermes_entries(text)
    assert len(entries) == 3
    assert entries[0].startswith("条目一")


def test_import_hermes_memory_dedup_and_soul(tmp_path: Path):
    home = tmp_path / "qxt"
    hermes_home = tmp_path / "hermes"
    _write(hermes_home / "memories" / "MEMORY.md", "用户偏好简洁回答\n§\n项目约定: 用 pytest\n")
    _write(hermes_home / "memories" / "USER.md", "昵称: 小王\n")
    _write(hermes_home / "SOUL.md", "你是 Hermes\n")
    store = MemoryStore(home)
    r1 = import_hermes_memory(store, [hermes_home / "memories"],
                              hermes_home=hermes_home, qxt_home=home)
    assert len(r1.memory_added) == 2
    assert len(r1.user_added) == 1
    assert r1.soul_copied is True
    assert (home / "SOUL.md").exists()
    # 二次导入: 全部去重
    r2 = import_hermes_memory(store, [hermes_home / "memories"],
                              hermes_home=hermes_home, qxt_home=home)
    assert len(r2.memory_added) == 0
    assert len(r2.memory_skipped) == 2
    # SOUL 已存在且未 force → 不覆盖
    assert r2.soul_error


def test_export_to_hermes_writes_files_and_flags_budget(tmp_path: Path):
    home = tmp_path / "qxt"
    hermes_home = tmp_path / "hermes"
    store = MemoryStore(home)
    store.append_memory("一条短期事实", section="事实")
    result = export_to_hermes(store, hermes_home)
    assert result.target
    mem = (hermes_home / "memories" / "MEMORY.md").read_text(encoding="utf-8")
    assert "一条短期事实" in mem
    assert (hermes_home / "memories" / "USER.md").exists()
    assert result.memory_over is False


# ---------------------------------------------------------------- agents bridge

def test_agents_bridge_roundtrip(tmp_path: Path):
    cc_dir = tmp_path / "cc" / "agents"
    qxt_dir = tmp_path / "qxt" / "agents"
    _write(cc_dir / "reviewer.md",
           "---\nname: reviewer\ndescription: 代码审查员\n---\n你是审查员\n")
    result = import_claude_agents([cc_dir], qxt_dir)
    assert result.imported == ["reviewer"]
    assert (qxt_dir / "reviewer.md").exists()
    # 导出回项目 .claude/agents
    out = tmp_path / "ws" / ".claude" / "agents"
    exported = export_to_claude(qxt_dir, out)
    assert exported.exported == ["reviewer"]
    assert (out / "reviewer.md").exists()
    # 无 frontmatter 的文件按 filename 兜底为名称 (与 agents_registry 运行期行为一致)
    _write(cc_dir / "broken.md", "没有 frontmatter 的正文文件\n")
    r2 = import_claude_agents([cc_dir], qxt_dir)
    assert "broken" in r2.imported
    assert "reviewer" in r2.skipped  # 同名已存在且未 overwrite → 跳过


# ---------------------------------------------------------------- mcp import

def test_parse_claude_mcp_json(tmp_path: Path):
    f = tmp_path / ".mcp.json"
    f.write_text(json.dumps({"mcpServers": {"filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"], "env": {"K": "V"}}}}), encoding="utf-8")
    servers = parse_claude_mcp_json(f)
    assert len(servers) == 1
    assert servers[0]["name"] == "filesystem"
    assert servers[0]["command"] == "npx"


def test_parse_hermes_config(tmp_path: Path):
    f = tmp_path / "config.yaml"
    f.write_text("mcp:\n  servers:\n    brave:\n      command: npx\n      args: [\"@mcp/brave\"]\n", encoding="utf-8")
    servers = parse_hermes_config(f)
    assert len(servers) == 1
    assert servers[0]["name"] == "brave"


class _FakeConfig:
    """最小 Config 鸭子类型: get/set 点号路径 (测试用)。"""

    def __init__(self):
        self.data = {}

    def get(self, key, default=None):
        cur = self.data
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, key, value):
        parts = key.split(".")
        cur = self.data
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value


def test_import_mcp_servers_merge_and_skip():
    cfg = _FakeConfig()
    cfg.set("mcp.servers", [{"name": "existing", "command": "python", "args": []}])
    servers = [{"name": "new", "command": "qxt", "args": ["ecosystem", "serve"]},
               {"name": "existing", "command": "python", "args": []},
               {"name": "", "command": ""}]
    result = import_mcp_servers(cfg, servers)
    assert result.imported == ["new"]
    assert result.skipped == ["existing", "<unnamed>"]
    names = [s["name"] for s in cfg.get("mcp.servers", [])]
    assert names == ["existing", "new"]
    # overwrite 时替换同名
    r2 = import_mcp_servers(cfg, [{"name": "existing", "command": "python3", "args": []}], overwrite=True)
    assert r2.imported == ["existing"]


def test_import_mcp_servers_with_real_config(tmp_path: Path, monkeypatch):
    """真实 Config 走 set_user 写用户层配置 (真实机 bug 回归: Config 无 set 属性)。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "qxt_home"))
    from qingxiaotuan.config import Config

    cfg = Config(profile="e2e", bare=False)
    result = import_mcp_servers(cfg, [{"name": "zhipu", "command": "zhipu-mcp", "args": []}])
    assert result.imported == ["zhipu"]
    assert not result.errors
    stored = cfg.get("mcp.servers", [])
    assert stored[0]["name"] == "zhipu"
    # 落盘可回读
    cfg2 = Config(profile="e2e", bare=False)
    assert cfg2.get("mcp.servers", [])[0]["name"] == "zhipu"


def test_export_redacts_secrets(tmp_path: Path):
    out = tmp_path / ".mcp.json"
    result = export_to_claude_mcp_json(
        [{"name": "db", "command": "python", "args": ["srv.py"], "env": {"API_KEY": "sk-123", "PORT": "8080"}}],
        out, include_env=True,
    )
    assert result.exported_path
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["mcpServers"]["db"]["env"]["API_KEY"] == "<redacted: 请手动填写>"
    assert data["mcpServers"]["db"]["env"]["PORT"] == "8080"


def test_export_to_hermes_config_merges(tmp_path: Path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("mode: default\nmcp:\n  servers:\n    old:\n      command: x\n", encoding="utf-8")
    result = export_to_hermes_config([{"name": "qxt", "command": "qxt", "args": ["ecosystem", "serve"]}], cfg_file)
    assert result.exported_path
    text = cfg_file.read_text(encoding="utf-8")
    assert "qxt" in text and "old" in text


# ---------------------------------------------------------------- mcp server

def _rpc(method: str, params, req_id=None):
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    if req_id is not None:
        msg["id"] = req_id
    return json.dumps(msg, ensure_ascii=False)


def test_mcp_server_handshake_and_tools(tmp_path: Path):
    srv = McpToolServer(tmp_path)
    init = json.loads(srv.handle_line(_rpc("initialize", {"protocolVersion": "2024-11-05"}, 1)))
    assert init["result"]["serverInfo"]["name"] == "qingxiaotuan-ecosystem"
    # 通知无响应
    assert srv.handle_line(_rpc("notifications/initialized", None)) is None
    listed = json.loads(srv.handle_line(_rpc("tools/list", {}, 2)))
    names = [t["name"] for t in listed["result"]["tools"]]
    assert "qxt_status" in names and "memory_write" in names and "skill_list" in names
    assert "run_shell" not in names  # 默认 fail-closed 不暴露危险工具
    # 调 qxt_status
    call = json.loads(srv.handle_line(_rpc("tools/call", {"name": "qxt_status", "arguments": {}}, 3)))
    assert not call["result"]["isError"]
    assert "qingxiaotuan-ecosystem" in call["result"]["content"][0]["text"]
    # ping
    pong = json.loads(srv.handle_line(_rpc("ping", {}, 9)))
    assert pong["result"] == {}
    # 未知工具 → 协议错误
    err = json.loads(srv.handle_line(_rpc("tools/call", {"name": "nope", "arguments": {}}, 4)))
    assert err["error"]["code"] == -32602
    # 坏 JSON → Parse error
    perr = json.loads(srv.handle_line("{not json}"))
    assert perr["error"]["code"] == -32700


def test_mcp_server_memory_and_skill_tools(tmp_path: Path):
    home = tmp_path / "qxt"
    srv = McpToolServer(home)
    # memory_write → memory_search 回读
    w = json.loads(srv.handle_line(_rpc("tools/call", {"name": "memory_write",
                                                      "arguments": {"fact": "生态桥接测试事实", "section": "test"}}, 1)))
    assert not w["result"]["isError"]
    s = json.loads(srv.handle_line(_rpc("tools/call", {"name": "memory_search",
                                                      "arguments": {"query": "生态桥接"}}, 2)))
    assert "生态桥接测试事实" in s["result"]["content"][0]["text"]
    # skill_list 不报错
    sl = json.loads(srv.handle_line(_rpc("tools/call", {"name": "skill_list", "arguments": {}}, 3)))
    assert "isError" in sl["result"]


def test_mcp_server_dangerous_gated(tmp_path: Path):
    srv = McpToolServer(tmp_path, allow_dangerous_tools=True)
    names = [t["name"] for t in srv.tools()]
    assert "run_shell" in names
    # 硬红线命令被 fail-closed 拒绝
    call = json.loads(srv.handle_line(_rpc("tools/call", {"name": "run_shell",
                                                         "arguments": {"command": "shutdown -s -t 0"}}, 1)))
    assert call["result"]["isError"]
    assert "红线" in call["result"]["content"][0]["text"]
