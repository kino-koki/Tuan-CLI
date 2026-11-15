"""安全命令行: safe (基准/报告/审计/红队扫描) / gh / tutorial / sandbox / harden。

从 `parser_commands.py` 拆出的 `register_subcommands` 分片, 行为不变。
"""

from __future__ import annotations

import argparse
from typing import Any
def register_safety_cli(sub: Any) -> None:
    """注册 safety_cli 域子命令。"""

    p = sub.add_parser("safe", help="安全总入口: 白名单 / 本地黑名单减负 / 状态 / 更新")
    ssub = p.add_subparsers(dest="safe_cmd", required=False)
    ssub.add_parser("status", help="安全系统状态 + 审计概览").set_defaults(
        safe_cmd="status"
    )
    ssub.add_parser("list", help="列出白名单").set_defaults(safe_cmd="list")
    sa = ssub.add_parser("allow", help="把命令加入白名单 (用户在本地自主添加)")
    sa.add_argument("command", help="要加入白名单的命令")
    sa.add_argument("--description", help="描述 (可选)")
    sa.set_defaults(safe_cmd="allow")
    sd = ssub.add_parser("deny", help="从白名单移除命令")
    sd.add_argument("command", help="要移除的命令")
    sd.set_defaults(safe_cmd="deny")
    # 白名单/红线判定: 预先确认命令的免确认执行 (第 74 个独特功能)
    sc = ssub.add_parser("check", help="判定命令的免确认策略 (白名单/红线)")
    sc.add_argument("command", help="要判定的命令")
    sc.add_argument("--json", action="store_true", help="输出 JSON")
    sc.set_defaults(safe_cmd="check")
    # 命令警告级别预判 (第 80 个独特功能: 弹窗次数可观测)
    sw = ssub.add_parser("warn", help="命令警告级别预判 (0/3/5 次确认)")
    sw.add_argument("command", help="要判定的命令")
    sw.add_argument("--json", action="store_true", help="输出 JSON")
    sw.set_defaults(safe_cmd="warn")
    ssub.add_parser("blacklist", help="列出内置黑名单模式 (标注已减负)").set_defaults(
        safe_cmd="blacklist"
    )
    sr = ssub.add_parser("reduce", help="抑制匹配关键字的黑名单模式 (本地减负)")
    sr.add_argument(
        "keyword", help="黑名单模式 label 关键字 (如 dd / format / shutdown)"
    )
    sr.set_defaults(safe_cmd="reduce")
    sre = ssub.add_parser("restore", help="恢复被抑制的黑名单模式")
    sre.add_argument("keyword", help="之前 reduce 的关键字")
    sre.set_defaults(safe_cmd="restore")
    ssub.add_parser("update", help="更新安全策略 (月度检查)").set_defaults(
        safe_cmd="update"
    )
    ss = ssub.add_parser("suggest", help="对一条命令给出安全替代建议 (命令感知)")
    ss.add_argument("command", help="要评估的命令")
    ss.set_defaults(safe_cmd="suggest")
    sb = ssub.add_parser(
        "bench", help="一键复现安全基准 (对抗样本 / PowerShell / 绕过矩阵)"
    )
    sb.add_argument(
        "--quick", action="store_true", help="快速模式 (2000 条对抗样本, ~30s)"
    )
    sb.add_argument(
        "--check",
        action="store_true",
        help="跑完后与存档对比: 安全指标变差即退出码 1 (回归门禁)",
    )
    sb.add_argument(
        "--full",
        action="store_true",
        help="全量跑完后输出数字漂移报告 (本跑 vs 存档, 每个指标旧值→新值→Δ)",
    )
    sb.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help="汇总 JSON 输出路径 (默认 bench/security-bench.json)",
    )
    sb.add_argument(
        "--json",
        action="store_true",
        help="机器可读模式 (CI): 人类可读日志改走 stderr, stdout 只输出汇总 JSON;"
        " 全量模式同时把结果追加到 bench/results/ 时间序列存档",
    )
    sb.set_defaults(safe_cmd="bench")
    srp = ssub.add_parser(
        "report", help="生成安全状态 HTML 报告 (宣传 / 审计 / 交接用)"
    )
    srp.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help="HTML 输出路径 (默认 security-report.html)",
    )
    srp.add_argument(
        "--release",
        action="store_true",
        help="RELEASE 版: 数字与对应 git 提交三方绑定 (防数字过期)",
    )
    srp.set_defaults(safe_cmd="report")
    # 安全审计可视入口: 完整性校验 / 关联告警 / 统计 / 导出
    sau = ssub.add_parser(
        "audit", help="安全审计可视化: 完整性校验 / 关联告警 / 统计 / 导出"
    )
    sau.add_argument("--last", type=int, default=50, help="最近 N 条 (默认 50)")
    sau.add_argument("--module", default=None, help="按模块过滤")
    sau.add_argument("--severity", default=None, help="按严重度过滤 (info/warn/critical)")
    sau.add_argument(
        "--verify-only", action="store_true", help="只跑防篡改链完整性校验"
    )
    sau.add_argument(
        "--export", choices=["md", "json", "jsonl"], default=None,
        help="导出格式 (jsonl 供 SIEM 消费)",
    )
    sau.add_argument(
        "--flush", action="store_true",
        help="强制刷盘 SecurityBus 事件 (审计日志完整落盘)",
    )
    sau.add_argument(
        "--clear", action="store_true",
        help="清空 SecurityBus 内存事件 (审计链不受影响)",
    )
    sau.set_defaults(safe_cmd="audit")
    # 红队自检: 用内置对抗载荷验证安全引擎拦截率 (只读, 不执行危险命令)
    srt = ssub.add_parser(
        "redteam", help="红队自检: 用对抗载荷验证拦截率 (只读, 不执行危险命令)"
    )
    srt.add_argument("--list", action="store_true", help="只列出红队载荷分类 (不执行)")
    srt.add_argument("--json", action="store_true", help="机器可读 JSON 汇总 (CI)")
    srt.add_argument(
        "--category", default=None,
        help="只跑指定载荷分类 (如 '破坏性命令'); 默认全部",
    )
    srt.set_defaults(safe_cmd="redteam")
    # 密钥泄露扫描: 纯本地扫描目录文本中的明文密钥 (离线, 不依赖漏洞库)
    ssc = ssub.add_parser(
        "scan", help="密钥泄露扫描: 纯本地扫明文 API Key/私钥, 给出修复建议"
    )
    ssc.add_argument(
        "path", nargs="?", default=None, help="要扫描的目录 (默认当前目录)"
    )
    ssc.add_argument("--file", default=None, help="只扫单个文件 (优先于 path)")
    ssc.add_argument("--json", action="store_true", help="机器可读 JSON (CI/SIEM)")
    ssc.add_argument(
        "--max-files", type=int, default=2000,
        dest="max_files", help="限制扫描文件数 (默认 2000)",
    )
    ssc.add_argument(
        "--no-skip-dirs", action="store_true", dest="no_skip_dirs",
        help="不跳过 .git/node_modules/.venv 等 (慎用, 会扫出依赖噪声)",
    )
    ssc.set_defaults(safe_cmd="scan")
    # 关键文件完整性监控: 对配置/脚本/技能目录建快照并检测篡改
    sin = ssub.add_parser(
        "integrity", help="文件完整性监控: 关键文件防篡改 (快照/检测/报告)"
    )
    isub = sin.add_subparsers(dest="integrity_cmd", required=False)
    isnap = isub.add_parser("snapshot", help="对目录建完整性快照 (首次基准)")
    isnap.add_argument("target", help="要快照的目录")
    isnap.add_argument("--label", default="", help="快照标签 (区分不同目录)")
    isnap.set_defaults(safe_cmd="integrity")
    icheck = isub.add_parser("check", help="对比快照检测变更 (篡改)")
    icheck.add_argument("target", help="要检查的目录")
    icheck.add_argument("--label", default="", help="快照标签 (与 snapshot 一致)")
    icheck.set_defaults(safe_cmd="integrity")
    sin.add_argument("--report", action="store_true", help="导出 Markdown 报告")
    sin.add_argument("--last", type=int, default=50, help="最近 N 条变更 (默认 50)")
    sin.add_argument("--severity", default=None, help="按严重度过滤 (high/medium/low)")
    sin.set_defaults(safe_cmd="integrity")
    # 路径安全校验: 检测 ../ 逃逸 / 符号链接逃逸 / 系统目录访问 / 敏感路径
    spth = ssub.add_parser(
        "path", help="路径安全校验: 边界/逃逸/敏感目录裁决 (fail-closed)"
    )
    spth.add_argument("path", help="要校验的路径")
    spth.add_argument("--action", default="read",
                      choices=("read", "write", "execute", "list"),
                      help="操作类型 (默认 read)")
    spth.add_argument("--workspace", default=None, help="工作区 (默认当前目录)")
    spth.add_argument("--json", action="store_true", help="输出 JSON (CI/SIEM 消费)")
    spth.set_defaults(safe_cmd="path")
    # 威胁规则透明化: 列出安全引擎 E1-E4 分级规则
    srule = ssub.add_parser("rules", help="威胁规则透明化: 列出 E1-E4 分级规则")
    srule.add_argument("--level", default=None,
                       choices=("all", "e1", "e2", "e3", "e4"),
                       help="只看某级 (默认 all)")
    srule.add_argument("--keyword", default=None, help="按关键词筛选 (描述/正则)")
    srule.add_argument("--for", dest="for_cmd", default=None,
                       help="反查: 这条命令会命中哪些规则 (只读审计)")
    srule.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    srule.set_defaults(safe_cmd="rules")
    # 实时安全事件流 (tail -f 式): 监听 security-audit.jsonl 追加行
    swt = ssub.add_parser("watch", help="实时安全事件流 (tail -f 式, Ctrl-C 退出)")
    swt.add_argument("--tail", type=int, default=10, help="先打印最近 N 条历史 (默认 10)")
    swt.add_argument("--min", default=None,
                     choices=("info", "low", "medium", "high", "critical"),
                     help="只显示 >= 该严重度 (默认 info; 未传则读 config.security.watch_min_severity)")
    swt.add_argument("--json", action="store_true",
                     help="结构化输出 (每行一个 JSON 事件, 供 SIEM)")
    swt.set_defaults(safe_cmd="watch")
    # 密钥拦截守卫: 阻断含明文密钥的提交/写入 (嵌入 pre-commit / CI)
    sgd = ssub.add_parser(
        "guard", help="密钥拦截守卫: 阻断含明文密钥的提交 (pre-commit/CI 接入)"
    )
    gsub = sgd.add_subparsers(dest="guard_cmd", required=False)
    gchk = gsub.add_parser("check", help="检查并阻断含密钥的提交/写入")
    gchk.add_argument("target", nargs="?", default=None, help="文件或目录 (默认 git 暂存区)")
    gchk.add_argument("--stdin", action="store_true", help="从 stdin 读内容 (编辑器钩子)")
    gchk.add_argument("--severity", default=None, help="只拦指定级别及以上 (high/medium/low)")
    gchk.set_defaults(safe_cmd="guard")
    gall = gsub.add_parser("allow", help="添加豁免类型 (如 aws_access_key)")
    gall.add_argument("allow", help="要豁免的密钥类型")
    gall.set_defaults(safe_cmd="guard")
    ginit = gsub.add_parser("init-hook", help="打印 git pre-commit hook 接入片段")
    ginit.set_defaults(safe_cmd="guard")
    gsub.add_parser("status", help="查看守卫状态").set_defaults(safe_cmd="guard")
    sgd.set_defaults(safe_cmd="guard")
    # 密钥暴露与轮换态势: 扫描密钥载体, 判定每个凭据是否暴露/需轮换
    ssec = ssub.add_parser(
        "secrets", help="密钥暴露与轮换态势报告 (差异化: 凭据级暴露裁决)"
    )
    ssec.add_argument("--scope", default="home",
                      choices=("home", "workspace", "all"),
                      help="扫描范围: home=~/.tuan 密钥载体, workspace=当前目录, all=两者")
    ssec.add_argument("--json", action="store_true", help="输出 JSON (CI/SIEM 消费)")
    ssec.set_defaults(safe_cmd="secrets")
    # 安全规则层级透明度: E1-E4 分级规则树 (每个严重度多少条规则, 覆盖面)
    spol = ssub.add_parser(
        "policy", help="安全规则层级透明度 (E1-E4 分级规则树, 差异化)"
    )
    spol.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    # 策略引擎导出/统计/热重载 (第 62 个独特功能)
    spol.add_argument(
        "--export", choices=["yaml", "json"], default=None,
        help="导出全部规则 (yaml=可版本化, json=机器可读)",
    )
    spol.add_argument("--stats", action="store_true",
                      help="策略引擎统计 (按来源/动作)")
    spol.add_argument("--reload", action="store_true",
                      help="热重载用户 YAML (改规则后立即生效)")
    spol.set_defaults(safe_cmd="policy")
    # 安全事件流趋势分析: 跨会话聚合 (严重度/时间/来源/命令模式 + 态势分)
    strd = ssub.add_parser(
        "trends", help="安全事件流趋势分析 (跨会话聚合 + 安全态势分, 差异化)"
    )
    strd.add_argument("--window", type=int, default=24 * 7,
                      help="统计窗口小时数 (默认 168 = 近 7 天)")
    strd.add_argument("--json", action="store_true", help="输出 JSON (CI/SIEM 消费)")
    strd.set_defaults(safe_cmd="trends")
    # 多维风险评估: 六维风险向量 (文件系统/网络/进程/凭据/数据流/混淆)
    srk = ssub.add_parser(
        "risk", help="多维风险评估: 六维风险向量 + 执行域建议 (差异化)"
    )
    srk.add_argument("command", help="待评估的命令 (如 \"rm -rf /\")")
    srk.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    srk.set_defaults(safe_cmd="risk")
    # 策略即代码评估: YAML 规则引擎对命令/路径/内容/工具的结构化裁决
    sev = ssub.add_parser(
        "eval", help="策略即代码评估: 命令/路径/内容/工具的结构化裁决 (差异化)"
    )
    sev.add_argument("--command", default=None, help="要裁决的 shell 命令")
    sev.add_argument("--path", default=None, help="要裁决的文件路径")
    sev.add_argument("--action", default="read", help="路径动作 read/write (默认 read)")
    sev.add_argument("--content", default=None, help="要裁决的写入内容")
    sev.add_argument("--name", default="", help="内容对应的文件名 (可选)")
    sev.add_argument("--tool", default=None, help="要裁决的工具名 (配合 --args)")
    sev.add_argument("--args", default=None, help="工具参数 JSON (配合 --tool)")
    sev.add_argument("--list", action="store_true", help="列出全部已加载规则")
    sev.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    sev.set_defaults(safe_cmd="eval")
    # 命令安全分类: 只读/元数据/风险/阻断 四级语义分类 + 会话统计
    scl = ssub.add_parser(
        "classify", help="命令安全分类: 语义分类 + 置信度 + 会话统计 (差异化)"
    )
    scl.add_argument("--command", default=None, help="要分类的 shell 命令")
    scl.add_argument("--bench", default=None, help="批量分类 (分号分隔)")
    scl.add_argument("--stats", action="store_true", help="会话级分类统计")
    scl.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    scl.set_defaults(safe_cmd="classify")
    # 工具自动批准判定 (第 78 个独特功能: AutoMode 风险预判)
    sauto = ssub.add_parser(
        "auto", help="工具自动批准判定: 预先知道工具调用的裁决"
    )
    sauto.add_argument("--tool", default=None, help="工具名 (如 run_shell / write_file)")
    sauto.add_argument("--arg", default=None, help="工具参数 JSON (如 '{\"command\":\"git status\"}')")
    sauto.add_argument("--rules", action="store_true", help="查看自定义规则")
    sauto.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    sauto.set_defaults(safe_cmd="auto")
    # 安全决策在线学习 (第 125 个独特功能: 可学习拦截器)
    slearn = ssub.add_parser(
        "learn", help="安全决策在线学习: 感知器在线调整权重 (差异化)"
    )
    slearn.add_argument("--command", default=None, help="要反馈的命令")
    slearn.add_argument("--label", default=None,
                        choices=["danger", "safe"],
                        help="实际判定: danger(危险)/safe(安全)")
    slearn.add_argument("--stats", action="store_true", help="查看学习器状态")
    slearn.add_argument("--explain", action="store_true",
                        help="解释命令的多路裁决 (静态基线/学习权重/护栏)")
    slearn.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    slearn.set_defaults(safe_cmd="learn")
    # 安全决策模型权重查看/重置/基准 (第 125 个独特功能)
    smodel = ssub.add_parser(
        "model", help="安全决策模型: 查看/重置/基准评估学习权重 (差异化)"
    )
    smodel.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    smodel.add_argument("model_cmd", nargs="?", default="show",
                        choices=["show", "reset", "bench"],
                        help="子命令: show/reset/bench (默认 show)")
    smodel.set_defaults(safe_cmd="model")
    # 安全围栏性能预算自测 (第 125 个独特功能: 资源占用可观测, N100 达标证明)
    sfence = ssub.add_parser(
        "fence", help="安全围栏性能预算自测: 延迟/内存/缓存收益 + N100 达标判定"
    )
    sfence.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    sfence.set_defaults(safe_cmd="fence")
    # 安全事件摘要: 直接暴露 SecurityBus.summary() (第 55 个独特功能: 安全可观测性)
    ssum = ssub.add_parser(
        "summary", help="安全事件摘要: 类型/严重度分布 + 最近 Critical (差异化)"
    )
    ssum.add_argument("--last", type=int, default=100, help="考虑最近 N 条 (默认 100)")
    ssum.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    ssum.set_defaults(safe_cmd="summary")
    # 安全告警历史/统计/导出: 实时告警通道可观测 (第 58 个独特功能)
    sal = ssub.add_parser(
        "alerts", help="安全告警: 实时告警通道的历史/统计/导出 (差异化)"
    )
    sal.add_argument("--last", type=int, default=50, help="最近 N 条 (默认 50)")
    sal.add_argument(
        "--severity", default=None,
        help="按严重度过滤 (critical/high/medium/low)",
    )
    sal.add_argument(
        "--stats", action="store_true",
        help="只显示统计 (严重度/来源分布)",
    )
    sal.add_argument(
        "--export", choices=["md"], default=None,
        help="导出格式 (md = Markdown 报告)",
    )
    sal.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    sal.set_defaults(safe_cmd="alerts")
    # 审计指纹归一化查询: 同一攻击/注入 → 同一指纹 (第 85 个独特功能)
    sfi = ssub.add_parser(
        "fingerprint", help="审计指纹: 任意审计记录→稳定攻击指纹 (SIEM 归一化)"
    )
    sfi.add_argument("--module", default=None, help="模块名 (如 security)")
    sfi.add_argument("--action", default=None, help="动作名 (如 shell_exec)")
    sfi.add_argument("--reason", default=None, help="归一化原因 (可省略)")
    sfi.add_argument("--input", default=None, help="归一化输入摘要 (可省略)")
    sfi.add_argument("--alert", default=None, help="告警 JSON → 可消费 dict (SIEM)")
    sfi.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    sfi.set_defaults(safe_cmd="fingerprint")
    # 审计关联器配置/状态/重置: 阈值可查 + 手动清空 (第 86 个独特功能)
    sco = ssub.add_parser(
        "correlator", help="审计关联器: 滑动窗口/爆发阈值/跨会话复用配置+重置"
    )
    sco.add_argument("--reset", action="store_true",
                     help="清空关联状态 (窗口/指纹/告警/峰值)")
    sco.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    sco.set_defaults(safe_cmd="correlator")
    p.set_defaults(func="cmd_safe")

    p = sub.add_parser(
        "gh",
        help="GitHub 原生绑定: 调用本机 gh CLI (原生体验), 带不可绕过的安全沙箱",
    )
    p.add_argument(
        "--rest", action="store_true", help="只读命令走内置 REST 回退 (无需本机 gh CLI)"
    )
    p.add_argument(
        "gh_args",
        nargs=argparse.REMAINDER,
        help="随 gh 的命令与参数, 原样透传本机 gh (可含 repo view/rclone/search/api 等)",
    )
    p.set_defaults(func="cmd_gh")

    # ---- tutorial (任务驱动内置教程, onboarding 核心能力) ----
    p = sub.add_parser(
        "tutorial", help="任务驱动内置教程 (安全/撤销/协作/成本 等, 用真实命令引导)"
    )
    tsub = p.add_subparsers(dest="tutorial_cmd", required=False)
    tsub.add_parser("list", help="列出可用教程")
    tr = tsub.add_parser("run", help="逐步运行某个教程 (默认只展示, 不自动执行)")
    tr.add_argument("name", help="教程名称 (如 safety / undo / swarm / cost)")
    tr.add_argument(
        "--exec",
        dest="exec_demo",
        action="store_true",
        help="同时执行标注为安全的演示命令",
    )
    tr.add_argument("--step", type=int, default=1, help="从第 N 步开始 (默认 1)")
    tr.add_argument(
        "--no-pause",
        dest="no_pause",
        action="store_true",
        help="步骤间不暂停, 一口气跑完",
    )
    p.set_defaults(func="cmd_tutorial")

    # ---- sandbox (进程隔离沙箱可观测性: 4 层滤网裁决 / 策略 / 后端 / 拦截史) ----
    p = sub.add_parser(
        "sandbox", help="进程隔离沙箱可观测性: 4 层滤网裁决/策略/后端探测 (差异化)"
    )
    sbsub = p.add_subparsers(dest="sandbox_cmd", required=True)
    sba = sbsub.add_parser(
        "assess", help="对单条命令跑完整 4 层滤网裁决 (L0 意图→L1 信任→L2 资源→L3 强隔离)"
    )
    sba.add_argument("command", help="待裁决的命令 (如 \"rm -rf /\")")
    sba.add_argument("--workspace", default=None, help="工作区 (默认当前目录)")
    sba.add_argument("--yolo", action="store_true", help="yolo 模式 (免确认但 fail-closed 仍拒)")
    sba.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    sbp = sbsub.add_parser("policy", help="当前沙箱策略 + 启用状态 + 资源限制")
    sbp.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    sbb = sbsub.add_parser("backends", help="探测本机可用隔离后端")
    sbb.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    sbt = sbsub.add_parser("trace", help="最近沙箱裁决 (拦截史, 从审计/总线回读)")
    sbt.add_argument("--limit", type=int, default=20, help="返回条数 (默认 20)")
    sbt.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    p.set_defaults(func="cmd_sandbox")

    # ---- harden (安全加固工具集) ----
    p = sub.add_parser(
        "harden", help="安全加固工具: 审计导出/SBOM/加密后端/网络策略/可复现锁"
    )
    hsub = p.add_subparsers(dest="harden_cmd", required=True)
    ae = hsub.add_parser(
        "audit-export", help="把安全事件导出为 CEF/JSONL/Syslog, 可选推送"
    )
    ae.add_argument(
        "--format",
        default="jsonl",
        help="导出格式, 可逗号分隔: cef,jsonl,syslog (默认 jsonl)",
    )
    ae.add_argument(
        "--from",
        dest="from_",
        default=None,
        help="bus JSONL 源 (默认 ~/.tuan/security-audit.jsonl)",
    )
    ae.add_argument("--out", default=None, help="输出目录 (缺省打印到 stdout)")
    ae.add_argument("--push", default=None, help="可选: 把每条事件 POST 到该 URL")
    # --- 第 111 个独特功能: 审计导出归档只读体检 (audit-archive) ---
    aa = hsub.add_parser(
        "audit-archive",
        help="审计导出归档只读体检: 事件数/严重度分布/轮转/时间跨度 (差异化)",
    )
    aa.add_argument("--dir", default=None,
                    help="导出目录 (默认 ~/.tuan/audit-export/, 即 audit-export --out 的目标)")
    aa.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    hsub.add_parser("sbom", help="生成 SPDX 2.3 软件物料清单").add_argument(
        "--out", default=None, help="输出路径 (默认 sbom.spdx.json)"
    )
    hsub.add_parser("crypto-provider", help="列出可用的可插拔密码学后端")
    cs = hsub.add_parser(
        "crypto-selftest", help="密码学后端自检: 信任前验证加解密/篡改检测/HMAC (差异化)"
    )
    cs.add_argument("--provider", default="auto",
                    help="后端名: software|gmssl|hsm|auto (默认 auto)")
    cs.add_argument("--json", action="store_true", help="输出 JSON (CI 消费)")
    nc = hsub.add_parser("network-check", help="评估一条命令的网络出口策略")
    nc.add_argument("--command", required=True, help="待评估的命令")
    nc.add_argument(
        "--egress-cidr",
        action="append",
        dest="egress_cidr",
        default=[],
        help="出口 CIDR 白名单 (可多次, 如 10.0.0.0/8)",
    )
    nc.add_argument(
        "--one-way", action="store_true", help="单向模式 (禁止入站监听类命令)"
    )
    rl = hsub.add_parser("repro-lock", help="生成/校验可复现构建锁")
    rl.add_argument("--out", default=None, help="锁文件路径 (默认 requirements.lock)")
    rl.add_argument(
        "--verify", action="store_true", help="改为校验当前环境是否与锁一致"
    )
    # --- 第 104 个独特功能: 危险命令的安全替代建议 (suggest_safe_alternatives) ---
    sg = hsub.add_parser(
        "suggest",
        help="对危险命令给出安全替代建议: 拦截升级为「给你更安全的做法」 (差异化)",
    )
    sg.add_argument("--command", required=True, help="待评估的命令 (如 'rm -rf /tmp/x')")
    sg.add_argument("--json", action="store_true", help="输出 JSON")
    hsub.add_parser("status", help="展示当前加固态势: 加密后端/审计落盘/SBOM/网络策略")
    p.set_defaults(func="cmd_harden")
