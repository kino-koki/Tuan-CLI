"""Agent 能力命令: superagent / safety / 审计仓 / Web 缓存 / 产物 / 待办 / 图像 / 目标 / 循环 / 工作流。

从 `parser_commands.py` 拆出的 `register_subcommands` 分片, 行为不变。
"""

from __future__ import annotations

from typing import Any
def register_agent_features(sub: Any) -> None:
    """注册 agent_features 域子命令。"""

    # ---- superagent (Super-Agent 持久化状态只读审计, 第 102 个独特功能, 纯只读) ----
    psa = sub.add_parser(
        "superagent",
        help="Super-Agent 持久化状态只读审计: 工单/WAL/订阅/上下文 (差异化, 纯只读)",
    )
    psa.add_argument("--home", default=None, help="TUAN home 目录 (默认 ~/.tuan)")
    psa.add_argument("--json", action="store_true", help="输出 JSON")
    psa.set_defaults(func="cmd_superagent", superagent_cmd="overview")
    sasub = psa.add_subparsers(dest="superagent_cmd", required=False)
    # overview (顶层默认)
    saov = sasub.add_parser("overview", help="概览: 统计 + 最近未完成工单")
    saov.add_argument("--home", default=None, help="TUAN home 目录")
    saov.add_argument("--json", action="store_true", help="输出 JSON")
    saov.set_defaults(func="cmd_superagent", superagent_cmd="overview")
    # tickets
    satk = sasub.add_parser("tickets", help="列出全部工单")
    satk.add_argument("--status", default=None, help="按状态过滤 (pending/running/blocked/review/done/failed/...)")
    satk.add_argument("--limit", type=int, default=50, help="最多显示 N 条")
    satk.add_argument("--home", default=None, help="TUAN home 目录")
    satk.add_argument("--json", action="store_true", help="输出 JSON")
    satk.set_defaults(func="cmd_superagent", superagent_cmd="tickets")
    # ticket <id>
    sat = sasub.add_parser("ticket", help="查看单个工单详情")
    sat.add_argument("ticket_id", help="工单 ID")
    sat.add_argument("--home", default=None, help="TUAN home 目录")
    sat.add_argument("--json", action="store_true", help="输出 JSON")
    sat.set_defaults(func="cmd_superagent", superagent_cmd="ticket")
    # pending
    sapd = sasub.add_parser("pending", help="中断/未完成工单 (可恢复)")
    sapd.add_argument("--home", default=None, help="TUAN home 目录")
    sapd.add_argument("--json", action="store_true", help="输出 JSON")
    sapd.set_defaults(func="cmd_superagent", superagent_cmd="pending")
    # outbox
    saob = sasub.add_parser("outbox", help="WAL 先记录后执行队列")
    saob.add_argument("--home", default=None, help="TUAN home 目录")
    saob.add_argument("--json", action="store_true", help="输出 JSON")
    saob.set_defaults(func="cmd_superagent", superagent_cmd="outbox")
    # subscriptions
    sasb = sasub.add_parser("subscriptions", help="订阅映射 (thread → worker)")
    sasb.add_argument("--home", default=None, help="TUAN home 目录")
    sasb.add_argument("--json", action="store_true", help="输出 JSON")
    sasb.set_defaults(func="cmd_superagent", superagent_cmd="subscriptions")
    # context
    sact = sasub.add_parser("context", help="持久化观察上下文")
    sact.add_argument("--home", default=None, help="TUAN home 目录")
    sact.add_argument("--json", action="store_true", help="输出 JSON")
    sact.set_defaults(func="cmd_superagent", superagent_cmd="context")

    # ---- safety (跨来源综合风险评分, 第 106 个独特功能, 纯只读) ----
    psf = sub.add_parser(
        "safety",
        help="跨来源综合风险评分: 多只读面加权合成 0-100 分 (差异化, 纯只读)",
    )
    psf.add_argument("--home", default=None, help="TUAN home 目录 (默认 ~/.tuan)")
    psf.add_argument("--window", type=int, default=24, help="时间窗小时数 (默认 24h)")
    psf.add_argument("--json", action="store_true", help="输出 JSON")
    psf.set_defaults(func="cmd_safety", safety_cmd="score")
    sfs = psf.add_subparsers(dest="safety_cmd", required=False)
    sfsc = sfs.add_parser("score", help="综合风险评分 (0-100)")
    sfsc.add_argument("--home", default=None, help="TUAN home 目录")
    sfsc.add_argument("--window", type=int, default=24, help="时间窗小时数 (默认 24h)")
    sfsc.add_argument("--json", action="store_true", help="输出 JSON")
    sfsc.set_defaults(func="cmd_safety", safety_cmd="score")

    # ---- auditstore (内核全量审计事件归档只读查询, 第 107 个独特功能, 纯只读) ----
    pas = sub.add_parser(
        "auditstore",
        help="内核全量审计事件归档只读查询: 统计/最近/按条件过滤 (差异化, 纯只读)",
    )
    pas.add_argument("--home", default=None, help="TUAN home 目录 (默认 ~/.tuan)")
    pas.add_argument("--json", action="store_true", help="输出 JSON")
    pas.set_defaults(func="cmd_auditstore", auditstore_cmd="stats")
    assub = pas.add_subparsers(dest="auditstore_cmd", required=False)
    # stats (顶层默认)
    ast = assub.add_parser("stats", help="统计: 总量/类型分布/时间跨度")
    ast.add_argument("--home", default=None, help="TUAN home 目录")
    ast.add_argument("--json", action="store_true", help="输出 JSON")
    ast.set_defaults(func="cmd_auditstore", auditstore_cmd="stats")
    # recent
    asr = assub.add_parser("recent", help="最近 N 条审计事件")
    asr.add_argument("--limit", type=int, default=20, help="最多显示 N 条 (默认 20)")
    asr.add_argument("--type", default=None, help="按事件类型过滤")
    asr.add_argument("--home", default=None, help="TUAN home 目录")
    asr.add_argument("--json", action="store_true", help="输出 JSON")
    asr.set_defaults(func="cmd_auditstore", auditstore_cmd="recent")
    # query
    asq = assub.add_parser("query", help="按类型/关键词/时间窗过滤")
    asq.add_argument("--type", default=None, help="按事件类型过滤")
    asq.add_argument("--keyword", default="", help="关键词 (匹配 type + payload)")
    asq.add_argument("--since", default=None, help="自 N 小时前起 (默认不限)")
    asq.add_argument("--until", default=None, help="至 N 小时前止 (默认不限)")
    asq.add_argument("--limit", type=int, default=50, help="最多显示 N 条 (默认 50)")
    asq.add_argument("--home", default=None, help="TUAN home 目录")
    asq.add_argument("--json", action="store_true", help="输出 JSON")
    asq.set_defaults(func="cmd_auditstore", auditstore_cmd="query")

    # ---- webcache (Web 搜索磁盘缓存只读体检, 第 109 个独特功能, 纯只读) ----
    pwc = sub.add_parser(
        "webcache",
        help="Web 搜索磁盘缓存只读体检: 条目/新鲜/过期/引擎分布 (差异化, 纯只读)",
    )
    pwc.add_argument("--top", type=int, default=0, help="只显示前 N 条详情 (0=全部)")
    pwc.add_argument("--json", action="store_true", help="输出 JSON")
    pwc.set_defaults(func="cmd_webcache")

    # ---- artifact (Artifact 产物只读枚举, 第 110 个独特功能, 纯只读) ----
    part = sub.add_parser(
        "artifact", help="Artifact 产物只读枚举: 列出/预览已生成的自包含 HTML 产物"
    )
    part.add_argument("--workspace", default=None, help="工作区目录 (默认 TUAN_WORKSPACE/当前)")
    part.add_argument("--json", action="store_true", help="输出 JSON")
    part.set_defaults(func="cmd_artifact", artifact_cmd="list")
    artsub = part.add_subparsers(dest="artifact_cmd", required=False)
    # list (顶层默认)
    arl = artsub.add_parser("list", help="枚举产物 (标题/文件/大小/时间/预览)")
    arl.add_argument("--workspace", default=None, help="工作区目录")
    arl.add_argument("--limit", type=int, default=0, help="最多 N 个 (0=全部)")
    arl.add_argument("--json", action="store_true", help="输出 JSON")
    arl.set_defaults(func="cmd_artifact", artifact_cmd="list")
    # show
    ars = artsub.add_parser("show", help="预览单个产物正文首行")
    ars.add_argument("file", help="产物文件名 (如 report_20261111_120000.html)")
    ars.add_argument("--workspace", default=None, help="工作区目录")
    ars.add_argument("--json", action="store_true", help="输出 JSON")
    ars.set_defaults(func="cmd_artifact", artifact_cmd="show")

    # ---- todo (持久化任务清单只读查看, 第 112 个独特功能, 纯只读) ----
    tsub = sub.add_parser(
        "todo", help="持久化任务清单只读查看: 脱离会话审计 TodoWrite 状态"
    )
    tsub.add_argument("--workspace", default=None, help="工作区目录 (默认 TUAN_WORKSPACE/当前)")
    tsub.add_argument("--json", action="store_true", help="输出 JSON")
    tsub.set_defaults(func="cmd_todo", todo_cmd="list")
    tosub = tsub.add_subparsers(dest="todo_cmd", required=False)
    # list (顶层默认)
    tol = tosub.add_parser("list", help="列出工作区任务清单 (三态+进度)")
    tol.add_argument("--workspace", default=None, help="工作区目录")
    tol.add_argument("--json", action="store_true", help="输出 JSON")
    tol.set_defaults(func="cmd_todo", todo_cmd="list")
    # show
    tos = tosub.add_parser("show", help="查看单个步骤详情")
    tos.add_argument("index", help="步骤序号 (1 起)")
    tos.add_argument("--workspace", default=None, help="工作区目录")
    tos.add_argument("--json", action="store_true", help="输出 JSON")
    tos.set_defaults(func="cmd_todo", todo_cmd="show")

    # ---- image (已生成图片只读枚举, 第 113 个独特功能, 纯只读) ----
    img = sub.add_parser(
        "image", help="已生成图片只读枚举: 列出/查看 AI 生成产物 (脱离会话)"
    )
    img.add_argument("--workspace", default=None, help="工作区目录 (默认 TUAN_WORKSPACE/当前)")
    img.add_argument("--json", action="store_true", help="输出 JSON")
    img.set_defaults(func="cmd_image", image_cmd="list")
    imsub = img.add_subparsers(dest="image_cmd", required=False)
    # list (顶层默认)
    iml = imsub.add_parser("list", help="枚举生成图片 (文件/大小/时间/前缀分布)")
    iml.add_argument("--workspace", default=None, help="工作区目录")
    iml.add_argument("--limit", type=int, default=0, help="最多 N 张 (0=全部)")
    iml.add_argument("--json", action="store_true", help="输出 JSON")
    iml.set_defaults(func="cmd_image", image_cmd="list")
    # show
    ims = imsub.add_parser("show", help="查看单张图片元信息")
    ims.add_argument("file", help="图片文件名 (如 img_20260919_143052_abc123.png)")
    ims.add_argument("--workspace", default=None, help="工作区目录")
    ims.add_argument("--json", action="store_true", help="输出 JSON")
    ims.set_defaults(func="cmd_image", image_cmd="show")

    # ---- goal (持久化 Goal 状态只读查看, 第 114 个独特功能, 纯只读) ----
    gol = sub.add_parser(
        "goal", help="持久化 Goal 状态只读查看: 脱离会话审计目标/步骤进度"
    )
    gol.add_argument("--workspace", default=None, help="工作区目录 (默认 TUAN_WORKSPACE/当前)")
    gol.add_argument("--json", action="store_true", help="输出 JSON")
    gol.set_defaults(func="cmd_goal", goal_cmd="status")
    gosub = gol.add_subparsers(dest="goal_cmd", required=False)
    # status (顶层默认)
    gos = gosub.add_parser("status", help="查看当前目标与步骤进度 (含进度条)")
    gos.add_argument("--workspace", default=None, help="工作区目录")
    gos.add_argument("--json", action="store_true", help="输出 JSON")
    gos.set_defaults(func="cmd_goal", goal_cmd="status")
    # steps
    gst = gosub.add_parser("steps", help="列出全部步骤 (重点突出未完成)")
    gst.add_argument("--workspace", default=None, help="工作区目录")
    gst.add_argument("--json", action="store_true", help="输出 JSON")
    gst.set_defaults(func="cmd_goal", goal_cmd="steps")

    # ---- loop (Loop系统可观测性, 第 54 个独特功能: 查询可用循环/当前激活者) ----
    p = sub.add_parser(
        "loop",
        help="Loop系统可观测性: 查询可用循环/当前激活者/切换预览 (Claude Code 无)",
    )
    p.set_defaults(func="cmd_loop", loop_cmd="list")
    lpsub = p.add_subparsers(dest="loop_cmd", required=False)
    lpl = lpsub.add_parser("list", help="列出可用循环 + 当前激活者 (默认)")
    lpl.add_argument("--json", action="store_true", help="输出 JSON")
    lpl.set_defaults(loop_cmd="list")
    lpc = lpsub.add_parser("current", help="查询当前激活循环")
    lpc.add_argument("--json", action="store_true", help="输出 JSON")
    lpc.set_defaults(loop_cmd="current")
    lpi = lpsub.add_parser("info", help="查看指定循环详情")
    lpi.add_argument("name", nargs="?", default=None, help="循环名 (默认当前)")
    lpi.add_argument("--json", action="store_true", help="输出 JSON")
    lpi.set_defaults(loop_cmd="info")
    # Loop 生命周期钩子: should_nudge/on_task_start/on_task_end (第 67 个独特功能)
    lph = lpsub.add_parser(
        "hooks", help="Loop 生命周期钩子 (should_nudge/on_task_start/on_task_end)"
    )
    lph.add_argument("--name", default=None, help="只看指定 Loop")
    lph.add_argument("--json", action="store_true", help="输出 JSON")
    lph.set_defaults(loop_cmd="hooks")
    # 完成标记集合 (第 76 个独特功能: 模型声明完成的标记可观测)
    lpm = lpsub.add_parser(
        "markers", help="循环完成标记 (DONE_MARKERS) + is_done 判定"
    )
    lpm.add_argument("--test", default=None, help="用真实回复测试完成判定")
    lpm.add_argument("--json", action="store_true", help="输出 JSON")
    lpm.set_defaults(loop_cmd="markers")
    p.add_argument("--json", action="store_true", help="输出 JSON")

    # ---- workflow (动态并行工作流可观测性, 第 81 个独特功能) ----
    pw = sub.add_parser(
        "workflow",
        help="动态并行工作流可观测性: 列表/状态/结果/取消/重试 (Claude Code 无)",
    )
    pw.set_defaults(func="cmd_workflow", workflow_cmd="list")
    wfsub = pw.add_subparsers(dest="workflow_cmd", required=False)
    wfl = wfsub.add_parser("list", help="列出全部工作流 (默认)")
    wfl.add_argument("--json", action="store_true", help="输出 JSON")
    wfl.set_defaults(workflow_cmd="list")
    wfs = wfsub.add_parser("status", help="查看指定工作流状态 (每步进度)")
    wfs.add_argument("workflow_id", help="工作流 ID")
    wfs.add_argument("--json", action="store_true", help="输出 JSON")
    wfs.set_defaults(workflow_cmd="status")
    wfr = wfsub.add_parser("result", help="查看工作流聚合结果报告")
    wfr.add_argument("workflow_id", help="工作流 ID")
    wfr.add_argument("--json", action="store_true", help="输出 JSON")
    wfr.set_defaults(workflow_cmd="result")
    wfc = wfsub.add_parser("cancel", help="取消工作流 (已结束则忽略)")
    wfc.add_argument("workflow_id", help="工作流 ID")
    wfc.add_argument("--json", action="store_true", help="输出 JSON")
    wfc.set_defaults(workflow_cmd="cancel")
    wfy = wfsub.add_parser("retry", help="重跑失败任务 (原地重试失败步)")
    wfy.add_argument("workflow_id", help="工作流 ID")
    wfy.add_argument("--json", action="store_true", help="输出 JSON")
    wfy.set_defaults(workflow_cmd="retry")
    wfa = wfsub.add_parser("archive",
                           help="只读巡查已持久化工作流实例 (第 123 个独特功能)")
    wfa.add_argument("--limit", type=int, default=0,
                     help="最多显示 N 条 (0=全部)")
    wfa.add_argument("--json", action="store_true", help="输出 JSON")
    wfa.set_defaults(workflow_cmd="archive")
    pw.add_argument("--json", action="store_true", help="输出 JSON")
