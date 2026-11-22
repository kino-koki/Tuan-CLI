"""memory 工具进阶操作测试 (delete / stats / recall / recent)。

镜像 test_session_tools.py 的 build_kernel + Agent + tuan_home 夹具。
全程离线: 只走真实 MemoryStore (本机 SQLite/FTS5), 不触网;
记忆条目一律通过真实 store API (add_auto_memory) 播种。
"""

from tuan_cli.app import build_kernel
from tuan_cli.core.agent import Agent


def _make_ctx(tmp_path):
    kernel = build_kernel()
    config = kernel.require("config")
    agent = Agent(kernel=kernel, config=config, workspace=str(tmp_path),
                  confirm=lambda _p: True)
    return kernel, agent


def _seed(store, text, kind="project", tags=None):
    """通过真实 store API 播种一条 Auto Memory, 返回条目 id。"""
    rid = store.add_auto_memory(text, kind=kind, tags=tags, source="manual")
    assert rid is not None, f"seed 失败: {text}"
    return rid


# ------------------------------------------------------------------ 注册

def test_memory_advanced_tools_registered(tuan_home):
    kernel = build_kernel()
    reg = kernel.require("tool_registry")
    names = {t.name for t in reg.tools}
    for n in ("memory_delete", "memory_stats", "memory_recall", "memory_recent"):
        assert n in names, f"缺少工具 {n}"
    # 分组不变; delete 是危险写操作, 其余三个只读
    assert reg.get("memory_delete").group == "memory"
    assert reg.get("memory_delete").dangerous is True
    for n in ("memory_stats", "memory_recall", "memory_recent"):
        assert reg.get(n).group == "memory"
        assert reg.get(n).read_only is True


# ------------------------------------------------------------------ delete

def test_memory_delete_by_id(tmp_path, tuan_home):
    kernel, agent = _make_ctx(tmp_path)
    store = kernel.require("memory_store")
    rid = _seed(store, "部署流程: 先 build 再 push 最后 restart")
    assert len(store.list_by_kind(limit=100)) == 1
    reg = kernel.require("tool_registry")
    out = reg.get("memory_delete").handler(agent.ctx, id=str(rid))
    assert "已删除" in out and f"id={rid}" in out
    assert store.list_by_kind(limit=100) == []
    # 再删一次 → 友好报错
    out2 = reg.get("memory_delete").handler(agent.ctx, id=str(rid))
    assert out2.startswith("[memory]") and str(rid) in out2


def test_memory_delete_by_tag_then_prefix(tmp_path, tuan_home):
    kernel, agent = _make_ctx(tmp_path)
    store = kernel.require("memory_store")
    _seed(store, "API 网关地址已切换到 v2", kind="project", tags=["infra"])
    _seed(store, "数据库备份流程: mysqldump 全量导出", kind="reference", tags=["ops"])
    reg = kernel.require("tool_registry")
    # 按标签删除
    out = reg.get("memory_delete").handler(agent.ctx, tag="infra")
    assert "1/1" in out and "infra" in out
    remaining = [e["content"] for e in store.list_by_kind(limit=100)]
    assert remaining == ["数据库备份流程: mysqldump 全量导出"]
    # 按内容前缀删除
    out2 = reg.get("memory_delete").handler(agent.ctx, prefix="数据库备份")
    assert "1/1" in out2 and "前缀" in out2
    assert store.list_by_kind(limit=100) == []
    # 前缀无命中 → 友好报错
    out3 = reg.get("memory_delete").handler(agent.ctx, prefix="不存在的前缀")
    assert out3.startswith("[memory]") and "没有找到" in out3


