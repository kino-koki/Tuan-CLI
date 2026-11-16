"""内核与模型命令: kernel / prompt / 模型目录 / 配置 / 韧性 / 插件 / 技能 / 记忆 / 定时 / MCP / 生态互通 / hooks。

从 `parser_commands.py` 拆出的 `register_subcommands` 分片, 行为不变。
"""

from __future__ import annotations

from typing import Any
def register_kernel_models(sub: Any) -> None:
    """注册 kernel_models 域子命令。"""

    # ---- kernel (内核可观测性, 第 82 个独特功能: 事件总线/服务归属/中间件) ----
    pk = sub.add_parser(
        "kernel",
        help="内核可观测性: 事件总线历史/服务归属/中间件管线 (Claude Code 无)",
    )
    pk.set_defaults(func="cmd_kernel", kernel_cmd="events")
    ksub = pk.add_subparsers(dest="kernel_cmd", required=False)
    ke = ksub.add_parser("events", help="列出内核事件总线历史 (默认)")
    ke.add_argument("--limit", type=int, default=20, help="显示条数 (0=全部)")
    ke.add_argument("--json", action="store_true", help="输出 JSON")
    ke.set_defaults(kernel_cmd="events")
    ks = ksub.add_parser("services", help="列出服务容器与归属 (owner/贡献者)")
    ks.add_argument("service", nargs="?", default="", help="只看指定服务")
    ks.add_argument("--json", action="store_true", help="输出 JSON")
    ks.set_defaults(kernel_cmd="services")
    km = ksub.add_parser("middleware", help="列出事件总线中间件管线")
    km.add_argument("--json", action="store_true", help="输出 JSON")
    km.set_defaults(kernel_cmd="middleware")
    pk.add_argument("--json", action="store_true", help="输出 JSON")

    # ---- prompt (提示词分层诊断, 第 40 个独特功能: 预算可观测性) ----
    p = sub.add_parser(
        "prompt",
        help="提示词分层诊断: 按模型上下文窗口的注入预算/SOUL档位 (差异化)",
    )
    p.set_defaults(func="cmd_prompt", prompt_cmd="tier")
    psub = p.add_subparsers(dest="prompt_cmd", required=False)
    ptier = psub.add_parser(
        "tier", help="诊断当前/指定模型的分档 + 预算上限 + SOUL档位"
    )
    ptier.add_argument("--model", default=None, help="模型名 (自动推断窗口)")
    ptier.add_argument("--provider", default=None, help="供应商 (默认窗口查表)")
    ptier.add_argument("--window", type=int, default=None, help="显式上下文窗口 token")
    ptier.add_argument("--tier", default=None,
                       help="强制档位 compact/full (默认 auto 按窗口)")
    ptier.add_argument("--json", action="store_true", help="输出 JSON")
    ptier.set_defaults(prompt_cmd="tier")

    p = sub.add_parser(
        "models", help="配置/热切换模型供应商 (开箱支持57家, 含 Ollama/llama.cpp 本地)"
    )
    p.set_defaults(func="cmd_model")
    msub = p.add_subparsers(dest="model_cmd", required=False)
    msub.add_parser("current", help="显示当前生效的模型配置").set_defaults(
        model_cmd="current"
    )
    info = msub.add_parser("info", help="查看某供应商详细信息 (文档/模型/定价)")
    info.add_argument("provider_name", help="供应商名称 (如 deepseek / ollama)")
    info.set_defaults(model_cmd="info")
    ml = msub.add_parser("list", help="列出某供应商当前可选模型清单")
    ml.add_argument("provider_name", help="供应商名称 (如 openrouter / deepseek)")
    ml.set_defaults(model_cmd="list")
    mlocal = msub.add_parser(
        "local", help="列出本机已安装的本地模型 (Ollama + llama.cpp)"
    )
    mlocal.set_defaults(model_cmd="local")
    mt = msub.add_parser(
        "test", help="连通性测试: 向当前端点发一条最小请求验证 base_url/Key/模型名"
    )
    mt.add_argument("--provider", help="临时覆盖供应商 (不写盘)")
    mt.add_argument("--model", help="临时覆盖模型名 (不写盘)")
    mt.add_argument("--base-url", dest="base_url", help="临时覆盖 base_url (不写盘)")
    mt.add_argument(
        "--api-key-env", dest="api_key_env", help="临时覆盖密钥环境变量名 (不写盘)"
    )
    mt.set_defaults(model_cmd="test")
    ms = msub.add_parser("set", help="切换模型供应商并写入用户配置 (下次启动生效)")
    ms.add_argument(
        "provider",
        help="供应商名: deepseek / openai / openai-compatible / 自定义网关名",
    )
    ms.add_argument("model", help="模型名, 如 deepseek-chat / claude-3-5-sonnet")
    ms.add_argument(
        "base_url",
        nargs="?",
        default=None,
        help="可选: 网关 base_url (自定义/兼容网关必填)",
    )
    ms.add_argument(
        "api_key_env",
        nargs="?",
        default=None,
        help="可选: 密钥环境变量名 (默认沿用当前)",
    )
    ms.set_defaults(model_cmd="set")
    msub.add_parser(
        "list-providers", help="列出内置已知供应商与自定义网关提示"
    ).set_defaults(model_cmd="list-providers")
    mprov = msub.add_parser("providers",
                            help="供应商健康/成本矩阵 (可用性+分层, 差异化)")
    mprov.add_argument("--json", action="store_true", help="结构化输出 (CI 消费)")
    mprov.set_defaults(model_cmd="providers")
    mcap = msub.add_parser("capabilities",
                           help="能力覆盖矩阵: 哪些供应商覆盖哪些能力 (差异化)")
    mcap.add_argument("--json", action="store_true", help="结构化输出 (CI 消费)")
    mcap.set_defaults(model_cmd="capabilities")
    up = msub.add_parser("update", help="更新模型/供应商目录 (内置清单合并 + 可选联网拉官方最新)")
    up.add_argument("--check", action="store_true", help="只报告内置与本地差异, 不写盘")
    up.add_argument("--background", "--bg", dest="background", action="store_true",
                    help="后台线程执行, 立即返回")
    up.add_argument("--online", action="store_true",
                    help="联网拉各供应商官方模型清单 (每周 1 次, 仅官方渠道)")
    up.add_argument("--force", action="store_true",
                    help="配合 --online: 忽略 7 天到期检测, 强制重新拉取")
    up.set_defaults(model_cmd="update")
    sw = msub.add_parser("switch", help="运行时热切换 (当前会话立即换脑子, 不写盘)")
    sw.add_argument(
        "provider",
        help="供应商名: deepseek / openai / openai-compatible / 自定义网关名",
    )
    sw.add_argument("model", help="模型名, 如 deepseek-chat / claude-3-5-sonnet")
    sw.add_argument(
        "base_url",
        nargs="?",
        default=None,
        help="可选: 网关 base_url (自定义/兼容网关必填)",
    )
    sw.add_argument(
        "api_key_env",
        nargs="?",
        default=None,
        help="可选: 密钥环境变量名 (默认沿用当前)",
    )
    sw.set_defaults(model_cmd="switch")
    # 路由决策 dry-run (独特能力: 多模型 + 本地优先 + 成本追踪, 不发送请求)
    mr = msub.add_parser(
        "route",
        help="路由决策 dry-run: 难度/选型/成本/断网降级 (不发送请求)",
    )
    mr.add_argument(
        "task", nargs="?", default="常规编码任务",
        help="任务描述 (用于难度估算), 默认 '常规编码任务'",
    )
    mr.add_argument("--plan", action="store_true",
                    help="渲染 What-If 路由规划矩阵 (全候选 × 全难度, 差异化)")
    mr.add_argument("--strategy", action="store_true",
                    help="自动路由动态策略诊断: 强规划/便宜执行/卡住升级轨迹 (差异化)")
    mr.add_argument("--preview", action="store_true",
                    help="能力感知路由预览: 单任务难度评估+是否切换决策 (差异化, 无副作用)")
    mr.add_argument("--last", action="store_true",
                    help="执行期实际路由决策: AgentModelRouter.last_route (第 83 个独特功能)")
    mr.add_argument("--difficulty", type=int, default=0,
                    help="覆盖难度档 (preview 用, 默认自动评估)")
    mr.add_argument("--images", action="store_true",
                    help="模拟挂图视觉需求 (preview 用, 强制视觉能力检查)")
    mr.add_argument("--stuck", type=int, default=None,
                    help="卡住升级阈值 (strategy 用, 默认读配置)")
    mr.add_argument("--turns", type=int, default=None,
                    help="模拟轮数 (strategy 用, 默认 10)")
    mr.add_argument("--fail", default=None,
                    help="模拟失败轮次 (strategy 用, 如 '3,4,5,6')")
    mr.add_argument("--enable", action="store_true",
                    help="强制开启规划/执行 (strategy 用)")
    mr.add_argument("--disable", action="store_true",
                    help="强制关闭规划/执行 (strategy 用)")
    # 自动路由总开关可观测 (第 68 个独特功能)
    mr.add_argument("--enable-route", action="store_true",
                    help="强制开启路由总开关 router.enabled (strategy 用)")
    mr.add_argument("--json", action="store_true",
                    help="结构化输出 (规划矩阵, CI 消费)")
    mr.set_defaults(model_cmd="route")
    # --- 第 105 个独特功能: 模型响应缓存只读诊断 (ResponseCache 落盘面) ---
    mc = msub.add_parser("cache", help="模型响应缓存只读诊断 (差异化)")
    mc.add_argument("--top", type=int, default=0, help="按值长度取 Top-N 大条目")
    mc.add_argument("--json", action="store_true", help="输出 JSON")
    mc.set_defaults(model_cmd="cache")

    p = sub.add_parser("config", help="配置管理")
    csub = p.add_subparsers(dest="config_cmd", required=True)
    csub.add_parser("dump", help="打印叠加后的最终配置")
    csub.add_parser("dump-default", help="打印内置默认配置")
    csub.add_parser("drift", help="用户覆盖 vs 默认差异报告 (配置透明度, 差异化)")
    csub.add_parser("profiles", help="列出可用预设 profile")
    csub.add_parser("validate", help="校验当前配置 (类型/范围/枚举/密钥)")
    # 配置 schema 发现: 可配置键树 + 类型 + 默认值 + 层级混淆检测 (第 69 个独特功能)
    cschema = csub.add_parser(
        "schema",
        help="配置 schema 发现: 全部可配置键/类型/默认值 + 层级混淆检测 (差异化)",
    )
    cschema.add_argument("--section", default=None,
                         help="只看指定顶层段 (如 router/loop/agent/model)")
    cschema.add_argument("--flat", action="store_true",
                         help="扁平点路径列出 (CI 消费友好)")
    cschema.add_argument("--json", action="store_true",
                         help="输出 JSON (机器可读)")
    cschema.set_defaults(config_cmd="schema")
    # 受管配置分层只读体检 (第 122 个独特功能)
    cman = csub.add_parser(
        "managed",
        help="受管配置分层审计: 层级存在性/赢得者/锁定字段 (差异化)",
    )
    cman.add_argument("--workspace", default=None,
                      help="项目目录 (用于解析项目级 .tuan/settings.json)")
    cman.add_argument("--json", action="store_true",
                      help="输出 JSON (机器可读)")
    cman.set_defaults(config_cmd="managed")
    g = csub.add_parser("get", help="读取配置项")
    g.add_argument("key")
    s = csub.add_parser("set", help="写入用户层配置")
    s.add_argument("key")
    s.add_argument("value")
    p.set_defaults(func="cmd_config")

    p = sub.add_parser(
        "resilience",
        help="韧性可观测性: 熔断/限流/重试/故障转移四层防线 (差异化, Claude Code 无)",
    )
    resub = p.add_subparsers(dest="resilience_cmd", required=True)
    _rs = resub.add_parser("status", help="四层防线实时状态")
    _rs.add_argument("--json", action="store_true",
                     help="结构化输出 (CI / 审计消费)")
    _rs.set_defaults(resilience_cmd="status")
    rh = resub.add_parser("history", help="跨会话故障转移历史 (最近 N 次)")
    rh.add_argument("--limit", type=int, default=20, help="返回条数 (默认 20)")
    rh.add_argument("--json", action="store_true",
                    help="结构化输出 (CI / 审计消费)")
    rh.set_defaults(resilience_cmd="history")
    _rc = resub.add_parser("config", help="韧性相关配置 (只读)")
    _rc.add_argument("--json", action="store_true",
                     help="结构化输出 (CI / 审计消费)")
    _rc.set_defaults(resilience_cmd="config")
    # 熔断器状态/统计/复位: 熔断器可观测与手动恢复 (第 60 个独特功能)
    _rb = resub.add_parser(
        "breaker", help="熔断器状态/统计/手动复位 (差异化)"
    )
    _rb.add_argument("--reset", action="store_true",
                     help="手动复位熔断器到 CLOSED (运维恢复)")
    _rb.add_argument("--json", action="store_true",
                     help="结构化输出 (CI / 审计消费)")
    _rb.set_defaults(resilience_cmd="breaker")
    # 限流器运行态快照: 令牌桶节流可观测 (第 71 个独特功能)
    _rl = resub.add_parser(
        "limiter", help="限流器运行态快照: 令牌桶节流可观测 (差异化)"
    )
    _rl.add_argument("--json", action="store_true",
                     help="结构化输出 (CI / 审计消费)")
    _rl.set_defaults(resilience_cmd="limiter")
    # 错误分类裁决 (第 79 个独特功能: 重试行为预判)
    _rcl = resub.add_parser(
        "classify", help="错误分类裁决: 预判某错误会否被重试/多久重试"
    )
    _rcl.add_argument("--error", default="", help="错误文案 (如 '未配置 api key')")
    _rcl.add_argument("--type", default="runtime",
                      help="异常类型 (runtime/value/timeout/connection/keyerror/config)")
    _rcl.add_argument("--json", action="store_true", help="结构化输出 (CI / 审计)")
    _rcl.set_defaults(resilience_cmd="classify")
    p.set_defaults(func="cmd_resilience")

    p = sub.add_parser("plugin", help="插件管理 (兼容 DSH 0.2+)")
    psub = p.add_subparsers(dest="plugin_cmd", required=True)
    psub.add_parser(
        "list", help="列出已安装插件 (含版本/状态/兼容性, 含 DSH 0.2 格式)"
    ).set_defaults(plugin_cmd="list")
    pinst = psub.add_parser("install", help="从本地目录安装插件")
    pinst.add_argument("path", help="插件源目录路径 (含 plugin.json 或 plugin.toml)")
    pinst.add_argument(
        "--name", default=None, help="可选: 覆盖插件名 (默认取 manifest.name)"
    )
    pun = psub.add_parser("uninstall", help="卸载插件")
    pun.add_argument("name", help="插件名 (manifest.name)")
    pen = psub.add_parser("enable", help="启用插件")
    pen.add_argument("name", help="插件名")
    pdis = psub.add_parser("disable", help="禁用插件")
    pdis.add_argument("name", help="插件名")
    pinf = psub.add_parser("info", help="查看插件详情 (manifest/skills/hooks/依赖/兼容性)")
    pinf.add_argument("name", help="插件名")
    p.set_defaults(func="cmd_plugin")

    p = sub.add_parser("skill", help="技能管理")
    ssub = p.add_subparsers(dest="skill_cmd", required=True)
    ssub.add_parser("list", help="列出全部技能 (标注来源 project/user/builtin)")
    sh = ssub.add_parser("show", help="查看技能详情")
    sh.add_argument("name")
    imp = ssub.add_parser(
        "import", help="从 Claude Code/Codex 技能目录导入到用户级 skills/"
    )
    imp.add_argument("path", help="SKILL.md 文件或技能包目录路径")
    ssub.add_parser("audit", help="审计全部技能: 僵尸/元数据不全/frontmatter 合法性")
    con = ssub.add_parser("consolidate", help="检测相似技能并提议合并 (默认 dry-run)")
    con.add_argument("--apply", action="store_true", help="实际执行合并 (默认只演练)")
    con.add_argument(
        "--threshold", type=float, default=0.7, help="相似度阈值 (默认 0.7)"
    )
    lnt = ssub.add_parser("lint", help="检查单个技能的 frontmatter 与正文结构")
    lnt.add_argument("name")
    p.set_defaults(func="cmd_skill")

    p = sub.add_parser("memory", help="记忆管理")
    msub = p.add_subparsers(dest="memory_cmd", required=True)
    msub.add_parser("list", help="查看长期记忆")
    se = msub.add_parser("search", help="全文检索记忆")
    se.add_argument("query")
    p.set_defaults(func="cmd_memory")

    p = sub.add_parser("cron", help="定时任务")
    crsub = p.add_subparsers(dest="cron_cmd", required=True)
    a = crsub.add_parser("add", help="添加定时任务")
    a.add_argument("name")
    a.add_argument("prompt")
    a.add_argument("--interval", type=int, default=60, help="间隔分钟数")
    a.add_argument("--cron", help="标准 5 字段 cron 表达式 (如 '0 9 * * 1-5'); 传入后按 cron 排期, 忽略 --interval")
    a.add_argument("--output", help="每次执行把结果写入该文件 (供监控/CI 消费)")
    crsub.add_parser("list", help="列出任务")
    r = crsub.add_parser("remove", help="删除任务")
    r.add_argument("id")
    en = crsub.add_parser("enable", help="启用任务")
    en.add_argument("id")
    dis = crsub.add_parser("disable", help="暂停任务")
    dis.add_argument("id")
    ed = crsub.add_parser("edit", help="修改任务 (间隔/提示词/名称/输出文件)")
    ed.add_argument("id")
    ed.add_argument("--interval", type=int, help="新的间隔分钟数")
    ed.add_argument("--cron", help="新的 cron 表达式 (传入后从间隔模式切换为 cron 排期)")
    ed.add_argument("--prompt", help="新的任务提示词")
    ed.add_argument("--name", help="新的任务名称")
    ed.add_argument("--output", help="新的结果输出文件路径 (留空字符串则清除)")
    run = crsub.add_parser("run", help="立即执行指定任务 (一次)")
    run.add_argument("id")
    logs = crsub.add_parser("logs", help="查看任务执行历史")
    logs.add_argument("id")
    crsub.add_parser("tick", help="执行所有到期任务 (一次) — 也供系统计划任务/守护调用")
    st = crsub.add_parser(
        "start", help="启动常驻调度守护 (自动执行到期任务, 无需系统计划任务)"
    )
    st.add_argument(
        "--detach", action="store_true", help="后台分离运行 (写 PID 文件, 返回终端)"
    )
    st.add_argument("--check", type=int, default=60, help="守护检查间隔秒数 (默认 60)")
    crsub.add_parser("stop", help="停止常驻调度守护")
    crsub.add_parser("status", help="查看守护与任务状态")
    p.set_defaults(func="cmd_cron")

    p = sub.add_parser("mcp", help="MCP 协议: 接入外部 MCP Server 工具")
    psub = p.add_subparsers(dest="mcp_cmd", required=True)
    psub.add_parser("list", help="列出已配置的 MCP server 与桥接工具")

    pmt = psub.add_parser("tools", help="列出 MCP 工具 (可指定 server)")
    pmt.add_argument("server", nargs="?", default=None, help="只显示该 server 的工具")

    pmc = psub.add_parser("call", help="调用一个 MCP 工具")
    pmc.add_argument("server", help="MCP server 名")
    pmc.add_argument("tool", help="工具名")
    pmc.add_argument(
        "--json",
        dest="json",
        default=None,
        help='工具参数 (JSON 字符串, 如 \'{"text":"hi"}\')',
    )

    pma = psub.add_parser("add", help="添加一个 MCP server 到用户配置")
    pma.add_argument("name", help="server 名 (本地引用)")
    pma.add_argument("command", help="启动命令 (如 npx / python)")
    pma.add_argument("--args", nargs="*", default=[], help="命令参数")
    pma.add_argument("--env", nargs="*", default=[], help="环境变量 KEY=VALUE")
    pma.add_argument("--timeout", type=float, default=None, help="单次调用超时(秒)")

    pmrm = psub.add_parser("remove", help="从用户配置删除一个 MCP server")
    pmrm.add_argument("name", help="要删除的 server 名")

    pmst = psub.add_parser("test", help="连通性测试: 启动 server 并列举工具")
    pmst.add_argument("name", help="已配置的 MCP server 名")

    pmaud = psub.add_parser(
        "audit", help="查看 MCP 调用审计日志 (持久化到 ~/.tuan/mcp-audit.jsonl)"
    )
    pmaud.add_argument(
        "limit", nargs="?", type=int, default=20, help="显示条数 (默认 20)"
    )
    pmaud.add_argument("--clear", action="store_true", help="清空审计日志")

    pms = psub.add_parser(
        "security", help="显示各 MCP server 的安全策略 (权限/频率/审计/沙箱)"
    )
    pms.add_argument("server", nargs="?", default=None, help="只显示该 server 的策略")
    pgd = psub.add_parser(
        "guard", help="MCP 注入检测防线: 工具描述扫描摘要 + 审计日志 (TrustFall 类)"
    )
    pgd.add_argument("--limit", type=int, default=20, help="日志条数 (默认 20)")
    pgd.add_argument("--json", action="store_true", help="输出 JSON (CI/SIEM 消费)")
    # mcp policy: MCP server 信任分级策略只读面 (第 108 个独特功能)
    ppol = psub.add_parser(
        "policy", help="MCP server 信任分级策略只读面: tier/权限域/是否锁定 (fail-closed)"
    )
    ppol.add_argument("server", nargs="?", default=None, help="只显示指定 server")
    ppol.add_argument("--json", action="store_true", help="输出 JSON (CI / 审计)")
    p.set_defaults(func="cmd_mcp")

    # ---- tuan ecosystem: 生态互操作 (Claude Code / Hermes Agent) ----
    p = sub.add_parser(
        "ecosystem",
        help="生态互操作: Claude Code / Hermes Agent 资产双向搬运 + MCP 暴露",
    )
    esub = p.add_subparsers(dest="ecosystem_cmd", required=True)
    esub.add_parser("scan", help="探测本机 Claude Code / Hermes 及其资产").set_defaults(
        ecosystem_cmd="scan"
    )
    esub.add_parser("status", help="连接状态 + 资产计数 + 开关").set_defaults(
        ecosystem_cmd="status"
    )
    ei = esub.add_parser("import", help="导入对方生态资产到青小团")
    ei.add_argument(
        "kind", choices=["skills", "memory", "agents", "context", "mcp", "all"],
        help="skills|memory|agents|context|mcp|all",
    )
    ei.add_argument(
        "--from", dest="ecosystem_from", choices=["claude", "hermes", "all"],
        default="all", help="来源生态 (默认 all)",
    )
    ei.add_argument("--force", action="store_true", help="覆盖同名资产 (默认跳过)")
    ee = esub.add_parser("export", help="导出青小团资产到对方生态")
    ee.add_argument("kind", choices=["skills", "agents", "memory"],
                    help="skills|agents|memory")
    ee.add_argument(
        "--to", dest="ecosystem_to", choices=["claude", "hermes", "all"],
        default="all", help="目标生态 (默认 all)",
    )
    el = esub.add_parser("link", help="把 tuan 注册为外部 Agent 的 MCP server")
    el.add_argument(
        "--apply", action="store_true",
        help="同时写入 Hermes config.yaml (默认只打印接入命令)",
    )
    esub.add_parser(
        "serve", help="以 MCP stdio server 运行, 供 Claude Code / Hermes 挂载"
    ).set_defaults(ecosystem_cmd="serve")
    p.set_defaults(func="cmd_ecosystem")

    p = sub.add_parser("hooks", help="用户级 Hooks: 在工具执行前/后挂载自己的脚本")
    hsub = p.add_subparsers(dest="hook_cmd", required=True)
    hsub.add_parser("list", help="列出已配置的 Hooks")
    hst = hsub.add_parser("test", help="触发一次 Hook 事件 (连通性测试)")
    hst.add_argument(
        "event", help="事件名: PreToolUse / PostToolUse / SessionStart / SessionEnd"
    )
    hst.add_argument(
        "--tool", default="echo_text", help="工具名 (PreToolUse / PostToolUse 使用)"
    )
    hst.add_argument(
        "--json",
        dest="tool_input",
        default="{}",
        help='工具参数 (JSON 字符串, 如 \'{"text":"hi"}\')',
    )
    hsub.add_parser("enable", help="全局启用 Hooks (写入 hooks.enabled=true)")
    hsub.add_parser("disable", help="全局禁用 Hooks (写入 hooks.enabled=false)")
    p.set_defaults(func="cmd_hooks")
