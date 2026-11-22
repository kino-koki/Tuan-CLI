"""gh 工具测试 —— 全程离线: 注入假 http_get / 假 borrow, 不触网、不依赖本机 gh。

覆盖:
- 插件注册 (gh 进入 tool_registry, 只读、schema 带 op 枚举);
- op=search_repos / search_code: 行格式化 (名称/星标/许可证/链接);
- op=repo_view: 走 client._rest 的仓库视图 (与 cmd_gh._run_rest 同路径);
- op=api: 路径原样拼接 GET, 写/删方法词被只读闸门拒绝且不发请求;
- op=borrow: 透传 gh_borrow.borrow 并用 format_borrow 渲染;
- 错误路径: 未知 op / 缺参 / 匿名限流提示 (GITHUB_TOKEN)。
"""

from __future__ import annotations

import json

from tuan_cli.app import build_kernel
from tuan_cli.core.agent import Agent
from tuan_cli.tools import gh_borrow
from tuan_cli.tools.gh_tool import GhToolPlugin


# ------------------------------------------------------------------ 夹具

def _make_ctx(tmp_path):
    """与 test_session_tools 同款内核夹具; 额外直接激活 GhToolPlugin
    (不改 tools/__init__.py, 注册行由集成方添加)。"""
    kernel = build_kernel()
    GhToolPlugin().activate(kernel)
    config = kernel.require("config")
    agent = Agent(kernel=kernel, config=config, workspace=str(tmp_path),
                  confirm=lambda _p: True)
    return kernel, agent


class _FakeHTTP:
    """假 http_get: 按 URL 子串路由返回固定 JSON, 并记录全部调用。"""

    def __init__(self):
        self.routes = {}
        self.calls = []

    def add(self, needle, payload, status=200):
        self.routes[needle] = (status, json.dumps(payload, ensure_ascii=False))

    def __call__(self, url, headers):
        self.calls.append(url)
        for needle, (status, body) in self.routes.items():
            if needle in url:
                return status, body
        return 404, json.dumps({"message": "Not Found"})


def _patch_offline_client(monkeypatch, http, token="test-token"):
    """把 gh_borrow.GitHubClient 换成: 无 gh + 注入假 http_get 的离线客户端。"""
    class _OfflineClient(gh_borrow.GitHubClient):
        def __init__(self):
            super().__init__(token=token, http_get=http)

        def has_gh(self):
            return False

    monkeypatch.setattr(gh_borrow, "GitHubClient", _OfflineClient)
    return _OfflineClient


# ------------------------------------------------------------------ 注册

def test_gh_tool_registered(tuan_home, tmp_path):
    kernel, _agent = _make_ctx(tmp_path)
    tool = kernel.require("tool_registry").get("gh")
    assert tool is not None
    assert tool.read_only is True and tool.dangerous is False
    assert tool.parameters["properties"]["op"]["enum"] == [
        "borrow", "search_repos", "search_code", "repo_view", "api"]


# ------------------------------------------------------------------ search

def test_search_repos_formats_rows(tmp_path, tuan_home, monkeypatch):
    kernel, agent = _make_ctx(tmp_path)
    http = _FakeHTTP()
    http.add("search/repositories", {"items": [
        {"full_name": "octo/demo", "html_url": "https://github.com/octo/demo",
         "description": "a demo repo", "stargazers_count": 123,
         "license": {"spdx_id": "MIT"}},
        {"full_name": "octo/empty", "html_url": "https://github.com/octo/empty",
         "description": None, "stargazers_count": 0, "license": None},
    ]})
    _patch_offline_client(monkeypatch, http)
    out = kernel.require("tool_registry").get("gh").handler(
        agent.ctx, op="search_repos", query="demo lang:python", limit=2)
    assert "[gh]" in out and "仓库搜索" in out
    assert "octo/demo" in out and "⭐123" in out and "MIT" in out
    assert "a demo repo" in out and "octo/empty" in out
    assert any("search/repositories" in u and "per_page=2" in u for u in http.calls)


def test_search_code_formats_rows(tmp_path, tuan_home, monkeypatch):
    kernel, agent = _make_ctx(tmp_path)
    http = _FakeHTTP()
    http.add("search/code", {"items": [
        {"repository": {"full_name": "octo/demo"}, "path": "src/retry.py",
         "html_url": "https://github.com/octo/demo/blob/main/src/retry.py"},
    ]})
    _patch_offline_client(monkeypatch, http)
    out = kernel.require("tool_registry").get("gh").handler(
        agent.ctx, op="search_code", query="retry backoff language:python")
    assert "[gh]" in out and "代码搜索" in out
    assert "octo/demo" in out and "src/retry.py" in out
    assert any("search/code" in u for u in http.calls)


# ------------------------------------------------------------------ repo_view

def test_repo_view_via_rest(tmp_path, tuan_home, monkeypatch):
    kernel, agent = _make_ctx(tmp_path)
    http = _FakeHTTP()
    http.add("api.github.com/repos/octo/demo", {
        "full_name": "octo/demo", "stargazers_count": 42, "forks_count": 7,
        "description": "demo repository", "language": "Python",
        "license": {"spdx_id": "MIT"}, "open_issues_count": 3,
        "html_url": "https://github.com/octo/demo"})
    _patch_offline_client(monkeypatch, http)
    out = kernel.require("tool_registry").get("gh").handler(
        agent.ctx, op="repo_view", repo="octo/demo")
    assert "octo/demo" in out and "⭐42" in out and "fork:7" in out
    assert "demo repository" in out and "Python" in out and "MIT" in out
    assert any(u == "https://api.github.com/repos/octo/demo" for u in http.calls)


