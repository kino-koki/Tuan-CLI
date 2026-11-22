"""GitHub 只读集成工具 (``gh``) —— 把既有 GitHub 能力暴露为 Agent 工具。

复用的底层模块 (不重复造轮子):
  * :mod:`tuan_cli.tools.gh_borrow` —— GitHubClient (gh CLI 优先 / REST 回退)、
    borrow() 借鉴编排、format_borrow() 渲染、DEFAULT_LIMIT;
  * :mod:`tuan_cli.gh.native` / :mod:`tuan_cli.gh.policy` —— 原生 gh 透传与
    破坏性操作分级 (本工具只取其"只读"精神, 见下)。

安全原则 (与 ``tuan gh`` 的安全沙箱一致):
  * **本工具绝不修改 GitHub 状态**。所有 op 都是只读; op=api 恒为 GET,
    路径里出现任何写/删 HTTP 方法词 (POST/PATCH/PUT/DELETE) 或 ``-X``/
    ``--method`` 方式覆盖都会被只读闸门拒绝 —— 写操作必须由用户通过本机
    ``gh`` 执行 (那里有完整的确认/审计/拦截链路)。
  * **主用 op=borrow**: 自主发现相似开源项目并「借鉴」(带署名、非全抄),
    完全复用 gh_borrow.borrow()/format_borrow() 的编排与渲染。
  * **离线可测**: GitHubClient 支持注入 http_get, 测试不触网。
  * 错误一律渲染为 "[gh] ..." 的模型可读文本, 绝不向 Agent 抛原始异常;
    匿名限流时附上设置 GITHUB_TOKEN 的提示。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict

from ..core.kernel import Kernel, Plugin
from ..tools.base import Tool, ToolContext, string_prop
from . import gh_borrow

import logging
log = logging.getLogger(__name__)

# op=api 的只读闸门: 路径按整词出现这些 HTTP 方法词 (大小写不敏感) 即拒绝。
# 本工具永远只发 GET; 写操作请走用户自己的 gh。
_API_WRITE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}

# 拦截 "-X DELETE" / "-XPUT" / "--method=post" 这类把方法词拼进路径的写法。
_API_METHOD_OVERRIDE_RE = re.compile(r"(-x|--method)\s*[=: ]?\s*(delete|post|patch|put)")

# op=api 输出截断上限 (字符), 避免超大 JSON 淹没模型上下文。
_API_OUTPUT_LIMIT = 6000

_OPS = ("borrow", "search_repos", "search_code", "repo_view", "api")


# ================================================================ 小工具

def _to_limit(value: Any, default: int = gh_borrow.DEFAULT_LIMIT) -> int:
    """把 limit 参数安全地转为 [1, 50] 内的整数; 非法时用默认值。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(n, 50))


def _gh_error(msg: str, exc: BaseException) -> str:
    """统一错误渲染: ``[gh]`` 前缀 + 简短原因; 限流/认证失败时附提示。"""
    text = str(exc).strip() or type(exc).__name__
    low = text.lower()
    hint = ""
    if "rate limit" in low or "429" in low or "403" in low:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            hint = ("\n提示: 当前未设置 GITHUB_TOKEN/GH_TOKEN, 匿名访问限额 60 次/小时; "
                    "设置 GITHUB_TOKEN 环境变量后可提升限额。")
    elif "401" in low or "bad credentials" in low or "unauthorized" in low:
        hint = "\n提示: GitHub 认证失败, 请检查 GITHUB_TOKEN/GH_TOKEN 是否有效。"
    return f"[gh] {msg}: {text[:300]}{hint}"


# ================================================================ op 实现

