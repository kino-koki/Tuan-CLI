"""斜杠命令处理器 —— REPL 内 /xxx 命令。

拆分自 commands.py。
"""

from __future__ import annotations

import json
from typing import Any, Dict

from ..i18n import t
from ._ui_singleton import ui
from .cmd_slash_blast import _cmd_blast
from .cmd_slash_goal import _cmd_goal
from .cmd_slash_mcp import _cmd_audit, _cmd_mcp
from .cmd_slash_offline import _cmd_offline
from .cmd_slash_sandbox import _cmd_sandbox
from .cmd_slash_boundary import (
    _cmd_rewind as _boundary_rewind,
    _cmd_handoff as _boundary_handoff,
    _cmd_worktree as _boundary_worktree,
    _cmd_subagent_enhanced,
)
from .cmd_slash_image import _cmd_image
from .cmd_slash_memory import _cmd_memory
from .cmd_slash_provider import _cmd_provider
from .cmd_slash_session import _cmd_export, _cmd_import
from .cmd_slash_superagent import _cmd_superagent
from .cmd_slash_claude import (
    cmd_fork,
    cmd_branch,
    cmd_cd,
    cmd_btw,
    cmd_copy,
    cmd_tasks,
    cmd_background,
    cmd_theme,
    cmd_color,
    cmd_loop,
    cmd_review,
    cmd_simplify,
    cmd_debug,
    cmd_config_slash,
    cmd_batch,
    cmd_dataviz,
    cmd_design,
    cmd_artifacts,
    cmd_auto_mode_setup,
)


_HELP = """
可用斜杠命令 (Slash Commands)

── 核心层 (Core, / 弹出菜单默认展示) ──
  /help      显示帮助
  /model     切换/查看模型
  /mode      切换运行模式 (感通/灵码/闲聊/无界/协同; 旧名 standard/yolo/plan 可用)
  /memory    查看记忆
  /clear     清空对话上下文 (OpenCode /new 别名)
  /compact   手动压缩上下文 (折叠旧历史)
  /context   上下文占用
  /cost      成本估算 (token + 缓存命中率 + 费用)
  /usage     本次会话 token 用量
  /undo      精细回滚 (事务化账本: /undo /undo N /undo <file> /undo all /undo --safe)
  /diff      工作区变更摘要 (支持 /diff <file> / /diff --full)
  /export    导出会话为 Markdown 文件 ( /export [文件名] )
  /exit      退出
  /status    会话状态摘要 (模型/模式/上下文/用量/韧性)
  /tools     列出可用工具
  /skills    列出技能
  /mcp       MCP 管理 (list/tools/audit/security)
  /permissions  展示当前生效的权限策略 (只读)
  /web       启动本地 Web 工作台 (无参数) 或快捷联网 ( /web <URL> 或  /web search <关键词> )
  /plan      切换 Plan 模式 (只读分析, 修改类工具被拦截)

── 专家层 (Expert, 折叠; 输入 /<首字母> 前缀或 /help 可查全部) ──
  [...]/add-dir   把工作区外目录纳入本会话上下文 ( /add-dir <路径> [--writable]; 无参列出 )
  [...]/audit     审计报告 (统计/查看/导出合规报告)
  [...]/blast     Blast Radius 交互式可视化 (影响半径/安全风险/工具统计)
  [...]/budget    查看/设置成本预算上限 ( /budget <USD> )
  [...]/checkpoint  会话检查点 ( /checkpoint save 保存;  restore [id] 回滚; list 查看 )
  [...]/clear-images  清除待发送的图片
  [...]/commands  热插拔命令管理: list / reload / enable <名> / disable <名>
  [...]/code      代码感知问答: ContextForge 检索工作区后带上下文执行 ( /code <任务> )
  [...]/effort    切换推理投入 low/medium/high
  [...]/gh-borrow GitHub 参考借力 ( /gh-borrow <关键词> 检索公开代码作参考 )
  [...]/goal      Goal 模式 (/goal <目标描述>, 循环直到条件满足)
  [...]/handoff   会话交接 ( /handoff 生成摘要 -> 开新会话继续 )
  [...]/hooks     用户级 Hooks ( /hooks 列出已配置脚本; /hooks test 触发一次)
  [...]/image     图片管理 + AI 生成 ( /image <路径|URL> · /image generate <描述> · /image list )
  [...]/images    列出当前待发送的图片
  [...]/impact    展示操作账本与影响半径 (哪些文件被改、改了几步)
  [...]/import    导入 Markdown 对话 ( /import <文件路径> )
  [...]/init      扫描工作区生成 TUAN.md 项目规则
  [...]/log       最近工具调用历史 ( /log [N] 默认 15 条 )
  [...]/mcp-tools MCP Tool Search 上下文占用 (report/on/off/search)
  [...]/more      展开上一条被折叠的长输出
  [...]/offline   离线模式 (Ollama 本地模型管理)
  [...]/personality 人设管理 ( /personality [list|show|set <人设名>|auto] )
  [...]/provider  查看/设置/清除 API Key 与供应商 ( /provider set <ENV> <KEY> · /provider clear [ENV] )
  [...]/quit      退出
  [...]/resume    恢复历史会话 (编号/会话id/latest)
  [...]/session   会话管理 (无参列出; /session <编号|会话id|latest> 恢复)
  [...]/route     智能模型路由建议 (咨询式, 输入 /route <任务>)
  [...]/rewind    会话时间线回溯 ( /rewind 回退一步; /rewind list 列快照; /rewind to <N> )
  [...]/sandbox   沙箱执行 (在 Docker 容器中隔离执行危险命令)
  [...]/stats     Agent 可观测性面板 (trace/span/延迟/错误率, 需开启 telemetry)
  [...]/subagent  派发隔离子代理 (独立上下文) 执行任务并回收摘要
  [...]/superagent  Super-Agent: DeepSeek 双层架构 (start/stop/status/panel/ingest/speculate)
  [...]/swarm     多 Agent 协作 (强模型规划 -> 弱模型并发执行 -> 强模型验收)
  [...]/verify    编码验证闭环 (自动跑 test/typecheck/lint, 失败自修复)
  [...]/worktree  git worktree 并行实验 ( create/list/remove/switch )
  [...]/workflow  动态并行工作流管理 ( list/status <wf>/result <wf>/cancel <wf>/retry <wf> )
  [...]/background  后台任务管理 ( create <任务>/list/status <id>/result <id>/cancel <id> )
  [...]/branch    git 分支管理 ( create <名>/switch <名>/list/delete <名> )
  [...]/btw       发送前提醒 ( 在下次回复前附加一条提示 )
  [...]/cd        切换工作目录 ( /cd <路径>; 无参查看当前 )
  [...]/color     切换 UI 配色主题 ( /color [名]; 无参列出 )
  [...]/config    查看/编辑配置 ( /config get <key> / set <key> <val> / list )
  [...]/copy      复制最后输出到剪贴板 ( /copy [all] )
  [...]/debug     调试开关 ( /debug on|off; 查看日志/跟踪 )
  [...]/doctor    环境健康诊断 ( 检查 Python/Node/git/网络, 可 --fix 修复 )
  [...]/fork      分叉当前会话 ( /fork; 生成新会话副本继续 )
  [...]/loop      循环执行直到条件满足 ( /loop <目标> <条件> )
  [...]/review    代码审查 ( AI 审查工作区未提交变更 )
  [...]/security-review  安全审查 ( 扫描依赖/路径/注入风险 )
  [...]/simplify  简化重构 ( 对指定文件做去重/去死代码 )
  [...]/tasks     任务管理 ( 后台任务列表/状态/取消 )
  [...]/theme     切换主题 ( /theme [名]; 无参列出可用主题 )
  [...]/batch     批量后台任务 ( /batch <任务1> | <任务2> | ... )
  [...]/dataviz   数据可视化生成 ( /dataviz <数据描述> )
  [...]/design    前端设计生成 ( /design <界面描述> )
  [...]/artifacts Artifact 生成 ( /artifacts <工件描述> )
  [...]/auto-mode-setup  Auto 模式分类器展示与测试 ( /auto-mode-setup [test <tool> '<json>'] )
  [...]/language   切换界面语言 ( /language [代码]; 无参列出可用 )

提示: Enter 发送 · Esc+Enter 换行 · 多行可用三引号
TUI 中: 输入 / 或 +/ 即会弹出命令补全菜单 (Tab 切换, 回车执行; 仅列核心层, 输入首字母可展开专家层)"""


