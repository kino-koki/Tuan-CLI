"""信任与策略命令: 工作区信任 / 引导 / 命令目录 / 人格 / 运行模式 / 成本 / 遥测 / 角色 / 边界声明。

从 `parser_commands.py` 拆出的 `register_subcommands` 分片, 行为不变。
"""

from __future__ import annotations

from typing import Any
def register_trust_policy(sub: Any) -> None:
    """注册 trust_policy 域子命令。"""

    p = sub.add_parser(
        "trust", help="工作区信任管理: 信任边界 (受信/受限/不信任 + 衰减)"
    )
    p.set_defaults(func="cmd_trust", trust_cmd="status")
    tsub = p.add_subparsers(dest="trust_cmd", required=False)
    tst = tsub.add_parser("status", help="列出受信工作区")
    tst.add_argument("--all", action="store_true", help="连不信任工作区也列出")
    tst.set_defaults(trust_cmd="status")
    tchk = tsub.add_parser("check", help="裁决某路径的信任级别 (含衰减提示)")
    tchk.add_argument("path", help="要检查的工作区路径")
    tchk.set_defaults(trust_cmd="check")
    tset = tsub.add_parser("set", help="标记工作区信任级别")
    tset.add_argument("path", help="工作区路径")
    tset.add_argument("level", choices=("trusted", "limited", "untrusted"),
                      help="信任级别")
    tset.add_argument("--name", default="", help="项目名 (可选)")
    tset.set_defaults(trust_cmd="set")
    trm = tsub.add_parser("remove", help="撤销信任")
    trm.add_argument("path", help="工作区路径")
    trm.set_defaults(trust_cmd="remove")
    tsub.add_parser("cleanup", help="清理 >90 天未用的过期信任").set_defaults(
        trust_cmd="cleanup"
    )
    texp = tsub.add_parser("export", help="导出信任策略为可移植 JSON (团队共享)")
    texp.add_argument("--file", default=None, help="输出文件 (默认 stdout)")
    texp.set_defaults(trust_cmd="export")
    timp = tsub.add_parser("import", help="导入信任策略 (建立与团队一致的信任边界)")
    timp.add_argument("file", help="策略 JSON 文件")
    timp.add_argument("--overwrite", action="store_true", help="覆盖同路径已有记录")
    timp.set_defaults(trust_cmd="import")
    tmx = tsub.add_parser("matrix", help="L1 信任滤网动作矩阵 (fail-closed 透明度)")
    tmx.add_argument("--json", action="store_true",
                     help="结构化输出 (CI / 审计消费)")
    tmx.set_defaults(trust_cmd="matrix")
    taud = tsub.add_parser("audit", help="信任决策审计 (级别分布 + 衰减 + 敏感面)")
    taud.add_argument("--json", action="store_true",
                      help="结构化输出 (CI / 审计消费)")
    taud.set_defaults(trust_cmd="audit")
    # 信任衰减维护: 检测/强制衰减/时间戳刷新 (第 63 个独特功能)
    tdec = tsub.add_parser(
        "decay", help="信任衰减检测/强制衰减/时间戳刷新 (差异化)"
    )
    tdec.add_argument("path", nargs="?", default=None, help="目标路径")
    tdec.add_argument("--force", action="store_true",
                      help="强制衰减 trusted→limited (留审计原因)")
    tdec.add_argument("--touch", action="store_true",
                      help="刷新使用时间戳 (确认仍在使用, 避免超期误衰减)")
    tdec.add_argument("--json", action="store_true",
                      help="结构化输出 (CI / 审计消费)")
    tdec.set_defaults(trust_cmd="decay")

    p = sub.add_parser(
        "onboarding", help="首次运行引导 (欢迎/可选模型配置/快速上手)"
    )
    p.add_argument("--skip", action="store_true", help="跳过引导并写入完成标记")
    p.set_defaults(func="cmd_onboarding")

    p = sub.add_parser(
        "commands", help="以 JSON 输出所有可用斜杠命令及其元数据 (供 IDE/外部工具消费)"
    )
    p.set_defaults(func="cmd_commands")

    p = sub.add_parser(
        "personality", help="人设管理 (列出/查看/设置行为风格, 大上下文模型专属)"
    )
    p.set_defaults(func="cmd_personality", personality_cmd="list")
    psub = p.add_subparsers(dest="personality_cmd", required=False)
    psub.add_parser("list", help="列出所有可用人设").set_defaults(
        personality_cmd="list"
    )
    psub.add_parser("show", help="显示当前人设详情").set_defaults(
        personality_cmd="show"
    )
    pset = psub.add_parser("set", help="设置人设 (写入 USER.md)")
    pset.add_argument("name", help=f"人设名: {'/'.join(__import__('tuan_cli.core.personality', fromlist=['PERSONALITY_NAMES']).PERSONALITY_NAMES)}")
    pset.set_defaults(personality_cmd="set")
    psub.add_parser("auto", help="恢复自动分配").set_defaults(
        personality_cmd="auto"
    )

    mode_p = sub.add_parser(
        "mode", help="五模式切换 (感通/灵码/闲聊/无界/协同; 旧名 standard/yolo/plan 可用)"
    )
    mode_sub = mode_p.add_subparsers(dest="mode_cmd", required=True)
    mode_sub.add_parser("list", help="列出所有模式").set_defaults(func="cmd_mode")
    mode_sub.add_parser("current", help="显示当前模式").set_defaults(func="cmd_mode")
    mode_show = mode_sub.add_parser("show", help="显示模式详情与能力矩阵")
    mode_show.add_argument("mode_id", nargs="?", default=None, help="模式 ID (默认当前)")
    mode_show.set_defaults(func="cmd_mode")
    mode_switch = mode_sub.add_parser("switch", help="切换模式")
    mode_switch.add_argument("mode_id", help="目标模式 ID")
    mode_switch.add_argument("--force", action="store_true", help="跳过二次确认")
    mode_switch.set_defaults(func="cmd_mode")
    mode_p.set_defaults(func="cmd_mode")

    p = sub.add_parser(
        "cost", help="成本/使用审计: 模型路由决策历史 (按天/模型/供应商聚合)"
    )
    p.set_defaults(func="cmd_cost", cost_cmd="report")
    csub = p.add_subparsers(dest="cost_cmd", required=False)
    csub.add_parser("report", help="按天/模型/供应商聚合报告").set_defaults(
        cost_cmd="report"
    )
    clast = csub.add_parser("last", help="最近 N 条路由决策明细")
    clast.add_argument("--last", type=int, default=20, help="条数 (默认 20)")
    clast.set_defaults(cost_cmd="last")
    ctop = csub.add_parser("top", help="最热/最频繁的模型 Top-K")
    ctop.add_argument("--top", type=int, default=5, help="K (默认 5)")
    ctop.set_defaults(cost_cmd="top")
    csub.add_parser("json", help="输出原始 JSON 数组 (SIEM/流水线)").set_defaults(
        cost_cmd="json"
    )
    csub.add_parser(
        "budget", help="预算燃烧率: 已用/剩余/趋势 (差异化, 超 Claude Code 单次硬上限)"
    ).set_defaults(cost_cmd="budget")
    ctrend = csub.add_parser(
        "trend", help="成本历史趋势 ASCII 柱状图 (按天可视化, Claude Code 无)"
    )
    ctrend.add_argument("--days", type=int, default=14, help="窗口天数 (默认 14)")
    ctrend.set_defaults(cost_cmd="trend")
    ceff = csub.add_parser(
        "efficiency", help="成本效率归因: 每模型/供应商每 1k token 花费 (差异化)"
    )
    ceff.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    ceff.set_defaults(cost_cmd="efficiency")
    p.add_argument("--last", type=int, default=20, help="明细条数 (last 用)")
    p.add_argument("--top", type=int, default=5, help="Top-K (top 用)")
    p.add_argument("--days", type=int, default=14, help="趋势窗口 (trend 用)")
    p.add_argument("--json", action="store_true", help="输出 JSON (report 用)")

    # ---- telemetry (遥测可观测性, 第 44 个独特功能: 本地可查询/可导出/跨进程可见) ----
    p = sub.add_parser(
        "telemetry",
        help="遥测可观测性: span树/指标本地查询与 JSONL 导出 (Claude Code 黑盒上传, 本命令本地优先)",
    )
    p.set_defaults(func="cmd_telemetry", telemetry_cmd="stats")
    tsub = p.add_subparsers(dest="telemetry_cmd", required=False)
    ts = tsub.add_parser("stats", help="本进程内存统计 + 磁盘导出文件盘点")
    ts.add_argument("--json", action="store_true", help="输出 JSON (CI / SIEM 消费)")
    ts.set_defaults(telemetry_cmd="stats")
    tsp = tsub.add_parser("spans", help="最近 N 条 span (内存优先, 回退磁盘)")
    tsp.add_argument("--n", type=int, default=20, help="条数 (默认 20)")
    tsp.add_argument("--json", action="store_true", help="输出 JSON (CI / SIEM 消费)")
    tsp.set_defaults(telemetry_cmd="spans")
    tex = tsub.add_parser("export", help="导出全部 span 为 JSONL")
    tex.add_argument("--path", default=None, help="导出路径 (默认 ~/.tuan/telemetry/)")
    tex.add_argument("--json", action="store_true", help="输出 JSON (CI / SIEM 消费)")
    tex.set_defaults(telemetry_cmd="export")
    # OTLP 导出/自动导出/清空 (第 64 个独特功能)
    tot = tsub.add_parser(
        "otlp", help="OTLP 导出/自动导出判断/清空 (遥测数据归用户所有)"
    )
    tot.add_argument(
        "--endpoint", default=None,
        help="OTLP HTTP 接收端 URL (如 http://localhost:4318/v1/traces)",
    )
    tot.add_argument("--clear", action="store_true",
                     help="清空本进程遥测缓冲 (防内存/磁盘无限增长)")
    tot.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    tot.set_defaults(telemetry_cmd="otlp")
    p.add_argument("--json", action="store_true", help="输出 JSON (CI / SIEM 消费)")

    # ---- roles (专业化角色系统查询, 第 45 个独特功能: 角色透明化+推荐) ----
    p = sub.add_parser(
        "roles",
        help="专业化角色系统: 查询 7 个角色的系统提示/质量标准/工具集, 按任务推荐角色",
    )
    p.set_defaults(func="cmd_roles", roles_cmd="list")
    rsub = p.add_subparsers(dest="roles_cmd", required=False)
    rls = rsub.add_parser("list", help="列出全部角色 (默认)")
    rls.add_argument("--json", action="store_true", help="输出 JSON")
    rls.set_defaults(roles_cmd="list")
    rgt = rsub.add_parser("get", help="查看单个角色详情")
    rgt.add_argument("role_id", help="角色 id (reviewer/tester/debugger/architect/security_auditor/documenter/implementer)")
    rgt.add_argument("--json", action="store_true", help="输出 JSON")
    rgt.set_defaults(roles_cmd="get")
    rsg = rsub.add_parser("suggest", help="按关键词推荐角色")
    rsg.add_argument("task", help="任务描述 (关键词匹配)")
    rsg.add_argument("--json", action="store_true", help="输出 JSON")
    rsg.set_defaults(roles_cmd="suggest")
    p.add_argument("--json", action="store_true", help="输出 JSON")

    # ---- boundary (四层边界自动决策可预判, 第 73 个独特功能) ----
    p = sub.add_parser(
        "boundary",
        help="四层边界自动决策: 隔离/并行worktree预判 (Claude Code 边界是执行期黑箱)",
    )
    p.set_defaults(func="cmd_boundary", boundary_cmd="check")
    bsub = p.add_subparsers(dest="boundary_cmd", required=False)
    bck = bsub.add_parser("check", help="对任务描述预判边界决策 (默认)")
    bck.add_argument("task", help="任务描述 (预判是否隔离/并行)")
    bck.add_argument("--json", action="store_true", help="输出 JSON")
    bck.set_defaults(boundary_cmd="check")
    bst = bsub.add_parser("status", help="四层边界开关总览")
    bst.add_argument("--json", action="store_true", help="输出 JSON")
    bst.set_defaults(boundary_cmd="status")