def _op_borrow(kw: Dict[str, Any]) -> str:
    """op=borrow —— 与 cmd_gh._handle_borrow 同构的参数构造。

    query 取 task 或 query; mode 默认 code (非法值回退 code, 与 borrow()
    的 ``mode == "repo"`` 分支语义一致); limit 默认 DEFAULT_LIMIT。
    成功时用 format_borrow() 渲染 (自带借鉴原则 pledge 与署名要求)。
    """
    query = str(kw.get("task") or kw.get("query") or "").strip()
    if not query:
        return "[gh] borrow 需提供借鉴任务/关键词 (task 或 query 参数)"
    mode = str(kw.get("mode") or "code").strip().lower()
    if mode not in ("code", "repo"):
        mode = "code"
    limit = _to_limit(kw.get("limit"))
    res = gh_borrow.borrow(query, mode=mode, limit=limit)
    return gh_borrow.format_borrow(res)


def _op_search(kw: Dict[str, Any], *, code: bool) -> str:
    """op=search_repos / search_code —— GitHubClient 搜索 + 简洁行格式化。"""
    query = str(kw.get("query") or kw.get("task") or "").strip()
    if not query:
        return f"[gh] search_{'code' if code else 'repos'} 需提供 query 关键词"
    limit = _to_limit(kw.get("limit"))
    client = gh_borrow.GitHubClient()
    rows = (client.search_code(query, limit) if code
            else client.search_repos(query, limit))
    if not rows:
        return f"[gh] 未找到匹配结果: {query} (可换关键词或提高 limit)"
    label = "代码搜索" if code else "仓库搜索"
    lines = [f"[gh] {label}: {query} (共 {len(rows)} 条)"]
    for i, it in enumerate(rows, 1):
        if code:
            repo = (it.get("repository") or {}).get("full_name") or "?"
            path = it.get("path") or ""
            url = it.get("html_url") or f"https://github.com/{repo}/blob/main/{path}"
            lines.append(f"{i}. {repo} · `{path}`")
            lines.append(f"   {url}")
        else:
            name = it.get("full_name") or "?"
            desc = (it.get("description") or "").strip()
            stars = it.get("stargazers_count", 0) or 0
            lic = (it.get("license") or {}).get("spdx_id") or "?"
            url = it.get("html_url") or f"https://github.com/{name}"
            lines.append(f"{i}. {name}  ⭐{stars}  许可证: {lic}")
            if desc:
                lines.append(f"   {str(desc)[:160]}")
            lines.append(f"   {url}")
    return "\n".join(lines)


def _op_repo_view(kw: Dict[str, Any]) -> str:
    """op=repo_view —— 与 cmd_gh._run_rest 的 repo view 相同的 _rest 路径。"""
    repo = str(kw.get("repo") or kw.get("query") or "").strip().strip("/")
    if not repo:
        return "[gh] repo_view 需提供 repo (owner/repo)"
    client = gh_borrow.GitHubClient()
    data = client._rest("https://api.github.com/repos/" + repo)
    lines = [
        f"[gh] 仓库 {data.get('full_name', repo)}  ⭐{data.get('stargazers_count', 0)}"
        f"  fork:{data.get('forks_count', 0)}",
    ]
    if data.get("description"):
        lines.append(str(data["description"]))
    bits = []
    if data.get("language"):
        bits.append(f"语言: {data['language']}")
    lic = (data.get("license") or {}).get("spdx_id")
    if lic:
        bits.append(f"许可证: {lic}")
    if data.get("open_issues_count") is not None:
        bits.append(f"开放 issue: {data['open_issues_count']}")
    if data.get("updated_at"):
        bits.append(f"最近更新: {data['updated_at']}")
    if bits:
        lines.append("  " + " · ".join(str(b) for b in bits))
    if data.get("html_url"):
        lines.append(f"  {data['html_url']}")
    return "\n".join(lines)