# 权威命令清单: 与 _handle_slash 的 elif 分支一一对应。
# 供 TUI / REPL 的补全词表、命令发现、ACP/IDE 能力清单共用, 避免多处维护漂移。
SLASH_COMMAND_NAMES: tuple = (
    "/add-dir", "/audit", "/background", "/blast", "/branch", "/btw", "/budget", "/cd", "/checkpoint",
    "/clear", "/new", "/clear-images", "/color", "/commands", "/compact", "/config",
    "/context", "/copy", "/cost", "/debug", "/diff", "/doctor",
    "/effort", "/exit", "/export", "/fork", "/gh-borrow", "/goal",
    "/help", "/hooks", "/image", "/init", "/images", "/impact", "/import", "/log",
    "/loop", "/mcp", "/mcp-tools", "/memory", "/mode", "/model", "/more", "/offline", "/permissions", "/plan", "/provider", "/quit", "/resume", "/review", "/route", "/sandbox", "/security-review", "/session", "/simplify", "/skills", "/stats",
    "/status", "/subagent", "/superagent", "/swarm", "/tasks", "/theme", "/tools", "/undo", "/usage", "/verify",
    "/rewind", "/handoff", "/worktree",
    "/web", "/workflow", "/code", "/commands",
    "/personality",
    "/batch", "/dataviz", "/design", "/artifacts",
    "/language",
)


# 核心层命令: TUI "/" 面板默认展示 ≤ 20 项; 其余归入专家层。
# 分层只影响 TUI 补全菜单显示, 不改变 list_slash_commands() 的全集 (供 ACP/IDE 协商)。
# 权威分层定义已移至 slash_tier.py (§2.3), 此处保留兼容副本供 _handle_slash 与
# cmd_chat.py 的 slash_command_tiers() 使用; TUI 补全菜单应导入 slash_tier.slash_command_tier。
CORE_SLASH_COMMANDS: frozenset = frozenset({
    "/help", "/model", "/mode", "/memory", "/clear", "/new", "/compact",
    "/context", "/cost", "/usage", "/undo", "/diff", "/export",
    "/exit", "/status", "/tools", "/skills", "/mcp",
    "/web", "/plan",
})


def slash_command_tier(name: str) -> str:
    """返回命令层级: 'core' | 'expert' | 'hidden'。

    - core: 核心层, TUI "/" 面板默认展开即可见 (≤ 20 项)
    - expert: 专家层, 需输入首字母前缀才在补全菜单中出现
    - hidden: 隐藏层, 不进补全, 仅 /help 全量列出 (当前未使用)

    不认识的命令 (用户自定义热插拔命令) 归入 expert, 保证可见性。
    """
    if name in CORE_SLASH_COMMANDS:
        return "core"
    return "expert"


def slash_command_tiers() -> Dict[str, str]:
    """枚举内置命令 -> tier 的映射表 (供 TUI 补全过滤器使用)。"""
    return {n: slash_command_tier(n) for n in SLASH_COMMAND_NAMES}


# 命令一句话描述 (补全菜单 display_meta / /help 用); 未收录的命令回退通用提示。
_CMD_META: Dict[str, str] = {
    "/add-dir": "把工作区外目录纳入本会话上下文 (/add-dir [路径] [--writable]); 开启写边界后普通授权仅读",
    "/help": "显示帮助",
    "/tools": "列出可用工具",
    "/skills": "列出技能",
    "/memory": "查看记忆",
    "/model": "切换模型",
    "/provider": "查看/设置/清除 API Key",
    "/usage": "本次会话 token 用量",
    "/cost": "本次会话花费",
    "/mode": "切换运行模式 (感通/灵码/闲聊/无界/协同; 旧名 standard/yolo/plan 可用)",
    "/effort": "切换推理档位",
    "/plan": "进入/退出只读规划模式",
    "/permissions": "权限模式设置",
    "/clear": "清空对话上下文 (OpenCode /new 别名)",
    "/new": "清空对话上下文 (OpenCode 别名)",
    "/compact": "压缩上下文",
    "/context": "查看上下文占用",
    "/undo": "撤销最近一次文件改动",
    "/diff": "查看最近改动 diff",
    "/impact": "分析改动影响面",
    "/export": "导出会话为 Markdown",
    "/import": "导入 Markdown 对话",
    "/resume": "恢复历史会话",
    "/session": "会话管理 (无参列出; /session <编号|会话id|latest> 恢复)",
    "/checkpoint": "会话检查点 (save/restore/list)",
    "/web": "启动本地 Web 工作台 (无参数) 或快捷联网",
    "/code": "代码感知问答: 检索工作区后带上下文执行",
    "/commands": "热插拔命令管理: list/reload/enable/disable",
    "/verify": "编码验证闭环 (test/typecheck/lint 失败自修复)",
    "/subagent": "派发隔离子代理执行任务 (run/status)",
    "/superagent": "Super-Agent: DeepSeek 双层架构 (Router/Worker/事件驱动/Watchdog)",
    "/personality": "人设管理 (list/show/set/auto)",
    "/rewind": "会话时间线回溯 (快照回退)",
    "/handoff": "会话交接: 摘要压缩后开新会话",
    "/worktree": "git worktree 并行实验",
    "/workflow": "动态并行工作流管理",
    "/swarm": "多 Agent 协作",
    "/route": "智能模型路由建议",
    "/sandbox": "沙箱策略",
    "/offline": "离线模式",
    "/audit": "审计日志",
    "/blast": "多步骤批量执行",
    "/budget": "预算设置",
    "/goal": "目标分解执行",
    "/hooks": "钩子管理",
    "/init": "扫描工作区生成 TUAN.md 项目规则",
    "/image": "图片管理 + AI 生成 (多模态)",
    "/images": "列出待发送图片",
    "/mcp": "MCP 服务器管理",
    "/mcp-tools": "MCP 工具列表",
    "/gh-borrow": "GitHub 参考借力",
    "/stats": "统计信息",
    "/status": "运行状态",
    "/exit": "退出",
    "/quit": "退出",
    "/more": "展开上一条被折叠的长输出",
    # ---- Claude Code 对齐 (v2.1.289) ----
    "/fork": "复制当前对话到新后台会话 (/fork [at_message N] [note 备注])",
    "/branch": "会话分叉树查看/切换",
    "/cd": "会话内切换工作目录",
    "/btw": "旁问: 主任务不中断的 side question",
    "/copy": "复制最近响应到剪贴板",
    "/tasks": "后台任务列表 (list/logs/cancel/wait)",
    "/background": "分离为后台 agent (/bg 别名)",
    "/theme": "切换 UI 主题 (dark/light)",
    "/color": "配色方案 (brand/blue/green)",
    "/loop": "进入/切换自主开发循环",
    "/review": "自动代码评审 (/code-review 别名)",
    "/security-review": "安全审查",
    "/simplify": "简化冗余代码",
    "/debug": "调试诊断 (配置/日志/内核)",
    "/config": "会话内配置 (key=value / get / dump)",
    "/doctor": "修复型 setup checkup (诊断 + 可修复)",
    "/batch": "批量后台任务 (用 | 分隔多任务, 并行执行)",
    "/dataviz": "数据可视化任务 (图表生成)",
    "/design": "设计工作流 (前端设计产出)",
    "/artifacts": "生成 artifact (自包含 HTML 产物)",
    "/language": "切换界面语言 (/language [代码]; 无参列出可用语言)",
}


def slash_command_meta() -> Dict[str, str]:
    """命令描述表 (补全菜单 meta / 帮助展示)。"""
    return dict(_CMD_META)


def list_slash_commands() -> list:
    """枚举支持的斜杠命令名 (供补全词表 / ACP/IDE 能力清单)。

    内置命令 + 热插拔命令 (用户命令表), 保持补全词表与实际可执行命令一致。
    """
    names = list(SLASH_COMMAND_NAMES)
    try:
        from . import user_commands as _uc
        for item in _uc.describe_commands():
            n = f"/{item['name']}"
            if n not in names:
                names.append(n)
    except Exception:  # noqa: BLE001
        pass
    return names


