"""工具合并 (consolidation) 测试: 复合入口 / 隐藏别名 / 分发 / 权限旗标 / 轻量化效果。"""
import pytest

from tuan_cli.tools.base import Tool, ToolContext, ToolRegistry


def _reg():
    """构造一个带"家族"的小注册表。"""
    r = ToolRegistry()
    r.register(Tool(name="git_status", description="status", read_only=True,
                    parameters={"type": "object", "properties": {}},
                    handler=lambda ctx, **k: "STATUS"))
    r.register(Tool(name="git_diff", description="diff", read_only=True,
                    parameters={"type": "object", "properties": {"path": {"type": "string"}}},
                    handler=lambda ctx, path="", **k: f"DIFF:{path}"))
    r.register(Tool(name="git_log", description="log", read_only=True,
                    parameters={"type": "object", "properties": {"limit": {"type": "integer"}}},
                    handler=lambda ctx, limit=0, **k: f"LOG:{limit}"))
    return r


# ---------------------------------------------------------------- 1. 合并与隐藏
def test_merge_creates_composite_and_hides_members():
    r = _reg()
    comp = r.merge("git", "git 入口", {"status": "git_status", "diff": "git_diff", "log": "git_log"},
                   op_docs={"status": "状态", "diff": "改动", "log": "历史"})
    assert comp is not None and comp.name == "git"
    assert r.get("git_status").hidden and r.get("git_diff").hidden
    # 隐藏者不出现在 schema 列表
    names = {s["function"]["name"] for s in r.schemas()}
    assert "git" in names
    assert "git_status" not in names


def test_hidden_members_still_dispatchable():
    """向后兼容: 旧名降级为隐藏别名后仍可按名调用。"""
    r = _reg()
    r.merge("git", "git", {"status": "git_status"})
    t = r.get("git_status")
    assert t is not None and t.hidden
    assert t.handler(None) == "STATUS"


def test_hidden_members_excluded_from_tool_search():
    r = _reg()
    r.merge("git", "git", {"status": "git_status"})
    assert "git_status" not in {t.name for t in r.searchable_tools()}
    assert "git" in {t.name for t in r.searchable_tools()}


# ---------------------------------------------------------------- 2. 分发
def test_composite_dispatch_routes_to_member():
    r = _reg()
    comp = r.merge("git", "git", {"status": "git_status", "diff": "git_diff", "log": "git_log"})
    ctx = ToolContext(kernel=None, workspace=".")
    assert comp.handler(ctx, op="status") == "STATUS"
    assert comp.handler(ctx, op="diff", path="a.py") == "DIFF:a.py"
    assert comp.handler(ctx, op="log", limit=5) == "LOG:5"


def test_composite_dispatch_filters_unknown_args():
    """只把该 op 成员声明过的参数透传下去 (跨 op 参数不串味)。"""
    r = _reg()
    comp = r.merge("git", "git", {"status": "git_status", "log": "git_log"})
    ctx = ToolContext(kernel=None, workspace=".")
    # path 不属于 log 成员 → 被过滤, log 仍拿到 limit
    assert comp.handler(ctx, op="log", limit=3, path="ignored") == "LOG:3"


def test_composite_bad_op_returns_friendly_error():
    r = _reg()
    comp = r.merge("git", "git", {"status": "git_status"})
    out = comp.handler(None, op="nope")
    assert "未知 op" in out and "status" in out


def test_composite_schema_has_op_enum():
    r = _reg()
    comp = r.merge("git", "git", {"status": "git_status", "diff": "git_diff"})
    props = comp.parameters["properties"]
    assert props["op"]["enum"] == ["status", "diff"]
    assert comp.parameters["required"] == ["op"]


# ---------------------------------------------------------------- 3. 权限旗标取最严
def test_composite_inherits_strictest_flags():
    r = ToolRegistry()
    r.register(Tool(name="a", description="", read_only=True,
                    parameters={"type": "object", "properties": {}}, handler=lambda *a, **k: ""))
    r.register(Tool(name="b", description="", read_only=False, dangerous=True, yolo_confirm=True,
                    parameters={"type": "object", "properties": {}}, handler=lambda *a, **k: ""))
    comp = r.merge("ab", "ab", {"a": "a", "b": "b"})
    assert comp.dangerous is True       # 任一危险 → 危险
    assert comp.yolo_confirm is True
    assert comp.read_only is False      # 非全部只读 → 非只读


def test_composite_all_readonly_stays_readonly():
    r = _reg()
    comp = r.merge("git", "git", {"status": "git_status", "diff": "git_diff"})
    assert comp.read_only is True


def test_merge_missing_members_is_safe():
    r = _reg()
    assert r.merge("nope", "x", {"a": "does_not_exist"}) is None
    comp = r.merge("partial", "x", {"status": "git_status", "missing": "nope"})
    assert comp is not None
    assert comp.parameters["properties"]["op"]["enum"] == ["status"]


# ---------------------------------------------------------------- 4. 真实内核集成
@pytest.fixture(scope="module")
def kernel():
    from tuan_cli.app import build_kernel

    return build_kernel()


def test_real_kernel_has_all_composites(kernel):
    reg = kernel.require("tool_registry")
    expected = ["git", "todo", "skill", "memory", "ext_json", "ext_crypto", "ext_index",
                "ext_rules", "sandbox", "codedev", "image", "templates",
                "find", "code_review", "delete", "background"]
    for name in expected:
        t = reg.get(name)
        assert t is not None, f"缺复合工具 {name}"
        assert not t.hidden, f"{name} 不应是隐藏别名"


def test_real_kernel_visible_tool_count_reduced(kernel):
    """合并后可见工具数应显著低于合并前 (87)。"""
    reg = kernel.require("tool_registry")
    visible = [t for t in reg.tools if not getattr(t, "hidden", False)]
    assert len(visible) < 70, f"可见工具仍过多: {len(visible)}"
    # 且 standard 档位更小
    assert len(reg.schemas(exposure="standard")) < 45


def test_real_kernel_hidden_aliases_are_callable(kernel):
    reg = kernel.require("tool_registry")
    for alias in ("git_status", "todo_write", "skill_read", "memory_search"):
        t = reg.get(alias)
        assert t is not None and t.hidden, f"{alias} 应存在且为隐藏别名"


def test_real_kernel_dedupe_list_agents(kernel):
    """list_agents 与 agents_list 功能重合 → 前者降级为隐藏别名。"""
    reg = kernel.require("tool_registry")
    assert reg.get("list_agents").hidden is True
    assert reg.get("agents_list").hidden is False


def test_real_kernel_tool_search_excludes_hidden(kernel):
    reg = kernel.require("tool_registry")
    names = {t.name for t in reg.searchable_tools()}
    assert "git" in names
    assert "git_status" not in names
