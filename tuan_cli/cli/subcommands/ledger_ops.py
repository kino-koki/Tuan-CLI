"""账本与运维命令: checkpoint / handoff / ledger / 完整性 / 告警 / 存储 / 姿态。

从 `parser_commands.py` 拆出的 `register_subcommands` 分片, 行为不变。
"""

from __future__ import annotations

from typing import Any
def register_ledger_ops(sub: Any) -> None:
    """注册 ledger_ops 域子命令。"""

    # ---- checkpoint (自动检查点可观测性, 第 93 个独特功能) ----
    p = sub.add_parser(
        "checkpoint",
        help="自动检查点可观测: 清单/变更文件/恢复预览 (差异化, 纯只读)",
    )
    p.set_defaults(func="cmd_checkpoint", cp_cmd="list")
    p.add_argument("--workspace", default=None, help="工作区路径 (默认 cwd)")
    csub = p.add_subparsers(dest="cp_cmd", required=False)
    cls = csub.add_parser("list", help="检查点清单 (默认)")
    cls.add_argument("--workspace", default=None, help="工作区路径")
    cls.add_argument("--json", action="store_true", help="输出 JSON")
    cls.set_defaults(cp_cmd="list")
    csh = csub.add_parser("show", help="单个检查点详情")
    csh.add_argument("cp_id", help="检查点 ID")
    csh.add_argument("--workspace", default=None, help="工作区路径")
    csh.add_argument("--json", action="store_true", help="输出 JSON")
    csh.set_defaults(cp_cmd="show")
    cpr = csub.add_parser("prune", help="清理过期检查点 (只读, 不执行代码回滚)")
    cpr.add_argument("--workspace", default=None, help="工作区路径")
    cpr.add_argument("--json", action="store_true", help="输出 JSON")
    cpr.set_defaults(cp_cmd="prune")
    p.add_argument("--json", action="store_true", help="输出 JSON")

    # ---- handoff (会话交接历史可观测性, 第 95 个独特功能) ----
    ph = sub.add_parser(
        "handoff",
        help="会话交接历史可观测: 交接清单/谱系/配置 (差异化, 纯只读)",
    )
    ph.set_defaults(func="cmd_handoff", handoff_cmd="list")
    ph.add_argument("--workspace", default=None, help="工作区路径 (默认 cwd)")
    hsub = ph.add_subparsers(dest="handoff_cmd", required=False)
    hl = hsub.add_parser("list", help="交接历史清单 (默认)")
    hl.add_argument("--workspace", default=None, help="工作区路径")
    hl.add_argument("--json", action="store_true", help="输出 JSON")
    hl.set_defaults(handoff_cmd="list")
    hs = hsub.add_parser("show", help="单个交接详情")
    hs.add_argument("index", help="交接序号 (从 1 开始)")
    hs.add_argument("--workspace", default=None, help="工作区路径")
    hs.add_argument("--json", action="store_true", help="输出 JSON")
    hs.set_defaults(handoff_cmd="show")
    hc = hsub.add_parser("config", help="当前启用/阈值配置")
    hc.add_argument("--workspace", default=None, help="工作区路径")
    hc.add_argument("--json", action="store_true", help="输出 JSON")
    hc.set_defaults(handoff_cmd="config")
    ph.add_argument("--json", action="store_true", help="输出 JSON")

    # ---- ledger (操作账本可观测性, 第 96 个独特功能) ----
    pl = sub.add_parser(
        "ledger",
        help="操作账本可观测: 凭证清单/影响半径/检查点标记 (差异化, 纯只读)",
    )
    pl.set_defaults(func="cmd_ledger", ledger_cmd="list")
    pl.add_argument("--workspace", default=None, help="工作区路径 (默认 cwd)")
    lsub = pl.add_subparsers(dest="ledger_cmd", required=False)
    ll = lsub.add_parser("list", help="凭证清单 (默认)")
    ll.add_argument("--workspace", default=None, help="工作区路径")
    ll.add_argument("--json", action="store_true", help="输出 JSON")
    ll.set_defaults(ledger_cmd="list")
    ls = lsub.add_parser("stats", help="影响半径统计 (操作数/触及文件数)")
    ls.add_argument("--workspace", default=None, help="工作区路径")
    ls.add_argument("--json", action="store_true", help="输出 JSON")
    ls.set_defaults(ledger_cmd="stats")
    lm = lsub.add_parser("mark", help="当前变更记录数 (检查点标记, 只读)")
    lm.add_argument("--workspace", default=None, help="工作区路径")
    lm.add_argument("--json", action="store_true", help="输出 JSON")
    lm.set_defaults(ledger_cmd="mark")
    pl.add_argument("--json", action="store_true", help="输出 JSON")

    # ---- integrity (文件完整性可观测性, 第 97 个独特功能, 纯只读) ----
    pi = sub.add_parser(
        "integrity",
        help="文件完整性可观测: 变更历史/统计/报告 (差异化, 纯只读)",
    )
    pi.set_defaults(func="cmd_integrity", integrity_cmd="overview")
    pi.add_argument("--home", default=None, help="TUAN home 目录 (默认 ~/.tuan)")
    pi.add_argument("--json", action="store_true", help="输出 JSON")
    isub2 = pi.add_subparsers(dest="integrity_cmd", required=False)
    iov = isub2.add_parser("overview", help="概览: 统计 + 最近变更 (默认)")
    iov.add_argument("--home", default=None, help="TUAN home 目录")
    iov.add_argument("--last", type=int, default=10, help="最近 N 条变更 (默认 10)")
    iov.add_argument("--json", action="store_true", help="输出 JSON")
    iov.set_defaults(integrity_cmd="overview")
    ich = isub2.add_parser("changes", help="变更历史查询 (可过滤)")
    ich.add_argument("--severity", default=None, help="按严重度过滤 (high/medium/low/critical)")
    ich.add_argument("--change-type", default=None, help="按类型过滤 (added/modified/deleted/permissions_changed)")
    ich.add_argument("--path-pattern", default=None, help="按路径 glob 过滤 (如 '*.py')")
    ich.add_argument("--last", type=int, default=100, help="最近 N 条 (默认 100)")
    ich.add_argument("--home", default=None, help="TUAN home 目录")
    ich.add_argument("--json", action="store_true", help="输出 JSON")
    ich.set_defaults(integrity_cmd="changes")
    ist = isub2.add_parser("stats", help="变更统计 (总数/按类型/按严重度)")
    ist.add_argument("--home", default=None, help="TUAN home 目录")
    ist.add_argument("--json", action="store_true", help="输出 JSON")
    ist.set_defaults(integrity_cmd="stats")
    irp = isub2.add_parser("report", help="导出 Markdown 完整性报告")
    irp.add_argument("--last", type=int, default=50, help="报告含最近 N 条 (默认 50)")
    irp.add_argument("--home", default=None, help="TUAN home 目录")
    irp.set_defaults(integrity_cmd="report")

    # ---- alerts (持久化安全告警可观测性, 第 98 个独特功能, 纯只读) ----
    pa = sub.add_parser(
        "alerts",
        help="持久化安全告警: 跨进程 JSONL 回溯 (差异化, 纯只读)",
    )
    pa.set_defaults(func="cmd_alerts", alerts_cmd="list")
    pa.add_argument("--home", default=None, help="TUAN home 目录 (默认 ~/.tuan)")
    pa.add_argument("--last", type=int, default=50, help="最近 N 条 (默认 50)")
    pa.add_argument("--severity", default=None, help="按严重度过滤 (critical/high/medium/low)")
    pa.add_argument("--source", default=None, help="按来源过滤 (如 mcp_security)")
    pa.add_argument("--json", action="store_true", help="输出 JSON")
    asub2 = pa.add_subparsers(dest="alerts_cmd", required=False)
    als = asub2.add_parser("list", help="最近告警明细 (默认)")
    als.add_argument("--home", default=None, help="TUAN home 目录")
    als.add_argument("--last", type=int, default=50, help="最近 N 条 (默认 50)")
    als.add_argument("--severity", default=None, help="按严重度过滤")
    als.add_argument("--source", default=None, help="按来源过滤")
    als.add_argument("--json", action="store_true", help="输出 JSON")
    als.set_defaults(alerts_cmd="list")
    ast = asub2.add_parser("stats", help="持久化告警统计 (总数/按严重度/按来源)")
    ast.add_argument("--home", default=None, help="TUAN home 目录")
    ast.add_argument("--json", action="store_true", help="输出 JSON")
    ast.set_defaults(alerts_cmd="stats")
    arp = asub2.add_parser("report", help="导出 Markdown 告警报告")
    arp.add_argument("--last", type=int, default=100, help="报告含最近 N 条 (默认 100)")
    arp.add_argument("--home", default=None, help="TUAN home 目录")
    arp.set_defaults(alerts_cmd="report")

    # ---- storage (持久化占用可观测性, 第 100 个独特功能, 纯只读) ----
    pst = sub.add_parser(
        "storage",
        help="持久化占用报表: 各子系统磁盘用量 (差异化, 纯只读)",
    )
    pst.set_defaults(func="cmd_storage", storage_cmd="overview")
    pst.add_argument("--home", default=None, help="TUAN home 目录 (默认 ~/.tuan)")
    pst.add_argument("--json", action="store_true", help="输出 JSON")
    stsub = pst.add_subparsers(dest="storage_cmd", required=False)
    stov = stsub.add_parser("overview", help="各子系统占用概览 (默认)")
    stov.add_argument("--home", default=None, help="TUAN home 目录")
    stov.add_argument("--json", action="store_true", help="输出 JSON")
    stov.set_defaults(storage_cmd="overview")
    sttop = stsub.add_parser("top", help="全局最大的 N 个文件")
    sttop.add_argument("--n", type=int, default=20, help="数量 (默认 20)")
    sttop.add_argument("--home", default=None, help="TUAN home 目录")
    sttop.add_argument("--json", action="store_true", help="输出 JSON")
    sttop.set_defaults(storage_cmd="top")
    sttree = stsub.add_parser("tree", help="下钻: 子系统内最大的文件")
    sttree.add_argument("subsystem", help="子系统目录名 (如 sessions / checkpoints)")
    sttree.add_argument("--home", default=None, help="TUAN home 目录")
    sttree.set_defaults(storage_cmd="tree")

    # ---- posture (跨子系统健康总览, 第 101 个独特功能, 纯只读) ----
    ppo = sub.add_parser(
        "posture",
        help="跨子系统安全/韧性健康总览 (差异化, 纯只读)",
    )
    ppo.add_argument("--home", default=None, help="TUAN home 目录 (默认 ~/.tuan)")
    ppo.add_argument("--json", action="store_true", help="输出 JSON")
    ppo.set_defaults(func="cmd_posture")