class _CfgStub:
    """最小配置桩: 仅供 /permissions test 把 rules 喂给 PermissionPolicy。"""

    def __init__(self, rules: Any) -> None:
        self._rules = rules

    def get(self, key: Any, default: Any = None) -> Any:
        return self._rules if key == "permissions.rules" else default


def _cmd_permissions(config: Any, arg: str = "") -> None:
    """/permissions — 展示当前生效的权限策略; /permissions test <tool> <json> 测试命中。"""
    rules = config.get("permissions.rules", [])
    # /permissions test <tool> <json参数> — 只读测试某次调用会命中哪条规则
    if arg.strip().lower().startswith("test"):
        parts = arg.strip().split(maxsplit=2)
        if len(parts) < 2:
            ui.info("  用法: /permissions test run_shell {\"command\":\"rm -rf /\"}")
            return
        tool = parts[1]
        try:
            call_args = json.loads(parts[2]) if len(parts) > 2 else {}
        except Exception as exc:  # noqa: BLE001
            ui.error(f"  参数 JSON 解析失败: {exc}")
            return
        from ..tools.permissions import PermissionPolicy
        policy = PermissionPolicy(_CfgStub(rules))
        result = policy.inspect(tool, call_args)
        ui.info(f"  测试调用: {tool}({parts[2] if len(parts) > 2 else '{}'})")
        if not result["hits"]:
            ui.info("  无规则命中 → 走默认决策")
            return
        ui.info(f"  命中 {len(result['hits'])} 条, 最终动作: {result['action']}")
        for hit in result["hits"]:
            r = hit["rule"]
            detail = (f"{r.get('tool')}({r.get('param')}={r.get('value', '*')})"
                      if r.get("param") else str(r.get("tool")))
            ui.info(f"    #{hit['index']}  {r.get('action')}  {detail}")
        return
    deny = config.get("permissions.shell.deny_patterns", [])
    net = config.get("permissions.network.allow_domains", [])
    red = config.get("mode.yolo_require_confirm", [])
    ui.info(f"  权限规则 (permissions.rules): {len(rules)} 条")
    for r in rules:
        if isinstance(r, dict):
            if r.get("param"):
                detail = f"{r.get('tool')}({r.get('param')}={r.get('value', '*')})"
            else:
                p = f" {r.get('pattern')}" if r.get("pattern") else ""
                detail = f"{r.get('tool')}{p}"
            ui.info(f"    {r.get('action')}  {detail}")
    ui.info("  Shell 拒绝规则: " + (", ".join(deny) if deny else "(无)"))
    ui.info("  网络域名白名单: " + (", ".join(net) if net else "(不限制)"))
    ui.info("  YOLO 仍需确认的工具: " + (", ".join(sorted(red)) if red else "(无)"))
    ui.info("  生效说明: 内置加固 > deny > ask > allow > 默认决策 (危险工具默认需确认)。")
    ui.info("  精确粒度示例: tuan config set permissions.rules "
            "'[{\"tool\":\"run_shell\",\"param\":\"command\",\"value\":\"rm -rf*\",\"action\":\"deny\"}]'")


def _cmd_status(agent: Any, config: Any) -> None:
    """/status — 会话状态摘要。"""
    ui.info(f"  模型: {config.get('model.provider')}/{config.get('model.model')}")
    mode = str(config.mode)
    if agent.yolo:
        mode += " (YOLO)"
    if agent.plan_mode:
        mode += " · PLAN 只读"
    ui.info(f"  模式: {mode}")
    ui.info(f"  推理投入: {config.get('agent.effort', 'high')}")
    # 人设 (Personality): 大上下文模型专属行为风格
    try:
        from ..core.personality import resolve_personality, get_personality_info
        memory_store = agent.kernel.get("memory_store")
        persona = resolve_personality(config, memory_store)
        info = get_personality_info(persona)
        ui.info(f"  人设: {info['name']} ({info['key']}) — {info['tagline']}")
    except Exception:
        pass  # 人设模块不可用不影响状态显示
    ui.info(f"  会话消息: {len(agent.messages)} 条")
    st = agent.context_stats()
    ui.info(f"  上下文: {st.get('estimated_tokens', '?')} / {st.get('budget_tokens', '?')} tokens")
    usage = agent.total_usage
    ui.usage(usage)
    rs = agent.resilience_status()
    ui.info("  韧性:")
    br = rs["circuit_breaker"]
    if br.get("enabled"):
        state = br.get("state", "closed")
        if state == "closed":
            ui.success(f"    熔断: 已启用 · 正常 (closed, 阈值 {br.get('failure_threshold')} / 冷却 {br.get('cooldown')}s)")
        elif state == "half_open":
            ui.info(f"    熔断: 已启用 · 探测中 (half_open, 阈值 {br.get('failure_threshold')} / 冷却 {br.get('cooldown')}s)")
        else:
            ui.error(f"    熔断: 已启用 · 已熔断 (open, 冷却 {br.get('cooldown')}s, 连续失败 {br.get('failures', 0)})")
    else:
        ui.info("    熔断: 未启用 (agent.circuit_breaker.enabled=false)")
    rl = rs["rate_limiter"]
    if rl["active"]:
        conc = f" / 并发<={rl['max_concurrent']}" if rl["max_concurrent"] else ""
        ui.info(f"    限流: 已启用 (<={rl['max_rpm']} req/min{conc})")
    else:
        ui.info("    限流: 未启用 (model.rate_limit.enabled=false)")
    rt = rs["retry"]
    ui.info(f"    重试: <={rt['max_retries']} 次 · 退避 {rt['backoff']}s · 重试图谱 {rt['retry_on']}")


def _cmd_stats(agent: Any, config: Any) -> None:
    """/stats — Agent 可观测性面板。"""
    tc = getattr(agent, "_telemetry", None)
    if tc is None:
        ui.info("可观测性(telemetry)未启用。设置 observability.telemetry.enabled: true 后, "
                "本面板展示 Agent 循环的 trace/span 与延迟/错误率等指标。")
        return
    s = tc.get_stats()
    ui.info("=== Agent 可观测性 (telemetry) ===")
    ui.info(f"  trace/spans: {s['total_traces']}/{s['total_spans']}  ·  活跃 span: {s['active_spans']}")
    ui.info(f"  错误: {s['total_errors']}  ·  错误率: {s['error_rate']}%")
    ui.info(f"  模型调用: 平均 {s['avg_model_latency_ms']} ms  ·  累计 tokens: {s['total_tokens']:,}")
    ui.info(f"  工具调用: {s['total_tool_calls']} 次  ·  平均 {s['avg_tool_latency_ms']} ms")
    if s["recent_model_calls"]:
        last = s["recent_model_calls"][-1]
        ui.info(f"  最近模型调用: {last['latency_ms']:.0f} ms · {last['tokens']} tokens · "
                f"{'成功' if last['success'] else '失败'}")


def _cmd_budget(agent: Any, config: Any, arg: str) -> None:
    """/budget [USD] — 查看或设置成本预算上限。"""
    if arg:
        try:
            amount = float(arg.strip())
        except ValueError:
            ui.error("用法: /budget <USD 金额>  (无参 = 查看当前预算)")
            return
        config.set_user("router.budget_limit", amount)
        ui.success(f"成本预算上限已设: ${amount:.2f}" + ("" if amount > 0 else " (0 = 不限制)"))
        return
    cur = float(config.get("router.budget_limit", 0.0) or 0.0)
    ui.info(f"  成本预算上限: ${cur:.2f}" + (" (到达自动停止)" if cur > 0 else " (不限制)"))
    try:
        spent = agent._estimate_total_cost()
        ui.info(f"  本会话估算已花费: ${spent:.4f}")
    except Exception:  # noqa: BLE001
        pass


def _cmd_checkpoint(agent: Any, arg: str) -> None:
    """/checkpoint [save|list|restore [id]] — 会话检查点。"""
    from ..tools.checkpoint import checkpoint_save, checkpoint_list, checkpoint_restore
    sp = arg.split()
    action = sp[0].lower() if sp else "list"
    if action in ("save", "s"):
        ui.success(checkpoint_save(agent.ctx, " ".join(sp[1:])))
    elif action in ("restore", "r"):
        cid = sp[1] if len(sp) > 1 else ""
        label = cid or "最近一个"
        if agent.ctx.confirm and not agent.ctx.confirm(f"恢复检查点 {label}? 将回滚其后的全部文件变更并把对话截回当时。"):
            ui.info("已取消恢复。")
            return
        ui.success(checkpoint_restore(agent.ctx, cid))
    else:
        ui.info(checkpoint_list(agent.ctx) or "没有已保存的检查点。")