def test_memory_delete_requires_explicit_target(tmp_path, tuan_home):
    """缺失目标 → 友好报错; "无差别全删"不可达, 原条目保留。"""
    kernel, agent = _make_ctx(tmp_path)
    store = kernel.require("memory_store")
    _seed(store, "需要被保留的记忆条目")
    reg = kernel.require("tool_registry")
    out = reg.get("memory_delete").handler(agent.ctx)
    assert out.startswith("[memory]") and "显式" in out
    # 空串/空白前缀等价于全删 → 同样拒绝
    out2 = reg.get("memory_delete").handler(agent.ctx, prefix="   ")
    assert out2.startswith("[memory]")
    # 非数字 id → 友好报错
    out3 = reg.get("memory_delete").handler(agent.ctx, id="abc")
    assert out3.startswith("[memory]") and "abc" in out3
    # 原条目未被误删
    assert len(store.list_by_kind(limit=100)) == 1


# ------------------------------------------------------------------ stats

def test_memory_stats_shows_counts_and_path(tmp_path, tuan_home):
    kernel, agent = _make_ctx(tmp_path)
    store = kernel.require("memory_store")
    _seed(store, "用户偏好中文回复", kind="user", tags=["style"])
    _seed(store, "本项目用 pytest 跑测试", kind="project")
    reg = kernel.require("tool_registry")
    out = reg.get("memory_stats").handler(agent.ctx)
    assert "记忆库路径" in out and str(store.dir) in out
    assert "分类分布" in out and "user=1" in out and "project=1" in out
    assert "标签分布" in out and "style×1" in out
    assert "FTS5 索引条目" in out and "标签索引条目" in out


# ------------------------------------------------------------------ recall

def test_memory_recall_returns_matches(tmp_path, tuan_home):
    kernel, agent = _make_ctx(tmp_path)
    store = kernel.require("memory_store")
    reg = kernel.require("tool_registry")
    # 空库: 无相关记忆 → 明确提示 (recall_context 对空库返回空串)
    out_empty = reg.get("memory_recall").handler(agent.ctx, task="如何部署服务?")
    assert "无相关长期记忆" in out_empty
    # 播种后: 命中 (recall_context 会合并全文命中 + 近期条目, 按 kind 优先级排序)
    _seed(store, "部署流程: 先 build 再 push 最后 restart", kind="project")
    out = reg.get("memory_recall").handler(agent.ctx, task="如何部署服务?")
    assert "召回" in out and "部署流程" in out
    # 空任务 → 友好报错
    out2 = reg.get("memory_recall").handler(agent.ctx, task="  ")
    assert out2.startswith("[memory]") and "任务描述" in out2


# ------------------------------------------------------------------ recent

def test_memory_recent_returns_latest(tmp_path, tuan_home):
    kernel, agent = _make_ctx(tmp_path)
    store = kernel.require("memory_store")
    _seed(store, "API 网关地址已切换到 v2", kind="project")
    reg = kernel.require("tool_registry")
    out = reg.get("memory_recent").handler(agent.ctx, hours=24)
    assert "最近 24h" in out and "API 网关" in out
    # 按分类过滤: 无命中 → 空提示
    out2 = reg.get("memory_recent").handler(agent.ctx, hours=24, kind="feedback")
    assert "没有记忆条目" in out2
    # 非法分类 → 友好报错
    out3 = reg.get("memory_recent").handler(agent.ctx, kind="bogus")
    assert out3.startswith("[memory]") and "bogus" in out3


# ------------------------------------------------------------------ 只读保证

def test_memory_read_only_ops_do_not_write(tmp_path, tuan_home):
    """stats / recall / recent 是只读: 调用前后存储内容与统计完全不变。"""
    kernel, agent = _make_ctx(tmp_path)
    store = kernel.require("memory_store")
    _seed(store, "部署流程: 先 build 再 push 最后 restart", kind="project", tags=["ops"])
    reg = kernel.require("tool_registry")
    stats_before = store.get_stats()
    memory_before = store.read_memory()
    reg.get("memory_stats").handler(agent.ctx)
    reg.get("memory_recall").handler(agent.ctx, task="部署")
    reg.get("memory_recent").handler(agent.ctx, hours=24)
    assert store.get_stats() == stats_before
    assert store.read_memory() == memory_before
    assert len(store.list_by_kind(limit=100)) == 1