def test_repo_view_via_registry_dispatch(tmp_path, tuan_home, monkeypatch):
    """走 registry.dispatch_result 的端到端: schema 过滤 + 只读放行 + handler。"""
    kernel, agent = _make_ctx(tmp_path)
    http = _FakeHTTP()
    http.add("api.github.com/repos/octo/demo", {
        "full_name": "octo/demo", "stargazers_count": 1, "forks_count": 0,
        "description": "d", "html_url": "u"})
    _patch_offline_client(monkeypatch, http)
    reg = kernel.require("tool_registry")
    result = reg.dispatch_result(
        "gh", json.dumps({"op": "repo_view", "repo": "octo/demo"}), agent.ctx)
    assert result.status == "ok" and "octo/demo" in result.content


# ------------------------------------------------------------------ api

def test_api_op_passes_path_through(tmp_path, tuan_home, monkeypatch):
    kernel, agent = _make_ctx(tmp_path)
    http = _FakeHTTP()
    http.add("api.github.com/repos/octo/demo/issues",
             [{"number": 1, "title": "bug"}, {"number": 2, "title": "feat"}])
    _patch_offline_client(monkeypatch, http)
    out = kernel.require("tool_registry").get("gh").handler(
        agent.ctx, op="api", path="repos/octo/demo/issues?state=open")
    assert "GET https://api.github.com/repos/octo/demo/issues?state=open" in out
    assert '"number": 1' in out and "bug" in out
    assert any(u.endswith("repos/octo/demo/issues?state=open") for u in http.calls)


def test_api_op_rejects_write_methods(tmp_path, tuan_home, monkeypatch):
    kernel, agent = _make_ctx(tmp_path)
    http = _FakeHTTP()
    _patch_offline_client(monkeypatch, http)
    handler = kernel.require("tool_registry").get("gh").handler
    for bad in ("repos/octo/demo -X DELETE", "repos/octo/demo?method=post",
                "user/repos -XPUT", "repos/octo/demo/patch"):
        out = handler(agent.ctx, op="api", path=bad)
        assert "[gh] 已拒绝" in out, f"应拒绝: {bad}"
    assert http.calls == []  # 只读闸门: 从未发出任何请求


# ------------------------------------------------------------------ borrow

def test_borrow_op_delegates_to_gh_borrow(tmp_path, tuan_home, monkeypatch):
    kernel, agent = _make_ctx(tmp_path)
    captured = {}

    def fake_borrow(query, *, mode="code", limit=gh_borrow.DEFAULT_LIMIT, **kw):
        captured.update(query=query, mode=mode, limit=limit)
        return {"query": query, "mode": mode, "pledge": gh_borrow.BORROW_PLEDGE,
                "items": [{"repo": "octo/demo",
                           "url": "https://github.com/octo/demo",
                           "path": "src/x.py", "snippet": "print('hi')\n",
                           "desc": "demo", "stars": 3, "license": "MIT"}]}

    monkeypatch.setattr(gh_borrow, "borrow", fake_borrow)
    out = kernel.require("tool_registry").get("gh").handler(
        agent.ctx, op="borrow", task="怎么做指数退避重试", mode="code", limit=2)
    assert captured == {"query": "怎么做指数退避重试", "mode": "code", "limit": 2}
    assert "octo/demo" in out and "借鉴原则" in out and "src/x.py" in out


def test_borrow_op_accepts_query_and_empty_items(tmp_path, tuan_home, monkeypatch):
    kernel, agent = _make_ctx(tmp_path)
    seen = {}

    def fake_borrow(query, **kw):
        seen.update(query=query, **kw)
        return {"query": query, "mode": "repo", "pledge": gh_borrow.BORROW_PLEDGE,
                "items": []}

    monkeypatch.setattr(gh_borrow, "borrow", fake_borrow)
    out = kernel.require("tool_registry").get("gh").handler(
        agent.ctx, op="borrow", query="cli agent harness", mode="repo")
    assert seen["query"] == "cli agent harness" and seen["mode"] == "repo"
    assert "未找到匹配" in out  # 空 items 的 format_borrow 渲染


# ------------------------------------------------------------------ 错误路径

def test_unknown_op_and_missing_params(tmp_path, tuan_home):
    kernel, agent = _make_ctx(tmp_path)
    handler = kernel.require("tool_registry").get("gh").handler
    assert "未知 op" in handler(agent.ctx, op="nope")
    assert "需提供" in handler(agent.ctx, op="borrow")
    assert "需提供" in handler(agent.ctx, op="search_repos")
    assert "需提供" in handler(agent.ctx, op="repo_view")
    assert "需提供" in handler(agent.ctx, op="api")


def test_rate_limit_hint_without_token(tmp_path, tuan_home, monkeypatch):
    kernel, agent = _make_ctx(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    http = _FakeHTTP()
    http.add("search/repositories",
             {"message": "API rate limit exceeded for 1.2.3.4."}, status=403)
    _patch_offline_client(monkeypatch, http, token=None)
    out = kernel.require("tool_registry").get("gh").handler(
        agent.ctx, op="search_repos", query="x")
    assert "[gh]" in out and "GITHUB_TOKEN" in out