def _cmd_add_dir(agent: Any, arg: str) -> None:
    """/add-dir [路径] [--writable] — 把工作区外目录纳入本会话上下文。

    无参: 列出当前已授权目录。带路径: 显式授权该目录。
    ``--writable`` 显式登记为可写根（供
    ``permissions.blockWritesOutsideWorkingDirectories`` 开启后放行写）。
    授权为 per-session 内存态, 不落盘。

    **口径纠偏**：旧帮助写「可读上下文 / 仅读; 写仍走既有守卫」，实测
    ``/add-dir /tmp/ext`` 之后 write/edit/move/delete 全部越界放行 ——
    「确认对话」不是路径硬边界。现在默认行为不变但文案如实；开启写边界后
    普通授权才真正变成仅读。
    """
    from ..tools.filesystem import (
        authorize_extra_dir, list_extra_dirs, list_writable_dirs,
    )
    parts = arg.strip().split()
    writable = "--writable" in parts
    parts = [x for x in parts if x != "--writable"]
    rest = " ".join(parts).strip()
    if not rest:
        dirs = list_extra_dirs(agent.ctx)
        wr = list_writable_dirs(agent.ctx)
        if not dirs:
            ui.info("当前没有额外授权目录。用法: /add-dir <绝对路径> [--writable]")
            return
        ui.info("已授权的额外目录 (本会话, 内存态, 不落盘):")
        wset = set(wr)
        for d in dirs:
            ui.info(f"  - {d}" + ("  [可写]" if d in wset else "  [仅读/默认可写]"))
        if wr:
            ui.info(f"显式可写根: {len(wr)} 个 (仅在写边界开启时生效)")
        return
    ui.success(authorize_extra_dir(agent.ctx, rest, writable=writable))


def _cmd_web(agent: Any, arg: str) -> None:
    """/web 启动本地 Web 工作台; /web <URL> 或 /web search <关键词> 快捷联网。"""
    if not arg:
        _launch_web_workbench(agent)
        return
    from ..tools.web import web_search, web_fetch
    parts = arg.strip().split(None, 1)
    if parts and parts[0].lower() == "search" and len(parts) > 1:
        ui.answer_md(web_search(agent.ctx, parts[1]))
    else:
        ui.answer_md(web_fetch(agent.ctx, arg.strip()))


def _launch_web_workbench(agent: Any) -> None:
    """在后台线程启动本地 Web 工作台 (不阻塞 TUI), 打印访问地址。"""
    import socket
    import threading

    from ..app import build_kernel
    from ..web import WebServer

    def _pick_port(start: int = 8090) -> int:
        for port in range(start, start + 20):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    continue
        return start

    try:
        kernel = getattr(agent, "kernel", None)
        own_kernel = False
        if kernel is None:
            kernel = build_kernel()
            own_kernel = True
        workspace = getattr(getattr(agent, "ctx", None), "workspace", "") or "."
        config = getattr(agent, "config", None)
        provider = config.get("model.provider", "unknown") if config is not None else "unknown"
        model = config.get("model.model", "unknown") if config is not None else "unknown"
        port = _pick_port()
        server = WebServer(kernel, workspace, port=port,
                           model_label=f"{provider}/{model}",
                           engine_label="tuan_cli (TUI 内嵌)")
        server.set_agent_factory(lambda: agent)
        ui.success(f"Web 工作台启动中: http://127.0.0.1:{port}")
        ui.info(f"工作区: {workspace}  ·  会话将复用当前 Agent")

        def _banner(url: str, ws: str, mdl: str) -> None:
            # TUI 内桥接后进入界面; 独立 CLI (tuan web) 不受影响
            ui.success(f"Web 工作台已启动: {url}")
            ui.info(f"工作区: {ws}  ·  模型: {mdl}")

        threading.Thread(
            target=lambda: server.serve_forever(banner=_banner), daemon=True
        ).start()
    except Exception as exc:  # noqa: BLE001
        ui.error(f"Web 工作台启动失败: {exc}")


def _cmd_code(agent: Any, arg: str, config: Any, workspace: str) -> None:
    """/code <任务> — 代码感知问答: ContextForge 检索工作区后带上下文执行。"""
    from ..codedev import CodeDevEngine

    if not arg:
        ui.info("用法: /code <任务> — 例如  /code 给检索模块加缓存")
        return
    ui.info("[代码检索] 正在扫描工作区符号…")
    try:
        engine = CodeDevEngine(workspace=workspace or ".")
        res = engine.forge_context(arg, top_k=8)
    except Exception as exc:  # noqa: BLE001
        ui.error(f"代码检索失败: {exc}")
        return
    if not res.hits:
        ui.info("(未命中相关符号, 直接执行)")
        from . import commands as _cmds
        _cmds._run_turn(agent, arg, config)
        return
    ui.info(f"命中 {len(res.hits)} 个符号 ({res.files_scanned} 文件 / {res.symbols_indexed} 符号, "
            f"{res.elapsed_ms:.0f}ms):")
    for i, h in enumerate(res.hits, 1):
        ui.info(f"  [{i}] {h.symbol.kind} {h.symbol.name}  @ {h.symbol.file}:{h.symbol.start}  "
                f"(score {h.score:.1f})")
    prompt = (res.pack()
              + "\n\n用户任务: " + arg
              + "\n请优先依据以上代码上下文完成任务; 涉及修改时先读文件再改。")
    from . import commands as _cmds
    _cmds._run_turn(agent, prompt, config)


def _cmd_commands(agent: Any, arg: str, config: Any, workspace: str) -> None:
    """/commands — 热插拔命令管理: list / reload / enable <名> / disable <名>。"""
    from . import user_commands as uc

    parts = arg.strip().split(None, 1)
    sub = parts[0].lower() if parts else "list"
    rest = parts[1] if len(parts) > 1 else ""

    if sub == "list":
        items = uc.describe_commands()
        if not items:
            ui.info("(当前无自定义命令; 在 <TUAN_HOME>/commands 或 <工作区>/.tuan/commands 放 .md/.py 即可热插拔)")
            return
        ui.info(f"自定义命令 {len(items)} 条 (运行期可热插拔):")
        for it in items:
            flag = "开" if it["enabled"] else "停"
            kind = "py" if it["kind"] == "py" else "md"
            hint = f" [{it['argument_hint']}]" if it["argument_hint"] else ""
            ui.info(f"  /{it['name']:<16} [{flag}/{kind}]{hint}  {it['description']}")
        return

    if sub == "reload":
        n = uc.reload_user_commands(config, workspace)
        ui.success(f"命令表已重载, 当前 {n} 条 (新增/修改立即生效)")
        return

    if sub in ("enable", "disable") and rest:
        name = rest.strip()
        prev = uc.describe_commands()
        if not any(c["name"] == name for c in prev):
            ui.error(f"命令 /{name} 不存在 (先 /commands list)")
            return
        state = uc.set_command_enabled(name, sub == "enable")
        if state is None:
            ui.error(f"命令 /{name} 不存在 (先 /commands list)")
            return
        ui.success(f"/{name} 已{'启用' if state else '停用'} (不重启 TUI, 立即生效)")
        return

    ui.info("用法: /commands list | reload | enable <名> | disable <名>")


def _cmd_subagent(agent: Any, arg: str) -> None:
    """/subagent <目标> — 派发隔离子代理执行任务。"""
    from ..tools.subagent_tool import _run_subagent
    if not arg:
        ui.info("用法: /subagent <目标> — 派发隔离子代理执行并回收摘要")
        return
    ui.info("[子代理] 已派出, 独立上下文执行中…")
    ui.answer_md(_run_subagent(agent.ctx, arg.strip()))