def _op_api(kw: Dict[str, Any]) -> str:
    """op=api —— 只读 GET 任意 GitHub API 路径 (相对 https://api.github.com/)。

    只读闸门: 路径按整词含 POST/PATCH/PUT/DELETE, 或带 ``-X``/``--method``
    方法覆盖写法时直接拒绝, 不发任何请求。本工具永不改写 GitHub 状态。
    """
    path = str(kw.get("path") or kw.get("query") or "").strip().strip("/")
    if not path:
        return "[gh] api 需提供 path (相对 https://api.github.com/, 如 repos/owner/repo)"
    low = path.lower()
    bad = sorted(w for w in (m.lower() for m in _API_WRITE_METHODS)
                 if w in re.findall(r"[a-z]+", low))
    if bad or _API_METHOD_OVERRIDE_RE.search(low):
        return (f"[gh] 已拒绝: op=api 仅支持只读 GET, 路径中检测到写/删方法词 "
                f"{[w.upper() for w in bad] or ['方法覆盖']}; "
                "本工具绝不修改 GitHub 状态, 写操作请由用户通过本机 gh 执行。")
    client = gh_borrow.GitHubClient()
    data = client._rest("https://api.github.com/" + path)
    body = json.dumps(data, ensure_ascii=False, indent=2)
    if len(body) > _API_OUTPUT_LIMIT:
        body = body[:_API_OUTPUT_LIMIT] + "\n…(输出过长, 已截断)"
    return f"[gh] GET https://api.github.com/{path}\n{body}"


# ================================================================ handler

def _gh_handler(ctx: ToolContext, op: str = "borrow", **kw: Any) -> str:
    """``gh`` 工具统一入口: 按 op 分发; 任何异常都渲染为 "[gh] ..." 文本。"""
    op = str(op or "borrow").strip().lower()
    try:
        if ctx is not None:
            ctx.heartbeat("gh", f"gh.{op} 执行中…")
        if op == "borrow":
            return _op_borrow(kw)
        if op == "search_repos":
            return _op_search(kw, code=False)
        if op == "search_code":
            return _op_search(kw, code=True)
        if op == "repo_view":
            return _op_repo_view(kw)
        if op == "api":
            return _op_api(kw)
        return (f"[gh] 未知 op={op!r}; 可用: " + " | ".join(_OPS))
    except Exception as exc:  # noqa: BLE001 —— 错误渲染为模型可读文本, 绝不抛原始异常
        log.warning("gh 工具 op=%s 失败: %s", op, exc)
        label = "借鉴失败" if op == "borrow" else f"op={op} 执行失败"
        return _gh_error(label, exc)


# ================================================================ 插件

class GhToolPlugin(Plugin):
    name = "tools.gh"
    provides: list[str] = []
    requires = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        config = kernel.get("config")
        if config and not config.get("tools.gh.enabled", True):
            return

        registry = kernel.require("tool_registry")
        registry.register(Tool(
            name="gh",
            description=(
                "GitHub 只读集成工具 (绝不修改 GitHub 状态): "
                "op=borrow 自主借鉴相似开源实现 (带署名, 非全抄, 主用); "
                "op=search_repos / search_code 搜索仓库/代码; "
                "op=repo_view 查看仓库概览; "
                "op=api 执行任意只读 GET API (路径含 POST/PATCH/PUT/DELETE 等"
                "写/删方法词会被拒绝)。写操作请由用户通过本机 gh 执行。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "op": {
                        "type": "string",
                        "enum": list(_OPS),
                        "description": (
                            "操作类型: borrow=借鉴相似开源实现(主用); "
                            "search_repos=搜索仓库; search_code=搜索代码; "
                            "repo_view=查看仓库概览; api=只读 GET API"),
                    },
                    "task": string_prop("借鉴任务描述 (op=borrow, 与 query 等价)"),
                    "query": string_prop("搜索/借鉴关键词"),
                    "mode": string_prop("borrow 模式: code(默认, 搜代码取片段) | repo(搜仓库清单)"),
                    "limit": {"type": "integer",
                              "description": "返回条数上限 (默认 5, 上限 50)"},
                    "repo": string_prop("仓库全名 owner/repo (op=repo_view)"),
                    "path": string_prop("API 路径, 相对 https://api.github.com/ "
                                        "(op=api), 例如 repos/owner/repo"),
                },
                "required": ["op"],
            },
            handler=_gh_handler,
            group="tools",
            read_only=True,
        ))
