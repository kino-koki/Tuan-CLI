"""观测与协作命令: DAG / 聚合 / 验证 / 可观测性 / 协作 / 子 Agent / 远程 / 消息。

从 `parser_commands.py` 拆出的 `register_subcommands` 分片, 行为不变。
"""

from __future__ import annotations

from typing import Any
def register_observe_verify(sub: Any) -> None:
    """注册 observe_verify 域子命令。"""

    # ---- dag (任务依赖图可观测性, 第 46 个独特功能: 关键路径/波次/死锁检测) ----
    p = sub.add_parser(
        "dag",
        help="任务依赖图: 关键路径/调度波次/死锁检测 (Claude Code 无多Agent依赖调度概念)",
    )
    p.set_defaults(func="cmd_dag", dag_cmd="demo")
    dsub = p.add_subparsers(dest="dag_cmd", required=False)
    ddm = dsub.add_parser("demo", help="内置示例 DAG 演示 (默认)")
    ddm.add_argument("--json", action="store_true", help="输出 JSON")
    ddm.set_defaults(dag_cmd="demo")
    dpl = dsub.add_parser("plan", help="从任务计划文件加载并分析")
    dpl.add_argument("plan", help="任务计划 JSON 文件 (或 @file / 内联 JSON)")
    dpl.add_argument("--break", action="store_true", help="分析并自动打破循环依赖")
    dpl.add_argument("--json", action="store_true", help="输出 JSON")
    dpl.set_defaults(dag_cmd="plan")
    dck = dsub.add_parser("check", help="仅环检测 (CI 门禁)")
    dck.add_argument("plan", help="任务计划 JSON 文件")
    dck.add_argument("--json", action="store_true", help="输出 JSON")
    dck.set_defaults(dag_cmd="check")
    p.add_argument("--json", action="store_true", help="输出 JSON")

    # ---- aggregate (多Agent结果聚合可观测性, 第 47 个独特功能: 去重/冲突/质量决策审计) ----
    p = sub.add_parser(
        "aggregate",
        help="多Agent结果聚合: 去重/冲突检测/质量评估/优先级合并 (Claude Code 无聚合概念)",
    )
    p.set_defaults(func="cmd_aggregate", aggregate_cmd="demo")
    asub = p.add_subparsers(dest="aggregate_cmd", required=False)
    adm = asub.add_parser("demo", help="内置示例聚合演示 (默认)")
    adm.add_argument("--json", action="store_true", help="输出 JSON")
    adm.set_defaults(aggregate_cmd="demo")
    arn = asub.add_parser("run", help="从多Agent结果文件加载并聚合")
    arn.add_argument("results", help="结果 JSON 文件 (或 @file / 内联 JSON)")
    arn.add_argument("--json", action="store_true", help="输出 JSON")
    arn.set_defaults(aggregate_cmd="run")
    p.add_argument("--json", action="store_true", help="输出 JSON")

    # ---- verify (验证工具发现与反思诊断, 第 48 个独特功能: 结构化验证+失败诊断) ----
    p = sub.add_parser(
        "verify",
        help="验证工具发现与反思诊断: 结构化验证结果 + 失败诊断 (Claude Code 验证黑盒)",
    )
    p.set_defaults(func="cmd_verify", verify_cmd="detect")
    vsub = p.add_subparsers(dest="verify_cmd", required=False)
    vdt = vsub.add_parser("detect", help="检测工作区可用验证工具 (默认, 只读)")
    vdt.add_argument("--workspace", default=None, help="工作区目录 (默认当前目录)")
    vdt.add_argument("--json", action="store_true", help="输出 JSON")
    vdt.set_defaults(verify_cmd="detect")
    vrn = vsub.add_parser("run", help="运行单个验证工具")
    vrn.add_argument("tool", help="验证工具 (pytest/ruff/mypy/flake8/npm_test/eslint/go_test/cargo_test)")
    vrn.add_argument("--workspace", default=None, help="工作区目录 (默认当前目录)")
    vrn.add_argument("--json", action="store_true", help="输出 JSON")
    vrn.set_defaults(verify_cmd="run")
    val = vsub.add_parser("all", help="运行全部可用验证工具")
    val.add_argument("--tools", default=None, help="指定工具 (逗号分隔, 默认全部可用)")
    val.add_argument("--workspace", default=None, help="工作区目录 (默认当前目录)")
    val.add_argument("--json", action="store_true", help="输出 JSON")
    val.set_defaults(verify_cmd="all")
    vrf = vsub.add_parser("reflect", help="反思诊断: 运行验证并给出决策建议")
    vrf.add_argument("task", help="任务描述")
    vrf.add_argument("--last-output", default="", help="上一轮输出 (反思用)")
    # 可注入反思提示词生成 (第 66 个独特功能)
    vrf.add_argument("--prompt", action="store_true",
                     help="生成可注入 Agent 的反思提示词 (下一轮自我修正)")
    vrf.add_argument("--workspace", default=None, help="工作区目录 (默认当前目录)")
    vrf.add_argument("--json", action="store_true", help="输出 JSON")
    vrf.set_defaults(verify_cmd="reflect")
    p.add_argument("--json", action="store_true", help="输出 JSON")

    # ---- obs (可观测性与成本归因, 第 49 个独特功能: 跨进程成本/缓存命中率重建) ----
    p = sub.add_parser(
        "obs",
        help="可观测性与成本归因: 会话累计成本/DeepSeek缓存命中率/token构成 (Claude Code 黑盒)",
    )
    p.set_defaults(func="cmd_obs", obs_cmd="status")
    osub = p.add_subparsers(dest="obs_cmd", required=False)
    ost = osub.add_parser("status", help="可观测性状态 (默认)")
    ost.add_argument("--session", default="", help="会话ID (可前缀, 默认最新)")
    ost.add_argument("--json", action="store_true", help="输出 JSON")
    ost.set_defaults(obs_cmd="status")
    ocs = osub.add_parser("cost", help="从会话JSONL重建累计成本 (USD)")
    ocs.add_argument("--session", default="", help="会话ID (可前缀, 默认最新)")
    ocs.add_argument("--json", action="store_true", help="输出 JSON")
    ocs.set_defaults(obs_cmd="cost")
    occ = osub.add_parser("cache", help="DeepSeek前缀缓存命中率")
    occ.add_argument("--session", default="", help="会话ID (可前缀, 默认最新)")
    occ.add_argument("--json", action="store_true", help="输出 JSON")
    occ.set_defaults(obs_cmd="cache")
    p.add_argument("--json", action="store_true", help="输出 JSON")

    # ---- collab (多Agent协作协议黑板, 第 51 个独特功能: 结构化消息/路由/依赖/CAS冲突) ----
    p = sub.add_parser(
        "collab",
        help="多Agent协作协议黑板: 结构化消息/定向路由/依赖声明/CAS冲突检测/审计 (Claude Code 无)",
    )
    p.set_defaults(func="cmd_collab", collab_cmd="stats")
    csub = p.add_subparsers(dest="collab_cmd", required=False)
    cwr = csub.add_parser("write", help="写入黑板 (带版本控制+冲突检测)")
    cwr.add_argument("key", help="黑板 key")
    cwr.add_argument("value", help="写入值")
    cwr.add_argument("--sender", default=None, help="发送者 Agent ID")
    cwr.add_argument("--msg-type", default="result",
                     help="消息类型 (result/artifact/feedback/request/dependency/conflict/status/progress/error)")
    cwr.add_argument("--priority", default="normal",
                     help="优先级 (low/normal/high/urgent)")
    cwr.add_argument("--depends-on", default=None, help="依赖的 key 列表 (逗号分隔)")
    cwr.add_argument("--json", action="store_true", help="输出 JSON")
    cwr.set_defaults(collab_cmd="write")
    crd = csub.add_parser("read", help="读取黑板值")
    crd.add_argument("key", help="黑板 key")
    crd.add_argument("--requester", default=None, help="请求者 Agent ID")
    crd.add_argument("--json", action="store_true", help="输出 JSON")
    crd.set_defaults(collab_cmd="read")
    ccs = csub.add_parser("cas", help="CAS (Compare-And-Swap) 条件写入")
    ccs.add_argument("key", help="黑板 key")
    ccs.add_argument("version", help="期望的当前版本号")
    ccs.add_argument("value", help="新值")
    ccs.add_argument("--sender", default=None, help="发送者 Agent ID")
    ccs.add_argument("--json", action="store_true", help="输出 JSON")
    ccs.set_defaults(collab_cmd="cas")
    ccf = csub.add_parser("conflicts", help="冲突检测/解决")
    ccf.add_argument("--resolve", action="store_true", help="解决指定冲突")
    ccf.add_argument("--idx", type=int, default=0, help="冲突索引 (resolve 用)")
    ccf.add_argument("--value", default=None, help="解决值 (resolve 用)")
    ccf.add_argument("--resolver", default=None, help="解决者")
    ccf.add_argument("--auto", action="store_true", help="自动解决全部未解决冲突")
    ccf.add_argument("--strategy", default="last_write",
                     help="自动解决策略 (last_write/sender_priority)")
    ccf.add_argument("--json", action="store_true", help="输出 JSON")
    ccf.set_defaults(collab_cmd="conflicts")
    cmsg = csub.add_parser("messages", help="查询消息历史 (审计追溯)")
    cmsg.add_argument("--sender", default=None, help="按发送者筛选")
    cmsg.add_argument("--msg-type", default=None,
                      help="按消息类型筛选 (result/artifact/feedback/...)")
    cmsg.add_argument("--limit", type=int, default=20, help="条数 (默认 20)")
    cmsg.add_argument("--json", action="store_true", help="输出 JSON")
    cmsg.set_defaults(collab_cmd="messages")
    cst = csub.add_parser("stats", help="黑板统计 (默认)")
    cst.add_argument("--json", action="store_true", help="输出 JSON")
    cst.set_defaults(collab_cmd="stats")
    ccl = csub.add_parser("clear", help="清空黑板")
    ccl.add_argument("--json", action="store_true", help="输出 JSON")
    ccl.set_defaults(collab_cmd="clear")
    cdm = csub.add_parser("demo", help="内置三角色协作演示 (含一次冲突)")
    cdm.add_argument("--json", action="store_true", help="输出 JSON")
    cdm.set_defaults(collab_cmd="demo")
    # 黑板全量快照: get_all()/context_block() (第 61 个独特功能)
    csn = csub.add_parser(
        "snapshot", help="黑板全量快照 (所有 key + 版本 + 冲突标注)"
    )
    csn.add_argument("--raw", action="store_true",
                     help="输出原始全量 dict (JSON)")
    csn.add_argument("--context", action="store_true",
                     help="输出 Agent 可消费的快照文本 (context_block)")
    csn.add_argument("--json", action="store_true", help="输出 JSON")
    csn.set_defaults(collab_cmd="snapshot")
    p.add_argument("--json", action="store_true", help="输出 JSON")

    # ---- subagent (子Agent编排规划, 第 53 个独特功能: 任务拆分/汇总/隔离目录/配置预览) ----
    p = sub.add_parser(
        "subagent",
        help="子Agent编排规划: 任务拆分/结果汇总/隔离目录/配置预览 (Claude Code 无)",
    )
    p.set_defaults(func="cmd_subagent", subagent_cmd="config")
    sbsub = p.add_subparsers(dest="subagent_cmd", required=False)
    sbp = sbsub.add_parser("plan", help="从提示列表构建子任务计划 (隔离目录预览)")
    sbp.add_argument("--prompts", default=None,
                     help="提示列表, 用 | 分隔 (如 '调研A|调研B|调研C')")
    sbp.add_argument("--task", default=None, help="单任务提示")
    sbp.add_argument("--prefix", default="T", help="任务ID前缀 (默认 T)")
    sbp.add_argument("--workspace", default=None, help="工作区 (默认当前目录)")
    sbp.add_argument("--json", action="store_true", help="输出 JSON")
    sbp.set_defaults(subagent_cmd="plan")
    sba = sbsub.add_parser("aggregate", help="预览子Agent结果汇总 (含失败来源标注)")
    sba.add_argument("--results", default=None,
                     help="结果列表 (格式 T1=ok:文本;T2=fail:错误; 默认内置示例)")
    sba.add_argument("--title", default="子任务汇总", help="汇总标题")
    sba.add_argument("--json", action="store_true", help="输出 JSON")
    sba.set_defaults(subagent_cmd="aggregate")
    sbc = sbsub.add_parser("config", help="预览子Agent运行时配置 (默认)")
    sbc.add_argument("--json", action="store_true", help="输出 JSON")
    sbc.set_defaults(subagent_cmd="config")
    # 第 90 个独特功能: 子代理类型注册表可观测 (内置/自定义/能力边界)
    sbt = sbsub.add_parser("types",
                           help="子代理类型注册表: 内置/自定义 + 能力边界 (差异化)")
    sbt.add_argument("name", nargs="?", default=None, help="类型名 (详情)")
    sbt.add_argument("--json", action="store_true", help="输出 JSON")
    sbt.set_defaults(subagent_cmd="types")
    sbr = sbsub.add_parser("refresh", help="重新扫描自定义类型 (<home>/agents/*.md)")
    sbr.add_argument("--json", action="store_true", help="输出 JSON")
    sbr.set_defaults(subagent_cmd="refresh")
    p.add_argument("--json", action="store_true", help="输出 JSON")

    # ---- remote (远程控制会话可观测性, 第 91 个独特功能) ----
    p = sub.add_parser(
        "remote",
        help="远程控制会话可观测: 配对会话/连接状态/主动通知 (差异化)",
    )
    p.set_defaults(func="cmd_remote", remote_cmd="status")
    rsub = p.add_subparsers(dest="remote_cmd", required=False)
    rst = rsub.add_parser("status", help="远程配对会话状态 (默认)")
    rst.add_argument("session", nargs="?", default=None, help="会话 ID (详情)")
    rst.add_argument("--json", action="store_true", help="输出 JSON")
    rst.set_defaults(remote_cmd="status")
    rnt = rsub.add_parser("notify", help="主动推送测试通知 (验证推送通道)")
    rnt.add_argument("title", help="通知标题")
    rnt.add_argument("--body", default="", help="通知正文")
    rnt.add_argument("--json", action="store_true", help="输出 JSON")
    rnt.set_defaults(remote_cmd="notify")
    rcl = rsub.add_parser("clear", help="移除过期/失效会话记录 (清理盘上残留)")
    rcl.add_argument("session", help="会话 ID")
    rcl.add_argument("--json", action="store_true", help="输出 JSON")
    rcl.set_defaults(remote_cmd="clear")

    # ---- msg (跨会话消息总线可观测性, 第 92 个独特功能) ----
    p = sub.add_parser(
        "msg",
        help="跨会话消息总线: 活跃会话/收件箱/主动发送 (差异化, 纯只读查询)",
    )
    p.set_defaults(func="cmd_msg", msg_cmd="agents")
    msub = p.add_subparsers(dest="msg_cmd", required=False)
    mag = msub.add_parser("agents", help="活跃会话/代理清单 (默认)")
    mag.add_argument("--json", action="store_true", help="输出 JSON")
    mag.set_defaults(msg_cmd="agents")
    mib = msub.add_parser("inbox", help="读取某会话未读消息")
    mib.add_argument("session", help="会话 ID")
    mib.add_argument("--keep", action="store_true", help="不标记已读")
    mib.add_argument("--json", action="store_true", help="输出 JSON")
    mib.set_defaults(msg_cmd="inbox")
    msd = msub.add_parser("send", help="主动发送测试消息 (验证消息通道)")
    msd.add_argument("from_sid", help="来源会话")
    msd.add_argument("to_sid", help="目标会话")
    msd.add_argument("content", help="消息内容")
    msd.add_argument("--json", action="store_true", help="输出 JSON")
    msd.set_defaults(msg_cmd="send")
    mcl = msub.add_parser("cleanup", help="清理死会话/过期消息")
    mcl.add_argument("--json", action="store_true", help="输出 JSON")
    mcl.set_defaults(msg_cmd="cleanup")
    mar = msub.add_parser(
        "archive",
        help="只读巡查弃用跨会话消息归档 (第 124 个独特功能)",
    )
    mar.add_argument("--limit", type=int, default=0,
                     help="最多显示 N 个消息队列 (0=全部)")
    mar.add_argument("--json", action="store_true", help="输出 JSON")
    mar.set_defaults(msg_cmd="archive")