def _cmd_workflow(agent: Any, arg: str) -> None:
    """/workflow — 动态并行工作流管理 (list/status <wf> /result <wf> /cancel <wf> /retry <wf>)。"""
    from ..core.dynamic_workflow import get_engine, close_engines
    from ..config import home_dir

    eng = get_engine(home_dir())
    eng.configure(
        kernel=getattr(agent, "kernel", None),  # type: ignore[arg-type]
        config=agent.config if hasattr(agent, "config") else None,  # type: ignore[arg-type]
        workspace=getattr(getattr(agent, "ctx", None), "workspace", "") or "",
        main_agent=agent,
    )
    parts = arg.strip().split(None, 1)
    sub = parts[0].lower() if parts else "list"
    rest = parts[1] if len(parts) > 1 else ""

    # 编排模式: authoring (文档/PRD 编写) 与 deep-research (深度研究)。
    # 对齐 Claude Code /workflow-authoring 与 /deep-research 的编排语义。
    if sub in ("authoring", "write", "doc"):
        if not rest:
            ui.info("用法: /workflow authoring <主题>  — 编排文档/PRD 编写工作流")
            return
        _workflow_authoring(agent, eng, rest)
        return
    if sub in ("deep-research", "research", "dr"):
        if not rest:
            ui.info("用法: /workflow deep-research <主题>  — 编排深度研究工作流")
            return
        _workflow_deep_research(agent, eng, rest)
        return

    if sub == "list":
        items = eng.list()
        if not items:
            ui.info("(暂无工作流)")
            return
        ui.info(f"工作流共 {len(items)} 个 (最新在前):")
        for it in items[:20]:
            ui.info(f"  {it['workflow_id']:<16} {it['status']:<9} 步骤={it['n_steps']}  {it['name']}")
        return

    if sub in ("status", "result", "cancel", "retry", "retry_failed"):
        wf_id = rest.strip()
        if not wf_id:
            ui.info(f"用法: /workflow {sub} <wf_id>")
            return
        try:
            if sub == "status":
                st = eng.status(wf_id)
                lines = [f"工作流 {st['name']} [{st['workflow_id']}] · 状态={st['status']}"
                         f" · {st['n_steps']} 步 · 并行={st['parallel']}"]
                for s in st["steps"]:
                    lines.append(f"  步骤 {s['step'] + 1}: {s['status']}"
                                 f" ({s['done_tasks']}/{s['n_tasks']})")
                ui.info("\n".join(lines))
            elif sub == "result":
                r = eng.result(wf_id)
                preview = r["summary"][:2000]
                ui.info(f"工作流 {r['name']} [{wf_id}] · 状态={r['status']} · "
                        f"成功 {r['ok_tasks']}/{r['total_done']}")
                ui.answer_md(preview or "(无输出)")
            elif sub == "cancel":
                ok = eng.cancel(wf_id)
                ui.info(f"已请求取消 {wf_id}" if ok else f"工作流 {wf_id} 已结束/正在取消")
            else:
                ok = eng.retry_failed(wf_id)
                ui.info(f"已重置失败任务并重新编排 {wf_id}" if ok
                        else f"{wf_id} 无失败任务可重试")
        except KeyError:
            ui.info(f"找不到工作流 {wf_id}")
        return

    ui.info("用法: /workflow [list|status <wf>|result <wf>|cancel <wf>|retry <wf>"
            "|authoring <主题>|deep-research <主题>]")


def _workflow_authoring(agent: Any, eng: Any, topic: str) -> None:
    """/workflow authoring <主题> —— 编排"文档/PRD 编写"工作流 (多步草稿→评审→定稿)。"""
    steps = [
        [{"title": "大纲", "role": "general-purpose",
          "prompt": f"为「{topic}」撰写结构化大纲。列出章节、每章要点与目标读者。输出纯大纲。"}],
        [{"title": "草稿", "role": "general-purpose",
          "prompt": f"基于大纲, 为「{topic}」撰写完整初稿。内容详实、结构清晰, 用 Markdown。"}],
        [{"title": "评审", "role": "general-purpose",
          "prompt": f"评审「{topic}」初稿: 找逻辑漏洞、信息缺口、表述问题, 给出改进建议清单。"}],
        [{"title": "定稿", "role": "general-purpose",
          "prompt": f"依据评审建议修订「{topic}」, 产出最终版本。保留 Markdown 结构。"}],
    ]
    wf_id = eng.create(f"authoring:{topic[:30]}", steps, parallel=False,
                       note="workflow-authoring: 草稿→评审→定稿")
    ui.success(f"编排写作工作流已启动: {wf_id}")
    ui.info(f"  主题: {topic[:60]}")
    ui.info("  步骤: 大纲 → 草稿 → 评审 → 定稿 (串行)")
    ui.info(f"  用 /workflow status {wf_id} 查看进度; /workflow result {wf_id} 取结果。")


def _workflow_deep_research(agent: Any, eng: Any, topic: str) -> None:
    """/workflow deep-research <主题> —— 编排"深度研究"工作流 (检索→分析→综合报告)。"""
    steps = [
        [{"title": f"检索源A", "role": "general-purpose",
          "prompt": f"针对「{topic}」做第一轮资料检索: 找权威来源、关键数据、核心论点。列出来源链接与摘要。"},
         {"title": f"检索源B", "role": "general-purpose",
          "prompt": f"针对「{topic}」做第二轮补充检索: 覆盖竞品、对比、反方观点、最新进展。"}],
        [{"title": "分析", "role": "general-purpose",
          "prompt": f"整合「{topic}」的检索材料: 交叉验证、去重、提炼关键发现与数据。输出结构化分析。"}],
        [{"title": "综合报告", "role": "general-purpose",
          "prompt": f"基于分析, 为「{topic}」产出完整研究报告: 摘要、背景、核心发现、数据图表、结论与建议。"}],
    ]
    wf_id = eng.create(f"deep-research:{topic[:30]}", steps, parallel=True,
                       note="deep-research: 双源检索→分析→综合报告")
    ui.success(f"深度研究工作流已启动: {wf_id}")
    ui.info(f"  主题: {topic[:60]}")
    ui.info("  步骤: [检索A∥检索B] → 分析 → 综合报告 (检索并行)")
    ui.info(f"  用 /workflow status {wf_id} 查看进度; /workflow result {wf_id} 取结果。")


def _cmd_verify(workspace: str, arg: str, agent: Any, config: Any) -> None:
    """/verify — 编码验证闭环。"""
    from ..core.verify_loop import (
        VerifyConfig, VerifyReport, verify_once, verify_with_heal,
    )
    cfg = VerifyConfig.from_dict({"verify": config.get("verify", {})})
    mode = "heal"
    argl = arg.strip().lower()
    # 支持 --fix/-f 标志 (自修复增强) 与 check/heal 子命令。
    if argl in ("check", "once", "run"):
        mode = "check"
    elif argl in ("heal", "fix", "--fix", "-f"):
        mode = "heal"
    ui.info(f"  模式: {mode} | 项目类型: {_detect_project_type(workspace)}")
    ui.info("")
    if mode == "check":
        rnd = verify_once(
            workspace, cfg,
            kernel=getattr(agent, "kernel", None),
            confirm=getattr(getattr(agent, "ctx", None), "confirm", None),
        )
        rnd.round_num = 1
        ui.info(rnd.summary())
    else:
        def _heal_fn(error_text: str) -> str:
            ui.info("  [自修复] 正在分析错误并修复…")
            prompt = (
                f"编码验证失败, 请分析以下错误并修复代码。只修复报错的文件, 不要改其他东西。\n\n"
                f"{error_text}\n\n修复后不要跑测试, 我会自动再验证。"
            )
            result = agent.run(prompt, stream=False)
            return result or ""
        report = verify_with_heal(
            workspace, cfg, heal_fn=_heal_fn,
            kernel=getattr(agent, "kernel", None),
            confirm=getattr(getattr(agent, "ctx", None), "confirm", None),
        )
        ui.info(report.summary())


