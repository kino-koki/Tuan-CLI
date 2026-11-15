"""会话与工作区命令: codedev / undo / improve / 会话 / 用户命令 / 命名 agents / rewind / diff / 项目 / chat / worktree / plan。

从 `parser_commands.py` 拆出的 `register_subcommands` 分片, 行为不变。
"""

from __future__ import annotations

import argparse
from typing import Any
def register_session_workspace(sub: Any) -> None:
    """注册 session_workspace 域子命令。"""

    # ---- dev codedev 子命令组 (原顶级 `tuan codedev`, 已并入 dev) ----
    # dev 的 task 是自由文本位置参数, 无法在其 parser 上直接挂 argparse subparsers
    # (否则任意任务首词会被当成子命令而报 invalid choice)。这里注册一个隐藏顶层
    # 解析器承载 codedev 的子命令与参数; main() 会把 `dev codedev ...` 透明改写过来,
    # 对用户而言仍是 `tuan dev codedev demo|doctor|retrieve|verify`。
    pcd = sub.add_parser("__dev_codedev", help=argparse.SUPPRESS)
    cdsub = pcd.add_subparsers(dest="codedev_cmd", required=True)
    cdsub.add_parser("demo", help="造一个临时项目, 端到端演示检索/验证/分解/编排")
    cdsub.add_parser("doctor", help="检查子系统健康度 (索引/检测器/编排可用性)")
    cp = cdsub.add_parser("retrieve", help="对给定任务在项目里检索相关代码上下文")
    cp.add_argument("task", help="自然语言任务 (支持中文)")
    cp.add_argument("--root", default=".", help="待检索的项目根目录")
    cp.add_argument("--top-k", type=int, default=8, help="返回的相关符号数")
    cv = cdsub.add_parser("verify", help="在给定目录运行验证闸门 (build/test/lint)")
    cv.add_argument("--cwd", default=".", help="运行目录")
    cix = cdsub.add_parser("index", help="只读体检已落盘的 code_index.json (第 118 个独特功能)")
    cix.add_argument("--root", default=".", help="项目根目录 (含 .tuan/code_index.json)")
    cix.add_argument("--json", action="store_true", help="输出 JSON")
    pcd.set_defaults(func="cmd_codedev")

    p = sub.add_parser(
        "undo", help="事务化精确回滚 (账本持久化于 .tuan/ledger, 可跨进程)"
    )
    p.add_argument(
        "target", nargs="?", default="", help="可选: N(步数) / <file> / all / --safe"
    )
    p.add_argument(
        "--impact",
        action="store_true",
        help="只展示操作账本与影响半径 (原 `tuan impact`), 不执行回滚",
    )
    p.set_defaults(func="cmd_undo")

    p = sub.add_parser("improve", help="自我改进闭环: 从执行历史提炼规则与技能草稿")
    impsub = p.add_subparsers(dest="improve_cmd", required=True)
    impsub.add_parser(
        "summarize", help="复盘执行历史, 预览将生成的经验与规则 (dry-run)"
    ).set_defaults(func="cmd_improve")
    impsub.add_parser(
        "apply", help="把经验固化为 rules .jsonl + 技能草稿并落盘"
    ).set_defaults(func="cmd_improve")
    imp_r = impsub.add_parser(
        "rules", help="只读体检已落盘的 learned 规则 (self_improve.jsonl, 第 117 个独特功能)"
    )
    imp_r.add_argument("--json", action="store_true", help="输出 JSON")
    imp_r.set_defaults(func="cmd_improve")

    p = sub.add_parser("session", help="会话管理 (列出/恢复/删除/导出/清理/统计)")
    sesub = p.add_subparsers(dest="session_cmd", required=True)
    sl = sesub.add_parser("list", help="列出最近的会话")
    sl.add_argument("--all", action="store_true", help="列出全部会话")
    sl.add_argument("--limit", type=int, default=10, help="显示数量 (默认 10)")
    r = sesub.add_parser("resume", help="恢复会话 (默认最近一个)")
    r.add_argument("target", nargs="?", help="会话序号或文件名 (省略则恢复最近)")
    d = sesub.add_parser("delete", help="删除会话 (按编号/会话ID/all)")
    d.add_argument("target", nargs="?", help="会话序号或会话ID (all 清空全部)")
    d.add_argument("--yes", "-y", action="store_true", help="跳过确认")
    ex = sesub.add_parser("export", help="导出会话到文件或 stdout")
    ex.add_argument("target", nargs="?", help="会话序号或会话ID")
    ex.add_argument("-o", "--output", help="导出路径 (省略则输出到 stdout)")
    cl = sesub.add_parser("clean", help="清理过期会话 (默认 >30 天)")
    cl.add_argument(
        "--older-than", type=int, default=30, help="清理超过 N 天的会话 (默认 30)"
    )
    cl.add_argument("--yes", "-y", action="store_true", help="跳过确认")
    sesub.add_parser("stats", help="显示会话统计信息")
    # --- 跨会话 / 分叉 (迭代 3) ---
    fr = sesub.add_parser("fork", help="分叉一个会话为新分支, 复用其历史")
    fr.add_argument("target", nargs="?", help="源会话序号或会话ID (省略取最近)")
    fr.add_argument(
        "--at",
        type=int,
        default=None,
        dest="at_message",
        help="分叉到第 N 条 user/assistant 消息 (默认整份)",
    )
    fr.add_argument("--note", default="", help="为分支添加备注")
    tr = sesub.add_parser("tree", help="显示会话的分叉树 (谱系)")
    tr.add_argument("root", nargs="?", help="根会话序号或会话ID (省略取最近根)")
    rf = sesub.add_parser("ref", help="把 @session / @# 引用展开为内容")
    rf.add_argument("text", nargs="+", help="含引用的文本 (如 '参考 @session:<id>')")
    # 跨会话差异对比 (第 77 个独特功能: CrossSessionResolver.compare)
    cp = sesub.add_parser("compare", help="跨会话差异对比 (事件/工具/元数据)")
    cp.add_argument("session_a", help="会话 A (ID 或前缀)")
    cp.add_argument("session_b", help="会话 B (ID 或前缀)")
    cp.add_argument("--json", action="store_true", help="输出 JSON")
    # --- 第 103 个独特功能: 跨会话指标聚合趋势 (Trajectory.metrics 横向对比) ---
    trn = sesub.add_parser(
        "trend",
        help="跨会话指标聚合趋势: 工具成功率/耗时/Token/成本 横向对比 (差异化)",
    )
    trn.add_argument("--limit", type=int, default=10, help="取最近 N 个会话 (默认 10)")
    trn.add_argument("--sort", choices=["time", "success", "cost", "tokens"],
                     default="time", help="排序键 (默认 time)")
    trn.add_argument("--json", action="store_true", help="输出 JSON")
    # --- 回放 / 轨迹 (原顶级 tuan replay / tuan trajectory, 已并入 session) ---
    rp = sesub.add_parser("replay", help="回放历史会话 (事件溯源重建时间线)")
    rp.add_argument(
        "session", nargs="?", default=None, help="会话 ID 或前缀 (默认列出最近会话)"
    )
    rp.add_argument("--json", action="store_true", help="以 JSON 输出 Trajectory")
    rp.add_argument(
        "--export", metavar="PATH", default=None, help="把回放导出为 Markdown 文件"
    )
    rp.add_argument("--list", action="store_true", help="列出最近会话")
    # --- 第 50 个独特功能: 多维筛选回放 (TrajectoryReplay.replay) ---
    rp.add_argument("--filter-type", dest="filter_type", default=None,
                    help="按事件类型筛选 (user/assistant/tool_call/tool/system/security)")
    rp.add_argument("--filter-tool", dest="filter_tool", default=None,
                    help="按工具名筛选")
    rp.add_argument("--filter-status", dest="filter_status", default=None,
                    help="按状态筛选 (ok/error/denied/timeout)")
    rp.add_argument("--filter-source", dest="filter_source", default=None,
                    help="按来源模块筛选")
    rp.add_argument("--limit", type=int, default=50, help="显示条数 (默认 50)")
    tj = sesub.add_parser("trajectory", help="Trajectory 轨迹: 结构化导出/查看会话")
    tjsub = tj.add_subparsers(dest="traj_cmd")
    tjs = tjsub.add_parser("show", help="查看会话的 Trajectory 摘要")
    tjs.add_argument("session", help="会话 ID 或前缀")
    tje = tjsub.add_parser("export", help="导出 Trajectory 为 JSON / Markdown")
    tje.add_argument("session", help="会话 ID 或前缀")
    tje.add_argument(
        "--format", choices=["json", "md"], default="md", help="导出格式 (默认 md)"
    )
    tje.add_argument(
        "--out", metavar="PATH", default=None, help="输出文件路径 (默认 stdout)"
    )
    # --- 第 50 个独特功能: TrajectoryReplay 高级分析/时间线/分叉/快照 ---
    tja = tjsub.add_parser("analyze",
                           help="轨迹分析: 工具延迟/状态/来源/安全事件统计 (差异化)")
    tja.add_argument("session", help="会话 ID 或前缀")
    tja.add_argument("--json", action="store_true", help="以 JSON 输出")
    tjt = tjsub.add_parser("timeline", help="导出事件时间线 (Markdown, 图标/状态/延迟)")
    tjt.add_argument("session", help="会话 ID 或前缀")
    tjt.add_argument("--limit", type=int, default=50, help="显示条数 (默认 50)")
    tjt.add_argument("--json", action="store_true", help="以 JSON 输出事件列表")
    tjf = tjsub.add_parser("fork", help="从断点分叉出新回放分支 (快照落盘)")
    tjf.add_argument("session", help="会话 ID 或前缀")
    tjf.add_argument("--at", type=int, required=True, help="分叉断点序号")
    tjf.add_argument("--label", default="", help="分叉标签")
    tjf.add_argument("--json", action="store_true", help="以 JSON 输出")
    tjsn = tjsub.add_parser("snapshots", help="列出已保存的分叉快照")
    tjsn.add_argument("--json", action="store_true", help="以 JSON 输出")
    # --- 事件溯源查询/统计 (第 38 个独特功能) ---
    ev = sesub.add_parser(
        "events",
        help="事件溯源: 单一真相源查询/统计 (类型/语义分布/单条事件, 差异化)",
    )
    ev.add_argument("session", nargs="?", default=None, help="会话 ID 或前缀")
    ev.add_argument("--kind", default=None, help="按事件类型过滤 (如 tool_call)")
    ev.add_argument("--seq", type=int, default=None, help="查看单条事件 (按序号)")
    ev.add_argument("--limit", type=int, default=30, help="显示条数 (默认 30)")
    ev.add_argument("--json", action="store_true", help="以 JSON 输出")
    p.set_defaults(func="cmd_session")

    # --- session wire (WireStore 上下文记录流只读体检, 第 119 个独特功能) ---
    wr = sesub.add_parser(
        "wire",
        help="WireStore 上下文记录流只读体检: 类型分布/时间跨度/协议版本 (差异化)",
    )
    wr.add_argument("session", nargs="?", default=None, help="会话 ID 或前缀")
    wr.add_argument("--json", action="store_true", help="以 JSON 输出")
    wr.set_defaults(func="cmd_session", session_cmd="wire")

    # ---- session query (EventSourcer API 化查询, 第 84 个独特功能) ----
    sq = sesub.add_parser(
        "query",
        help="EventSourcer API 化查询: 类型/时间窗/标签/序号多维过滤 (差异化)",
    )
    sq.add_argument("session", nargs="?", default=None, help="会话 ID 或前缀")
    sq.add_argument("--kind", default=None, help="按事件类型过滤 (如 tool_call)")
    sq.add_argument("--tag", default=None, help="按标签过滤 (如 security)")
    sq.add_argument("--since", type=float, default=None, help="起始时间戳 (unix)")
    sq.add_argument("--until", type=float, default=None, help="截止时间戳 (unix)")
    sq.add_argument("--since-seq", type=int, default=0, help="起始序号")
    sq.add_argument("--until-seq", type=int, default=0, help="截止序号")
    sq.add_argument("--limit", type=int, default=1000, help="最大条数 (默认 1000)")
    sq.add_argument("--count", action="store_true", help="只统计命中数, 不列事件")
    sq.add_argument("--json", action="store_true", help="以 JSON 输出")
    sq.set_defaults(func="cmd_session", session_cmd="query")

    # ---- session sourcer (EventSourcer 内存态分叉/回放, 第 87 个独特功能) ----
    so = sesub.add_parser(
        "sourcer",
        help="EventSourcer 内存态分叉/回放 API: fork/list/get/replay/resume (差异化)",
    )
    sosc = so.add_subparsers(dest="sourcer_cmd", required=True)
    so_fork = sosc.add_parser("fork", help="在事件流指定序号创建分叉锚点")
    so_fork.add_argument("session", nargs="?", default=None, help="会话 ID 或前缀")
    so_fork.add_argument("--at", type=int, required=True, help="分叉锚点序号")
    so_fork.add_argument("--reason", default="", help="分叉原因")
    so_fork.add_argument("--json", action="store_true", help="以 JSON 输出")
    so_list = sosc.add_parser("list", help="列出分叉点")
    so_list.add_argument("session", nargs="?", default=None, help="会话 ID 或前缀")
    so_list.add_argument("--json", action="store_true", help="以 JSON 输出")
    so_get = sosc.add_parser("get", help="查看单个分叉点")
    so_get.add_argument("session", nargs="?", default=None, help="会话 ID 或前缀")
    so_get.add_argument("fork_id", help="分叉 ID")
    so_get.add_argument("--json", action="store_true", help="以 JSON 输出")
    so_rp = sosc.add_parser("replay", help="重放分叉后的事件 (内存计算)")
    so_rp.add_argument("session", nargs="?", default=None, help="会话 ID 或前缀")
    so_rp.add_argument("fork_id", help="分叉 ID")
    so_rp.add_argument("--to-seq", type=int, default=0, help="截止序号 (默认最新)")
    so_rp.add_argument("--json", action="store_true", help="以 JSON 输出")
    so_rs = sosc.add_parser("resume", help="从分叉点恢复 messages (供续聊)")
    so_rs.add_argument("session", nargs="?", default=None, help="会话 ID 或前缀")
    so_rs.add_argument("fork_id", help="分叉 ID")
    so_rs.add_argument("--json", action="store_true", help="以 JSON 输出")
    so.set_defaults(func="cmd_session", session_cmd="sourcer")

    # ---- session digest (无 LLM 结构化摘要提取预览, 第 89 个独特功能) ----
    sdg = sesub.add_parser(
        "digest",
        help="无 LLM 的结构化摘要提取预览: 上下文压缩会保留哪些关键信息 (差异化)",
    )
    sdg.add_argument("session", nargs="?", default=None, help="会话 ID 或前缀")
    sdg.add_argument("--tail", type=int, default=0,
                     help="只看最近 N 条消息 (默认全部)")
    sdg.add_argument("--json", action="store_true", help="以 JSON 输出")
    sdg.set_defaults(func="cmd_session", session_cmd="digest")

    # ---- sessions (复数: 精简列表 / 删除, C-4.4/C-4.5) ----
    p = sub.add_parser("sessions", help="会话列表与删除 (最近 20 条 / rm)")
    sesub2 = p.add_subparsers(dest="sessions_cmd")
    sesub2.add_parser("list", help="列出最近 20 条会话 (默认子命令)")
    rm = sesub2.add_parser("rm", help="删除指定会话")
    rm.add_argument("target", nargs="?", help="会话ID / 编号 / latest")
    rm.add_argument("--all", action="store_true", help="清空全部会话")
    rm.add_argument("--yes", "-y", action="store_true", help="跳过确认")
    p.set_defaults(func="cmd_sessions", sessions_cmd="list")

    p = sub.add_parser("usercmd", help="用户自定义斜杠命令 (列出)")
    ussub = p.add_subparsers(dest="usercmd_cmd")
    ussub.add_parser("list", help="列出全部自定义命令")
    p.set_defaults(func="cmd_usercmd")

    p = sub.add_parser("agents", help="Agent View: 多会话管理面板")
    asub = p.add_subparsers(dest="agents_cmd")
    av = asub.add_parser("view", help="打开 Agent View 面板 (默认)")
    av.add_argument(
        "--watch", action="store_true", help="实时刷新模式 (每 2 秒, 类 top)"
    )
    asub.add_parser("list", help="列出所有会话")
    ak = asub.add_parser("kill", help="终止后台会话")
    ak.add_argument("session_id", help="会话 ID (可前缀)")
    at = asub.add_parser("attach", help="附着到某会话 (转 tuan session resume)")
    at.add_argument("session_id", help="会话 ID (可前缀)")
    p.set_defaults(func="cmd_agents")

    # ---- rewind (会话时间线回溯) ----
    p = sub.add_parser("rewind", help="会话 Rewind: 回退到之前的快照")
    p.add_argument("session_id", nargs="?", default="", help="会话 ID (可前缀)")
    p.add_argument(
        "--to", dest="to", type=int, default=None, help="回退到第 N 个快照 (默认最新)"
    )
    p.add_argument("--list", action="store_true", help="列出当前工作区快照")
    p.add_argument("--checkpoint", action="store_true",
                   help="自动检查点可观测性: 列表/统计/摘要/清空 (差异化)")
    p.add_argument("--show", default=None,
                   help="显示检查点摘要 (序号 1=最新 或 完整 id 如 ckp1; 配合 --checkpoint)")
    # 检查点压缩摘要只读预览 (第 65 个独特功能)
    p.add_argument(
        "--preview", default=None,
        help="检查点摘要预览 (只读, 不改变磁盘): 序号/id/latest/all; 配合 --checkpoint",
    )
    p.add_argument("--clear", action="store_true",
                   help="清空检查点 (配合 --checkpoint, 危险)")
    p.add_argument("--json", action="store_true",
                   help="结构化输出 (配合 --checkpoint, CI 消费)")
    p.set_defaults(func="cmd_rewind")

    # ---- diff (操作账本驱动的字节级 diff 展示, 第 88 个独特功能) ----
    p = sub.add_parser(
        "diff",
        help="账本驱动的字节级 diff: 最近编辑/摘要统计 (差异化, 不依赖活动会话)",
    )
    p.add_argument("--last", type=int, default=0, help="只看最近 N 次编辑")
    p.add_argument("--file", default="", help="只看匹配该路径的编辑")
    p.add_argument("--stat", action="store_true", help="只显示摘要统计 (+/- 行数)")
    p.add_argument("--scope", action="store_true",
                   help="影响半径统计: 涉及文件数/操作数/文件清单 (第 94 个独特功能)")
    p.add_argument("--json", action="store_true", help="机器可读输出")
    p.set_defaults(func="cmd_diff")

    # ---- project (Project 层: 项目级记忆/配置/工作区隔离) ----
    p = sub.add_parser("project", help="Project 层: 项目级记忆/配置/工作区隔离")
    prsub = p.add_subparsers(dest="project_cmd")
    pi = prsub.add_parser("init", help="在当前目录初始化 .tuan 项目结构 (幂等)")
    pi.add_argument("--force", action="store_true", help="重建骨架")
    prsub.add_parser("info", help="显示当前项目信息")
    prsub.add_parser("list", help="列出已知项目")
    pmd = prsub.add_parser("memory-dir", help="显示隔离模式下项目级记忆目录")
    pmd.set_defaults(project_cmd="memory-dir")
    patt = prsub.add_parser("attach", help="登记一个会话到当前项目索引")
    patt.add_argument("session_id", help="会话 ID")
    patt.add_argument("--task", default="", help="任务描述 (可选)")
    patt.set_defaults(project_cmd="attach")
    psess = prsub.add_parser("sessions", help="列出登记到本项目的会话索引 (第 99 个独特功能)")
    psess.add_argument("--json", action="store_true", help="输出 JSON")
    psess.set_defaults(project_cmd="sessions")
    p.set_defaults(func="cmd_project")

    # ---- chat handoff (Chat 层: 会话交接) ----
    p = sub.add_parser("chat", help="Chat 层: 会话交接 handoff")
    chsub = p.add_subparsers(dest="chat_cmd")
    ch = chsub.add_parser("handoff", help="交接指定会话: 生成摘要 -> 开新会话")
    ch.add_argument("session_id", help="旧会话 ID (可前缀)")
    p.set_defaults(func="cmd_chat_handoff")

    # ---- worktree (Worktree 层: git worktree 并行实验) ----
    p = sub.add_parser("worktree", help="Worktree 层: git worktree 并行实验")
    wsub = p.add_subparsers(dest="worktree_cmd")
    wc = wsub.add_parser("create", help="创建 worktree (.tuan/worktrees/<name>)")
    wc.add_argument("name", help="worktree 名 (= 新分支名)")
    wsub.add_parser("list", help="列出所有 worktree")
    wr = wsub.add_parser("remove", help="删除 worktree")
    wr.add_argument("name", help="worktree 名")
    ws = wsub.add_parser("switch", help="显示 worktree 路径")
    ws.add_argument("name", help="worktree 名")
    wa = wsub.add_parser(
        "agent-create", help="为子代理创建/复用隔离 worktree (对标 Claude Code createAgentWorktree)"
    )
    wa.add_argument("spec_id", help="子代理 spec_id (用于命名 agent-<tail>-<slug>)")
    wa.add_argument("--slug", default="work", help="命名 slug (默认 work)")
    wa.add_argument("--cwd", default=None, help="original_cwd (默认工作区)")
    wsub.add_parser("cleanup", help="清理全部 ephemeral 子代理 worktree (agent-*/wf_*/bridge-*/job-*)")
    wst = wsub.add_parser("state", help="列出子代理 worktree 持久化会话状态")
    wst.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func="cmd_worktree")

    # --- plan (实施计划存档只读体检, 第 120 个独特功能) ---
    p = sub.add_parser("plan", help="实施计划存档只读体检: show / diff (差异化)")
    psub = p.add_subparsers(dest="plan_cmd", required=False)
    # 父命令也要 func: 只有叶子有默认值时 `tuan plan` 本身分发不到任何函数
    # (main() 直接 AttributeError), 且测试要求除 improve 外每个顶层子命令都
    # 注册 func。默认 show 是安全的只读面。
    p.set_defaults(func="cmd_plan", plan_cmd="show")
    ps = psub.add_parser("show", help="查看当前已确认实施计划存档")
    ps.add_argument("--workspace", help="覆盖工作区目录")
    ps.add_argument("--json", action="store_true", help="输出 JSON")
    ps.set_defaults(func="cmd_plan")
    pd = psub.add_parser("diff", help="与指定文件/字符串比对计划差异摘要")
    pd.add_argument("--workspace", help="覆盖工作区目录")
    pd.add_argument("--file", help="比对对象文件路径")
    pd.add_argument("--text", help="比对对象文本")
    pd.add_argument("--json", action="store_true", help="输出 JSON")
    pd.set_defaults(func="cmd_plan")
