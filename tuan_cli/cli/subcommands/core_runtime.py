"""核心运行时命令: ACP / Web 工作台 / 快速索引 / 开发循环 / headless run / 调度与命名 Agent / 后台 / 配置向导 / 体检 / 离线。

从 `parser_commands.py` 拆出的 `register_subcommands` 分片, 行为不变。
"""

from __future__ import annotations

import argparse
from typing import Any

from ._common import _DISPATCH_MODES
def register_core_runtime(sub: Any) -> None:
    """注册 core_runtime 域子命令。"""

    p = sub.add_parser(
        "acp",
        help="以 Agent Client Protocol server 运行, 供 IDE (VS Code/Zed/JetBrains) 驱动",
    )
    p.add_argument(
        "--login",
        action="store_true",
        help="执行终端鉴权后退出 (ACP 客户端触发的 AuthMethodTerminal 入口)",
    )
    p.add_argument("--workspace", help="工作区目录 (默认当前目录)")
    p.set_defaults(func="cmd_acp")

    pw = sub.add_parser(
        "web", help="本地 Web 工作台: 启动服务 (DeepSeek-harness 风格) 或只读体检持久化状态"
    )
    pw.add_argument("--host", default=None, help="监听地址 (默认 127.0.0.1)")
    pw.add_argument("--port", type=int, default=0, help="监听端口 (默认 8090)")
    pw.add_argument("--workspace", default=None, help="工作区路径 (默认当前目录)")
    pw.set_defaults(func="cmd_web")
    pwsub = pw.add_subparsers(dest="web_cmd", required=False)
    # audit (只读体检, 第 115 个独特功能)
    pw_a = pwsub.add_parser("audit", help="只读体检 Web 工作台持久化状态 (会话快照/用户偏好)")
    pw_a.add_argument("--workspace", default=None, help="工作区目录")
    pw_a.add_argument("--json", action="store_true", help="输出 JSON")
    pw_a.set_defaults(func="cmd_web_audit", web_audit_cmd="all")
    pw_asub = pw_a.add_subparsers(dest="web_audit_cmd", required=False)
    pw_as = pw_asub.add_parser("sessions", help="只列 Web 会话")
    pw_as.add_argument("--workspace", default=None, help="工作区目录")
    pw_as.add_argument("--json", action="store_true", help="输出 JSON")
    pw_as.set_defaults(func="cmd_web_audit", web_audit_cmd="sessions")
    pw_aset = pw_asub.add_parser("settings", help="只看用户偏好")
    pw_aset.add_argument("--workspace", default=None, help="工作区目录")
    pw_aset.add_argument("--json", action="store_true", help="输出 JSON")
    pw_aset.set_defaults(func="cmd_web_audit", web_audit_cmd="settings")

    # ---- fastindex (持久化快速文件索引只读体检, 第 116 个独特功能, 纯只读) ----
    fi = sub.add_parser(
        "fastindex", help="持久化快速文件索引只读体检: 覆盖率/语言分布/符号密度"
    )
    fi.add_argument("--workspace", default=None, help="工作区目录 (默认 TUAN_WORKSPACE/当前)")
    fi.add_argument("--json", action="store_true", help="输出 JSON")
    fi.set_defaults(func="cmd_fastindex", fastindex_cmd="stats")
    fisub = fi.add_subparsers(dest="fastindex_cmd", required=False)
    # files (按符号数排名)
    fif = fisub.add_parser("files", help="按符号数/体积排名列出索引文件")
    fif.add_argument("--workspace", default=None, help="工作区目录")
    fif.add_argument("--limit", type=int, default=0, help="最多 N 个文件 (0=全部)")
    fif.add_argument("--json", action="store_true", help="输出 JSON")
    fif.set_defaults(func="cmd_fastindex", fastindex_cmd="files")

    p = sub.add_parser(
        "dev", help="自主开发循环 (分析→实现→自测→核实→汇报, 直到你满意)"
    )
    p.add_argument("task", help="开发任务描述")
    p.add_argument("--model", help="临时覆盖模型名")
    p.add_argument(
        "--mode",
        choices=[
            "standard", "yolo", "plan",
            "gantong", "lingma", "chat", "boundless", "collaboration",
        ],
        help="临时切换运行模式 (旧三档 standard/yolo/plan 或五模式 "
             "gantong/lingma/chat/boundless/collaboration)",
    )
    p.add_argument(
        "--permission-mode",
        choices=[
            "default",
            "acceptEdits",
            "plan",
            "auto",
            "dontAsk",
            "bypassPermissions",
        ],
        dest="permission_mode",
        default=argparse.SUPPRESS,
        help="Claude Code 风格权限模式",
    )

    p.add_argument(
        "--effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        help="推理投入级别 (low/medium/high/xhigh/max)",
    )
    p.set_defaults(func="cmd_dev")

    p = sub.add_parser("run", help="headless 一次性任务")
    p.add_argument(
        "task",
        nargs="?",
        default="",
        help="任务描述 (可省略: stdin 为管道时读取 stdin 作为任务)",
    )
    p.add_argument(
        "-p",
        "--print",
        action="store_true",
        dest="print_mode",
        help="简洁 headless 模式: 不进 TUI/不打印横幅装饰, 纯文本流式输出到 stdout (stderr 仅错误), 退出码 0=成功 1=失败",
    )
    p.add_argument(
        "--output-format",
        dest="output_format",
        choices=["text", "json", "stream-json"],
        default="text",
        help="输出格式: text(默认纯文本) / json(每行一个 NDJSON 事件: "
             "text/tool_call/tool_result/thinking/finish) / "
             "stream-json(Claude Code 消息级事件流: system/init, assistant, user, result)",
    )
    p.add_argument(
        "--bare",
        action="store_true",
        help="CI/纯净模式: 仅用内置默认配置+内置工具, 跳过用户配置/skills/hooks/MCP/memory自动注入",
    )
    p.add_argument(
        "--yes", "-y", action="store_true",
        help="自动批准通常需确认的操作;硬红线仍阻止 (等同于 --mode yolo)",
    )
    p.add_argument("--no-stream", action="store_true", help="关闭流式输出")
    p.add_argument(
        "--bg", action="store_true", help="后台运行, 不阻塞终端 (用 tuan bg 查看进度)"
    )
    p.add_argument("--model", help="临时覆盖模型名")
    p.add_argument(
        "--mode",
        choices=[
            "standard", "yolo", "plan",
            "gantong", "lingma", "chat", "boundless", "collaboration",
        ],
        help="临时切换运行模式 (旧三档 standard/yolo/plan 或五模式 "
             "gantong/lingma/chat/boundless/collaboration)",
    )
    p.add_argument(
        "--permission-mode",
        choices=[
            "default",
            "acceptEdits",
            "plan",
            "auto",
            "dontAsk",
            "bypassPermissions",
        ],
        dest="permission_mode",
        default=argparse.SUPPRESS,
        help="Claude Code 风格权限模式",
    )
    p.add_argument(
        "--effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        help="推理投入级别 (low/medium/high/xhigh/max)",
    )
    p.add_argument(
        "--max-turns",
        type=int,
        default=0,
        dest="max_turns",
        help="限制代理交互轮数上限 (对应 Claude Code --max-turns; 0=不限)",
    )
    p.add_argument(
        "--allowed-tools",
        dest="allowed_tools",
        help="Claude Code 风格免确认工具/作用域: 如 'Bash(npm test),Read,Write'",
    )
    p.add_argument(
        "--disallowed-tools",
        dest="disallowed_tools",
        help="会话级工具黑名单 (逗号分隔; 对标 Claude Code --disallowedTools)",
    )
    p.add_argument(
        "--add-dir",
        dest="add_dir",
        action="append",
        default=None,
        metavar="DIR",
        help="额外可读目录, 可重复 (对标 Claude Code --add-dir)",
    )
    p.add_argument(
        "--settings",
        dest="settings",
        metavar="FILE",
        help="Claude Code 风格 settings.json (会话级生效, 不写盘)",
    )
    p.add_argument(
        "--max-cost",
        type=float,
        default=0.0,
        help="最大花费上限 (USD), 超过自动停止; 0=不限制",
    )
    p.add_argument(
        "--json-schema",
        dest="json_schema",
        default=None,
        metavar="SPEC",
        help="结构化输出: 要求最终回答符合给定 JSON Schema (内联 JSON 或 @file.json)",
    )
    p.add_argument(
        "--json-schema-strict",
        dest="json_schema_strict",
        action="store_true",
        help="--json-schema 严格模式: 回答必须仅含合法 JSON",
    )
    p.add_argument(
        "--json-schema-retries",
        dest="json_schema_retries",
        type=int,
        default=3,
        help="--json-schema 校验失败时的自动修复重试次数 (默认 3)",
    )
    p.add_argument(
        "--resume",
        "--continue",
        dest="resume",
        nargs="?",
        const="latest",
        default=None,
        metavar="会话ID|编号|latest",
        help="headless 续会话: 恢复指定历史会话上下文后再跑一轮 "
             "省略值=最近一个). 找不到会话时以非 0 退出码失败",
    )
    p.add_argument(
        "--append-system-prompt",
        dest="append_system_prompt",
        default=None,
        metavar="TEXT",
        help="在系统提示末尾追加一段文本 (CI 场景注入"
             " 额外约束/角色说明, 不改写原系统提示)",
    )
    p.add_argument(
        "--append-user-prompt",
        dest="append_user_prompt",
        default=None,
        metavar="TEXT",
        help="在用户任务末尾追加一段文本 (例如固定补上"
             "  '请用 JSON 输出')",
    )
    p.add_argument(
        "--session-id",
        dest="session_id",
        default=None,
        metavar="ID",
        help="指定本次 headless 会话 ID (CI 多步流水线里手工"
             " 命名会话, 便于后续 tuan session resume / replay 定位)",
    )
    p.set_defaults(func="cmd_run")

    p = sub.add_parser(
        "dispatch",
        help="Agent-of-Agents 调度层: 探测本机代理 / dry-run 路由 / 派活 / 启动调度服务器",
    )
    dsub = p.add_subparsers(dest="dispatch_cmd")
    dst = dsub.add_parser("status", help="探测本机 5 家本地代理 (默认子命令)")
    dst.add_argument("agent_id", nargs="?", help="只探测指定代理 id (省略=全部 5 家)")
    dst.add_argument("--format", choices=("text", "json"), default="text", help="输出格式: text|json (默认 text)")
    dst.set_defaults(func="cmd_dispatch")
    dls = dsub.add_parser("list", help="status 的别名")
    dls.add_argument("agent_id", nargs="?", help="只探测指定代理 id (省略=全部 5 家)")
    dls.add_argument("--format", choices=("text", "json"), default="text", help="输出格式: text|json (默认 text)")
    dls.set_defaults(func="cmd_dispatch")
    dr = dsub.add_parser("route", help="dry-run: 打分明细, 不执行")
    dr.add_argument("prompt", help="任务提示词 (仅用于路由判定)")
    dr.add_argument("--agent", help="显式指定代理 id (默认 auto)")
    dr.add_argument("--mode", choices=_DISPATCH_MODES, help="运行模式 (默认 chat)")
    dr.add_argument("--format", choices=("text", "json"), default="text", help="输出格式: text|json (默认 text)")
    dr.set_defaults(func="cmd_dispatch")
    dn = dsub.add_parser("run", help="实际派活: 路由 → 流式执行 → 汇总")
    dn.add_argument("prompt", help="任务提示词")
    dn.add_argument("--agent", help="显式指定代理 id (默认 auto)")
    dn.add_argument("--mode", choices=_DISPATCH_MODES, help="运行模式 (默认 chat)")
    dn.add_argument("--cwd", help="工作目录 (默认当前目录)")
    dn.add_argument("--timeout", type=int, default=600, help="超时秒数 (默认 600)")
    dn.add_argument("--format", choices=("text", "json"), default="text", help="输出格式: text|json (默认 text)")
    dn.set_defaults(func="cmd_dispatch")
    ds = dsub.add_parser("serve", help="启动 WebSocket 调度服务器 (手机/浏览器遥控)")
    ds.add_argument("--host", default="127.0.0.1", help="监听地址 (默认 127.0.0.1)")
    ds.add_argument("--port", type=int, default=8788, help="监听端口 (默认 8788)")
    ds.add_argument("--format", choices=("text", "json"), default="text", help="输出格式: text|json (默认 text)")
    ds.set_defaults(func="cmd_dispatch")
    # --- dispatch audit (派发-审批审计只读体检, 第 121 个独特功能) ---
    da = dsub.add_parser("audit", help="只读体检 dispatch 审计日志 (配对/派活/审批链路)")
    da.add_argument("--limit", type=int, default=20, help="只显示最近 N 条 (默认 20, 0=全部)")
    da.add_argument("--json", action="store_true", help="输出 JSON")
    da.set_defaults(func="cmd_dispatch")
    # 父级也挂一份: `tuan dispatch --format json status` 亦可 (子命令位优先)。
    p.add_argument("--format", choices=("text", "json"), default="text", help="输出格式: text|json (默认 text)")
    p.set_defaults(func="cmd_dispatch")

    p = sub.add_parser("agent", help="后台自主任务 (终端不阻塞, 青小团自己在后台干活)")
    p.add_argument("task", help="任务描述")
    p.add_argument(
        "--yes", "-y", action="store_true",
        help="自动批准通常需确认的操作;硬红线仍阻止 (等同于 --mode yolo)",
    )
    p.add_argument(
        "--wait",
        action="store_true",
        help="提交后阻塞等待任务结束 (等价于 run --bg + 等待)",
    )
    p.add_argument("--model", help="临时覆盖模型名")
    p.add_argument(
        "--mode",
        choices=[
            "standard", "yolo", "plan",
            "gantong", "lingma", "chat", "boundless", "collaboration",
        ],
        help="临时切换运行模式 (旧三档 standard/yolo/plan 或五模式 "
             "gantong/lingma/chat/boundless/collaboration)",
    )
    p.set_defaults(func="cmd_agent")

    p = sub.add_parser("bg", help="后台任务管理 (list / logs / cancel / wait)")
    bgsub = p.add_subparsers(dest="bg_cmd", required=True)
    bgsub.add_parser("list", help="列出后台任务")
    lg = bgsub.add_parser("logs", help="查看某后台任务的进展")
    lg.add_argument("job_id", help="后台任务 ID")
    lg.add_argument("--tail", type=int, default=15, help="显示最近 N 条")
    # 可恢复队列 (第 75 个独特功能: 暴露 queued 但 worker 已退出的可安全重启任务)
    rec = bgsub.add_parser("recover", help="列出可恢复重启的后台任务 (queued 且无存活 worker)")
    rec.add_argument("--json", action="store_true", help="结构化输出 (CI / 审计)")
    c = bgsub.add_parser("cancel", help="取消正在运行的后台任务")
    c.add_argument("job_id")
    w = bgsub.add_parser("wait", help="阻塞等待某后台任务结束")
    w.add_argument("job_id")
    w.add_argument("--timeout", type=float, default=0, help="最长等待秒数 (0=不限)")
    sh = bgsub.add_parser("shell", help="管理用 `! 命令` 启动的后台 shell 任务")
    sh.add_argument(
        "action",
        choices=["list", "status", "logs", "wait", "cancel", "prune"],
        help="操作",
    )
    sh.add_argument("job_id", nargs="?", default="", help="后台 shell 任务 ID")
    sh.add_argument("--tail", type=int, default=20, help="logs/wait 取输出的行数")
    sh.add_argument("--offset", type=int, default=0, help="logs 增量跟随游标")
    sh.add_argument(
        "--timeout", type=float, default=0, help="wait 最长等待秒数 (0=不限)"
    )
    p.set_defaults(func="cmd_bg")

    p = sub.add_parser("setup", help="初始化向导 (Hermes 风格: 快速/完整/空白)")
    p.add_argument(
        "--quick", action="store_true", help="跳过模式选择, 直接进入快速设置"
    )
    p.add_argument(
        "--skip", action="store_true",
        help="跳过向导并写入完成标记 (脚本/CI 友好; 等价环境变量 TUAN_SKIP_SETUP=1)",
    )
    p.set_defaults(func="cmd_setup")
    pd = sub.add_parser(
        "doctor", help="环境健康检查 (配置/技能/项目指令/环境/缓存/网络/压缩存活)"
    )
    pd.add_argument(
        "--fix",
        action="store_true",
        help="自动修复可修复问题 (建目录/补 frontmatter 占位)",
    )
    pd.add_argument(
        "--json", dest="json", action="store_true", help="输出 JSON 供脚本消费"
    )
    pd.add_argument(
        "--network", action="store_true", help="额外探测 API endpoint 可达性"
    )
    pd.add_argument(
        "--compact",
        action="store_true",
        help="额外跑上下文压缩存活自检 (SOUL/项目指令/MEMORY.md/Git/技能/todo/goal 能否从磁盘重建)",
    )
    pdcw = pd.add_argument(
        "--workspace", default=None, help="指定工作区 (默认当前目录, --compact 时用)"
    )
    pd.set_defaults(func="cmd_doctor")

    # 离线/本地优先态势 (独特能力: 本地优先, 断网自动降级)
    po = sub.add_parser(
        "offline", help="离线/本地优先态势: 网络探测 / 降级状态 / 本地模型库存"
    )
    po.set_defaults(func="cmd_offline", offline_cmd="status")
    po_sub = po.add_subparsers(dest="offline_cmd", required=False)
    po_sub.add_parser("status", help="综合态势: 网络/降级/本地模型").set_defaults(
        offline_cmd="status"
    )
    prou = po_sub.add_parser("route", help="降级决策预览 (不实际切换)")
    prou.add_argument("--tree", action="store_true",
                      help="渲染决策树可视化 (差异化: 完整分支/条件/结论)")
    prou.add_argument("--json", action="store_true",
                      help="结构化输出 (分支 + 条件 + 结论, CI 消费)")
    prou.set_defaults(offline_cmd="route")
    po_sub.add_parser("models", help="本机本地模型清单").set_defaults(
        offline_cmd="models"
    )
    po_sub.add_parser("doctor", help="离线链路逐项自检 (排障)").set_defaults(
        offline_cmd="doctor"
    )
    ppull = po_sub.add_parser("pull", help="下载本地模型 (Ollama, 实时进度)")
    ppull.add_argument("model", help="模型名 (如 qwen2.5:7b)")
    ppull.set_defaults(offline_cmd="pull")
    pverify = po_sub.add_parser("verify", help="校验已装模型完整性 (供应链防投毒)")
    pverify.add_argument("--json", action="store_true", help="结构化输出 (CI/审计)")
    pverify.set_defaults(offline_cmd="verify")
    # 强制真实网络探测: 绕过进程内缓存 (第 59 个独特功能)
    pprobe = po_sub.add_parser(
        "probe", help="强制网络探测 (绕过缓存, 真实 IO 含 DNS)"
    )
    pprobe.add_argument(
        "--timeout", type=float, default=3.0, help="单端点超时秒 (默认 3)"
    )
    pprobe.add_argument("--json", action="store_true", help="结构化输出 (CI 判定)")
    pprobe.set_defaults(offline_cmd="probe")