def _cmd_personality(agent: Any, config: Any, arg: str) -> None:
    """/personality — 人设管理 (list/show/set/auto)。"""
    from ..core.personality import (
        PERSONALITY_NAMES, list_personalities, get_personality_info,
        render_personality_block, resolve_personality, _validate_or_default,
    )
    sub = arg.strip().lower()
    memory_store = agent.kernel.get("memory_store")

    if sub in ("", "list"):
        current = resolve_personality(config, memory_store)
        ui.info("── 人设列表 ──")
        ui.info(f"  当前: {current}")
        for p in list_personalities():
            marker = " ★" if p["name"] == current else ""
            ui.info(f"  {p['name']:<6} ({p['key']:<14}) {p['tagline']}{marker}")
        ui.info("")
        ui.info("  用法: /personality set <人设名> | /personality show | /personality auto")
        return

    if sub == "show":
        current = resolve_personality(config, memory_store)
        info = get_personality_info(current)
        ui.info(f"── 当前人设: {info['name']} ({info['key']}) ──")
        ui.info(f"  定位: {info['tagline']}")
        ui.info(f"  语气: {', '.join(info['tone'])}")
        ui.info(f"  行为: {'; '.join(info['behaviors'])}")
        ui.info(f"  口头禅: {'; '.join(info['catchphrases'])}")
        return

    if sub.startswith("set "):
        name = arg.strip()[4:].strip()
        if not name:
            ui.info("用法: /personality set <人设名>")
            ui.info(f"可选值: {'/'.join(PERSONALITY_NAMES)}")
            return
        validated = _validate_or_default(name)
        if validated != name:
            ui.info(f"⚠ 已映射为: {validated}")
        if memory_store is None:
            ui.info("✗ 无法获取记忆存储")
            return
        memory_store.update_user("人设", validated)
        ui.info(f"✓ 人设已设置为: {validated}")
        ui.info(f"  下次会话生效 (提示词将在新对话中重建)")
        return

    if sub == "auto":
        if memory_store is None:
            ui.info("✗ 无法获取记忆存储")
            return
        memory_store.update_user("人设", "")
        current = resolve_personality(config, memory_store)
        ui.info(f"✓ 已恢复自动分配, 当前人设: {current}")
        return

    ui.info("用法: /personality [list|show|set <人设名>|auto]")


def _detect_project_type(workspace: str) -> str:
    from ..core.verify_loop import detect_project_type
    return detect_project_type(workspace)


def _cmd_log(agent: Any, arg: str) -> None:
    """/log [N] — 展示最近 N 条工具调用历史。"""
    from datetime import datetime
    n = 15
    if arg.strip():
        try:
            n = int(arg.strip())
        except ValueError:
            n = 15
    session = agent.session
    if session is None or not session.file.exists():
        ui.info("  暂无工具调用记录。")
        return
    tool_events = []
    try:
        with open(session.file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if rec.get("type") == "tool_call":
                    tool_events.append(rec)
    except Exception:  # noqa: BLE001
        ui.info("  暂无工具调用记录。")
        return
    if not tool_events:
        ui.info("  暂无工具调用记录。")
        return
    recent = tool_events[-n:]
    ui.info("")
    ui.info(f"  === 最近 {len(recent)} 条工具调用 ===")
    ui.info("")
    for ev in recent:
        ts = datetime.fromtimestamp(ev.get("ts", 0)).strftime("%H:%M:%S")
        name = ev.get("name", "?")
        args_str = ev.get("arguments", "")
        if len(args_str) > 120:
            args_str = args_str[:117] + "..."
        ui.info(f"    {ts} {name}")
        if args_str:
            ui.info(f"           {args_str}")


def _cmd_mcp_tools(agent: Any, arg: str) -> None:
    """/mcp-tools — MCP Tool Search 上下文降耗 (报告 / on / off / search)。

    支持:
      /mcp-tools            查看上下文占用报告
      /mcp-tools on|off     强制启用/禁用搜索模式 (运行时热切换)
      /mcp-tools search <q> 在当前 MCP 工具目录里检索并回显命中 schema
    """
    engine = None
    try:
        engine = agent.kernel.get("mcp_tool_search") if agent.kernel else None
    except Exception:  # noqa: BLE001
        engine = None
    if engine is None:
        ui.warn("MCP Tool Search 引擎未启用 (无 MCP 工具接入, 或 mcp.tool_search.enabled=false)")
        return
    head, _, rest = arg.strip().partition(" ")
    if arg and head in ("on", "enable"):
        engine.enabled = True
        ui.success("MCP Tool Search 已强制启用 (下一轮生效)")
        return
    if arg and head in ("off", "disable"):
        engine.enabled = False
        ui.success("MCP Tool Search 已禁用 (下一轮生效)")
        return
    if head == "search":
        q = rest or "list tools"
        hits = engine.search(q)
        if not hits:
            ui.info("未命中任何 MCP 工具。")
            return
        ui.info(f" 关键词 '{q}' 命中 {len(hits)} 个工具:")
        for s in hits:
            fn = s["function"]
            ui.info(f"  - {fn['name']}: {fn.get('description', '')[:70]}")
        return
    rep = engine.context_report()
    ui.info("MCP Tool Search 上下文占用:")
    ui.info(f"  模式: {rep['mode']} (搜索降耗 vs 全量内联)")
    ui.info(f"  已接入 MCP 工具: {rep['mcp_tools']} 个")
    ui.info(f"  MCP schema 占用: {rep['mcp_tokens']:,} tokens 约 {rep['utilization']:.1%}")
    ui.info(f"  上下文窗口: {rep['context_window']:,} · 阈值: {rep['threshold']:.0%}")
    ui.info(f"  累计检索 {rep['search_calls']} 次")
    ui.info("  切换: /mcp-tools on|off · 检索: /mcp-tools search <关键词>")


def _cmd_language(agent: Any, config: Any, arg: str) -> None:
    """/language: 查看或切换界面语言 (运行时生效, 写入 config)。

    无参列出可用语言; 传代码 (如 /language en) 立即切换并持久化。
    依赖 i18n 的运行时 set_language, 不重启即可让后续取词用新语言。
    """
    from ..i18n import (
        available_languages, get_language, normalize_language, set_language,
    )

    codes = list(available_languages())
    current = get_language()
    target = arg.strip()
    if not target:
        ui.info(f"  当前语言: {current} ({available_languages().get(current, {}).get('native', '')})")
        ui.info("  可用语言:")
        for code in codes:
            info = available_languages().get(code, {})
            marker = " ✓" if code == current else ""
            ui.info(f"    {code:<8} {info.get('native', ''):<20} ({info.get('english', '')}){marker}")
        ui.info("  用法: /language <代码> 立即切换并写入配置")
        return
    normalized = normalize_language(target)
    if not normalized:
        ui.error(f"无法识别语言: {target} (可用: {', '.join(codes)})")
        return
    applied = set_language(normalized)
    # 持久化: config 有 set_user 就写 (测试/桩可能没有)
    try:
        if config is not None and hasattr(config, "set_user"):
            config.set_user("language", applied)
    except Exception:  # noqa: BLE001
        pass
    info = available_languages().get(applied, {})
    ui.success(f"界面语言已切换为: {applied} ({info.get('native', '')})")


def _handle_slash(cmd: str, agent: Any, config: Any, workspace: str) -> bool:
    """处理斜杠命令。返回 True 表示已处理。"""
    parts = cmd.strip().split(None, 1)
    head = parts[0].lower() if parts else ""
    arg = parts[1] if len(parts) > 1 else ""

    if head == "/help":
        # 增强帮助: /help 分类列出; /help <命令> 详细用法; /help keyboard 快捷键
        try:
            from .cmd_help import categorized_help_text, help_for_command
            if arg.strip():
                ui.info(help_for_command(arg.strip()))
            else:
                ui.info(categorized_help_text())
        except Exception:  # noqa: BLE001 - 回退到静态帮助文本
            ui.info(_HELP)
    elif head == "/tools":
        tools = agent.registry.tools
        for tool in tools:
            ui.info(f"  {tool.name}: {tool.description[:60]}")
    elif head == "/skills":
        manager = agent.kernel.get("skill_manager")
        if manager:
            sub = arg.strip().lower()
            if sub in ("audit", ""):
                from ..skills.governance import audit
                rows = audit(manager)
                ui.info(f"技能审计: 共 {len(rows)} 个")
                for r in rows:
                    flags = []
                    if r.is_zombie:
                        flags.append("僵尸")
                    if r.incomplete:
                        flags.append("元数据不全")
                    tag = f" [{','.join(flags)}]" if flags else ""
                    ui.info(f"  {r.slug} ({r.origin}) use={r.use_count}"
                            f" 闲置{r.days_idle:.0f}天{tag}")
            elif sub == "consolidate":
                from ..skills.governance import consolidate
                props = consolidate(manager, dry_run=True)
                if not props:
                    ui.info("未发现相似技能对 (dry-run)")
                for pr in props:
                    ui.info(f"  相似度{pr.score}: 保留 {pr.keeper.slug} <- 并入 {pr.loser.slug}")
            else:
                for s in manager.list_all():
                    ui.info(f"  {s.ui_name} ({s.origin}): {(s.short_description or s.description)[:50]}")
    elif head == "/distill":
        svc = agent.kernel.get("self_improve")
        if svc is not None and hasattr(svc, "distill"):
            ui.info(f"蒸馏完成: {svc.distill()}")
        else:
            ui.info("蒸馏服务不可用 (self_improve 未启用)")
    elif head == "/memory":
        _cmd_memory(agent, config, arg)
    elif head == "/usage":
        ui.usage(agent.total_usage)
    elif head == "/cost":
        usage = agent.total_usage
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        hit = usage.get("prompt_cache_hit_tokens", 0)
        miss = usage.get("prompt_cache_miss_tokens", 0)
        ui.info(f"  prompt: {prompt:,} tokens")
        ui.info(f"  completion: {completion:,} tokens")
        if hit or miss:
            ui.info(f"  缓存: 命中 {hit:,} / 未命中 {miss:,}")
            rate = agent.cache_hit_rate()
            if rate is not None:
                ui.info(f"  缓存命中率: {rate:.1%}")
        from ..models.router import estimate_cost
        cost = estimate_cost(config.get("model.provider", ""),
                             config.get("model.model", ""), prompt, completion)
        ui.info(f"  估算成本: ${cost:.4f}")
    elif head == "/compact":
        before = agent.context_stats()["estimated_tokens"]
        dropped = agent.compact()
        after = agent.context_stats()["estimated_tokens"]
        ui.success(f"已压缩: 折叠 {dropped} 条历史, {before:,} -> {after:,} tokens")
    elif head == "/context":
        st = agent.context_stats()
        ui.context_bar(st)
        ui.info(f"  预算: {st.get('budget_tokens', '?')} tokens")
        ui.info(f"  已用: {st.get('estimated_tokens', '?')} tokens")
    elif head in ("/clear", "/new"):
        # OpenCode: /new 是 /clear 的别名 (开新会话, 清空上下文)
        agent.messages.clear()
        ui.info("上下文已清空。")
    elif head == "/more":
        ui.show_more()
    elif head == "/model":
        if arg:
            parts2 = arg.split()
            if parts2 and parts2[0] == "switch":
                from ..models.plugin import ModelPlugin
                ModelPlugin.switch_model(agent.kernel, {
                    k: v for k, v in zip(
                        ["provider", "model", "base_url", "api_key_env"],
                        parts2[1:]
                    )
                })
                config.set_user("router.auto_switch", False)
                ui.success("模型已切换 (自动路由本会话已暂停, 尊重你的选择)。")
            elif parts2 and parts2[0] == "auto":
                on = (parts2[1] in ("on", "1", "true", "yes")) if len(parts2) > 1 else True
                config.set_user("router.auto_switch", bool(on))
                ui.success(f"自动路由: {'开启' if on else '关闭'}")
            else:
                ui.info(f"  provider: {config.get('model.provider')}")
                ui.info(f"  model: {config.get('model.model')}")
                ui.info(f"  自动路由: {'开启' if config.get('router.auto_switch', True) else '关闭'}")
        else:
            ui.info(f"  provider: {config.get('model.provider')}")
            ui.info(f"  model: {config.get('model.model')}")
            ui.info(f"  自动路由: {'开启' if config.get('router.auto_switch', True) else '关闭'}")
    elif head == "/effort":
        if arg:
            from .cmd_chat import clamp_effort
            clamped = clamp_effort(config, arg.strip())
            if clamped is None:
                ui.error(f"非法档位: {arg.strip()} (可选 low/medium/high/xhigh/max)")
            elif clamped != arg.strip().lower():
                ui.warn(f"档位 {arg.strip()} 超过上限 {clamped}, 已截断")
                config.set_user("agent.effort", clamped)
                ui.success(f"推理投入: {clamped} (受 maxEffortLevel 上限)")
            else:
                config.set_user("agent.effort", arg.strip())
                ui.success(f"推理投入: {arg.strip()}")
        else:
            ui.info(f"  当前: {config.get('agent.effort', 'high')}"
                    f" (上限: {config.get('agent.max_effort_level', 'max')})")
    elif head == "/mode":
        from ..modes.switcher import switch_mode, current_mode
        from ..modes.registry import MODE_IDS, MODE_NAMES, MODE_LEVELS, MODE_RISK, get_mode_meta
        from ..modes.policy import get_mode_policy

        cur = current_mode()
        if not arg:
            meta = get_mode_meta(cur)
            policy = get_mode_policy(cur)
            ui.info(f"  当前: {meta['name']} ({cur}) · {meta['level']} · 风险: {meta['risk']}")
            ui.info(f"  可用: /mode <id> 切换 | /mode list 列出全部 | /mode show 查看详情")
            for mid in MODE_IDS:
                m = get_mode_meta(mid)
                marker = " ✓" if mid == cur else ""
                ui.info(f"    {m['name']:　<4} ({mid:15}) {m['level']:2} 风险:{m['risk']}{marker}")
        elif arg.lower() == "list":
            for mid in MODE_IDS:
                m = get_mode_meta(mid)
                marker = " ✓" if mid == cur else ""
                ui.info(f"  {m['name']:　<4} ({mid:15}) {m['level']:2} 风险:{m['risk']}{marker}")
        elif arg.lower() == "show":
            meta = get_mode_meta(cur)
            policy = get_mode_policy(cur)
            ui.info(f"  模式: {meta['name']} ({cur})")
            ui.info(f"  权限: {meta['level']} · 风险: {meta['risk']}")
            ui.info(f"  描述: {meta.get('description', '')}")
            ui.info(f"  Shell:  {'允许' if policy.shell_allowed() else '禁用'}")
            ui.info(f"  MCP:    {'允许' if policy.mcp_allowed() else '禁用'}")
            ui.info(f"  网络:   {'允许' if policy.network_allowed() else '禁用'}")
            ui.info(f"  文件:   {'允许' if policy.file_write_allowed() else '禁用'}")
            ui.info(f"  记忆:   {'允许' if policy.memory_write_allowed() else '禁用'}")
            ui.info(f"  TTS:    {'允许' if policy.tts_allowed() else '禁用'}")
            ui.info(f"  工具白名单: {len(policy.tool_allowlist())} 个工具")
        else:
            ok, reason = switch_mode(arg, force=True)
            if ok:
                new_id = current_mode()
                new_meta = get_mode_meta(new_id)
                ui.success(f"已切换到: {new_meta['name']} ({new_id})")
                # 旧三档别名提示: 用户敲 standard/yolo/plan 时明确告知映射到哪一档,
                # 否则「我明明输了 standard, 怎么显示的是协作模式」会让人以为切错了。
                try:
                    from ..modes.registry import MODE_ALIASES
                    canonical = MODE_ALIASES.get(arg.strip().lower())
                except Exception:  # noqa: BLE001
                    canonical = None
                if canonical:
                    ui.info(f"  「{arg.strip()}」是旧档别名, 对应新档「{canonical}」")
                ui.info(f"  {reason}")
            else:
                ui.warning(f"切换失败: {reason}")
    elif head == "/plan":
        arg_l = arg.strip().lower()
        if arg_l in ("on", "1", "true", "yes"):
            agent.plan_mode = True
            agent.ctx.plan_mode = True
            ui.success("Plan 模式已开启: 只读分析, 修改类工具将被拦截。")
        elif arg_l in ("off", "0", "false", "no"):
            agent.plan_mode = False
            agent.ctx.plan_mode = False
            ui.success("Plan 模式已关闭: 可以正常执行修改操作。")
        else:
            agent.plan_mode = not agent.plan_mode
            agent.ctx.plan_mode = agent.plan_mode
            if agent.plan_mode:
                ui.success("Plan 模式已开启: 只读分析, 修改类工具将被拦截。")
            else:
                ui.success("Plan 模式已关闭: 可以正常执行修改操作。")
    elif head == "/provider":
        _cmd_provider(agent, config, head, arg)
    elif head == "/language":
        _cmd_language(agent, config, arg)
    elif head == "/goal":
        _cmd_goal(agent, arg)
    elif head == "/blast":
        _cmd_blast(agent, arg)
    elif head == "/sandbox":
        _cmd_sandbox(agent, arg)
    elif head == "/offline":
        _cmd_offline(agent, arg)
    elif head == "/audit":
        _cmd_audit(agent, arg)
    elif head == "/resume":
        if arg:
            from .cmd_chat import _resume_session
            name = _resume_session(agent, arg)
            if name:
                ui.success(t("chat.resumed", path=name, count=len(agent.messages)))
        else:
            from .cmd_chat import _list_sessions
            _list_sessions(agent)
    elif head == "/session":
        # CodeX 风格会话管理: 无参列出历史会话, 带参恢复 (复用 /resume 语义)。
        if arg:
            from .cmd_chat import _resume_session
            name = _resume_session(agent, arg)
            if name:
                ui.success(t("chat.resumed", path=name, count=len(agent.messages)))
        else:
            from .cmd_chat import _list_sessions
            _list_sessions(agent)
    elif head == "/swarm":
        if not arg:
            ui.info("用法: /swarm <目标>  — 多 Agent 协作 (强模型规划 -> 弱模型并发执行 -> 强模型验收)")
            return True
        from ..core.swarm import Swarm
        ui.info("[多 Agent 协作] 强模型规划中…")
        swarm = Swarm(
            kernel=agent.kernel, config=config, workspace=workspace,
            main_agent=agent, confirm=agent.ctx.confirm,
        )
        collab = swarm.run(arg)
        ui.answer_md(collab.to_report())
        agent.messages.append({
            "role": "user",
            "content": f"(多 Agent 协作已完成, 目标: {arg[:60]})\n{collab.accepted[:1200]}",
        })
    elif head == "/route":
        from ..models.router import ModelRouter
        router = ModelRouter(
            default_provider=config.get("model.provider", "deepseek"),
            default_model=config.get("model.model", ""),
            budget_limit=config.get("router.budget_limit", 0.0),
        )
        auto = bool(config.get("router.enabled", False)) and bool(config.get("router.auto_switch", True))
        if not arg:
            ui.info("  用法: /route <任务描述> — 估算难度并建议/自动路由模型")
            ui.info(f"  自动路由: {'已开启 (本回合按难度自动切换)' if auto else '未开启 (仅咨询建议)'}")
        else:
            d = router.decide(
                arg,
                current_provider=config.get("model.provider"),
                current_model=config.get("model.model"),
                available_providers=ModelRouter.available_provider_names(),
            )
            ui.info(f"  难度评估: {d['difficulty']}/10")
            ui.info(f"  建议模型: {d['provider']}/{d['model']}")
            ui.info(f"  理由: {d['reason']}")
            if auto:
                ui.info(f"  自动路由: {'本回合将切换' if d['switch'] else '本回合保持当前模型'}")
            else:
                ui.info("  自动路由未开启, 仅建议不切换 (用 /model auto on 开启)")
    elif head == "/diff":
        from .cmd_agents import _cmd_diff
        _cmd_diff(workspace, arg)
    elif head == "/undo":
        from .cmd_agents import _cmd_undo
        _cmd_undo(workspace, arg, agent)
    elif head == "/log":
        _cmd_log(agent, arg)
    elif head == "/impact":
        from .cmd_agents import _cmd_impact
        _cmd_impact(workspace, arg, agent)
    elif head == "/mcp":
        _cmd_mcp(agent, arg)
    elif head == "/mcp-tools":
        _cmd_mcp_tools(agent, arg)
    elif head == "/hooks":
        from .cmd_services import _cmd_hooks
        _cmd_hooks(agent, arg)
    elif head in ("/image", "/images", "/clear-images"):
        _cmd_image(agent, head, arg)
    elif head == "/permissions":
        _cmd_permissions(config, arg)
    elif head == "/status":
        _cmd_status(agent, config)
    elif head == "/stats":
        _cmd_stats(agent, config)
    elif head == "/budget":
        _cmd_budget(agent, config, arg)
    elif head == "/checkpoint":
        _cmd_checkpoint(agent, arg)
    elif head == "/add-dir":
        _cmd_add_dir(agent, arg)
    elif head == "/web":
        _cmd_web(agent, arg)
    elif head == "/commands":
        _cmd_commands(agent, arg, config, workspace)
    elif head == "/code":
        _cmd_code(agent, arg, config, workspace)
    elif head == "/rewind":
        _boundary_rewind(agent, arg, workspace)
    elif head == "/handoff":
        _boundary_handoff(agent, config, workspace)
    elif head == "/worktree":
        _boundary_worktree(agent, arg, workspace)
    elif head == "/subagent":
        _cmd_subagent_enhanced(agent, arg)
    elif head == "/superagent":
        _cmd_superagent(agent, arg)
    elif head in ("/workflow", "/workflow-authoring", "/deep-research"):
        # /workflow-authoring <主题> 与 /deep-research <主题> 是 /workflow 编排模式的别名。
        if head == "/workflow-authoring":
            arg = f"authoring {arg}".strip()
        elif head == "/deep-research":
            arg = f"deep-research {arg}".strip()
        _cmd_workflow(agent, arg)
    elif head == "/verify":
        _cmd_verify(workspace, arg, agent, config)
    elif head == "/export":
        _cmd_export(agent, arg)
    elif head == "/import":
        _cmd_import(agent, arg)
    elif head == "/gh-borrow":
        from .cmd_gh import run_borrow_for_slash
        out = run_borrow_for_slash(arg or "", mode="code", limit=5)
        ui.info(out)
    elif head == "/init":
        from .cmd_slash_init import _cmd_init
        _cmd_init(agent, arg, config, workspace)
    elif head == "/personality":
        _cmd_personality(agent, config, arg)
    elif head == "/fork":
        cmd_fork(agent, arg)
    elif head == "/branch":
        cmd_branch(agent, arg)
    elif head == "/cd":
        cmd_cd(agent, arg)
    elif head == "/btw":
        cmd_btw(agent, arg)
    elif head == "/copy":
        cmd_copy(agent, arg)
    elif head == "/tasks":
        cmd_tasks(agent, arg)
    elif head in ("/background", "/bg"):
        cmd_background(agent, arg)
    elif head == "/theme":
        cmd_theme(agent, arg)
    elif head == "/color":
        cmd_color(agent, arg)
    elif head == "/loop":
        cmd_loop(agent, arg)
    elif head == "/review":
        cmd_review(agent, arg)
    elif head == "/code-review":
        cmd_review(agent, arg)
    elif head == "/security-review":
        cmd_review(agent, arg, security=True)
    elif head == "/simplify":
        cmd_simplify(agent, arg)
    elif head == "/debug":
        cmd_debug(agent, arg)
    elif head == "/doctor":
        # /doctor [--fix] — 修复型 setup checkup (对齐 Claude Code doctor)
        from .cmd_doctor import run_checks, _render_rich
        from pathlib import Path as _Path
        fix = "--fix" in arg.split() or "-f" in arg.split()
        network = "--network" in arg.split() or "-n" in arg.split()
        ws = getattr(getattr(agent, "ctx", None), "workspace", "") or workspace or ""
        ui.info(f"[doctor] 诊断中 (fix={fix})…")
        findings = run_checks(_Path(ws) if ws else None, fix=fix, network=network)
        _render_rich(findings)
        if fix:
            ui.info("  (--fix: 已尝试自动修复可修复项, 请用 /undo 回滚或手动复核。)")
    elif head == "/batch":
        cmd_batch(agent, arg)
    elif head == "/dataviz":
        cmd_dataviz(agent, arg)
    elif head == "/design":
        cmd_design(agent, arg)
    elif head == "/artifacts":
        cmd_artifacts(agent, arg)
    elif head == "/auto-mode-setup":
        cmd_auto_mode_setup(agent, arg)
    elif head == "/config":
        cmd_config_slash(agent, arg)
    elif head in ("/exit", "/quit"):
        return False
    else:
        ui.info(f"未知命令: {head} (输入 /help 查看可用命令)")
    return True
