"""其余命令: tui / skills / craft / migrate / network / help / upgrade / permissions / review / security-review / simplify / debug / auto-mode / batch。

从 `parser_commands.py` 拆出的 `register_subcommands` 分片, 行为不变。
"""

from __future__ import annotations

from typing import Any

from ._common import _add_network_parser
def register_misc_compat(sub: Any) -> None:
    """注册 misc_compat 域子命令。"""

    # ---- tui (TUI 对齐态势) ----
    p = sub.add_parser("tui", help="TUI 与上游的对齐态势")
    tsub = p.add_subparsers(dest="tui_cmd", required=True)
    tp = tsub.add_parser("parity", help="展示与 OpenAI Codex TUI 的对齐矩阵")
    tp.add_argument("--report-json", dest="report_json", action="store_true",
                    help="输出结构化 JSON 报告 (规避 --json-schema 前缀歧义)")
    tp.add_argument("--gaps", action="store_true", help="列出待对齐模块队列")
    p.set_defaults(func="cmd_tui_parity")

    # ---- skills / craft (registry 远程技能与组件) ----
    sk = sub.add_parser(
        "skills",
        help="从 Tuan-Skills / Tuan-Craft 远程 registry 管理技能与组件",
    )
    sksub = sk.add_subparsers(dest="skills_action")
    sksub.add_parser("list", help="列出远程 registry 可用的 skill")
    sksub.add_parser("installed", help="列出本地已安装的 skill (builtin/用户级/项目级)")
    sin = sksub.add_parser("install", help="安装一个 skill 到 ~/.tuan/skills/<name>/")
    sin.add_argument("name", help="skill 名称 (Tuan-Skills registry 里的 name)")
    sup = sksub.add_parser("update", help="更新已安装 skill (重新拉远程)")
    sup.add_argument("name", help="skill 名称")
    srm = sksub.add_parser("remove", help="删除已安装 skill (只删用户级副本)")
    srm.add_argument("name", help="skill 名称")
    spull = sksub.add_parser("pull", help="一次性 pull registry 全部 skill 到本地")
    spull.add_argument("--force", "-f", action="store_true", help="覆盖已存在的 skill")
    sksub.add_parser("cache", help="清除 registry 本地缓存 (1h TTL)")
    sksub.add_parser("seed", help="把 builtin/ 内置 skill 播种到 ~/.tuan/skills/ (去预制化第一步)")
    # Tuan-Craft 组件工坊 (挂在 skills 下方便发现, 也提供独立 craft 子命令)
    sksub.add_parser("craft-list", help="列出 Tuan-Craft 组件工坊")
    sci = sksub.add_parser("craft-install", help="安装 craft 组件到 ~/.tuan/craft/<name>/")
    sci.add_argument("name", help="组件名")
    sk.set_defaults(func="cmd_skills")

    # 同时注册独立 craft 命令 (两种入口等价)
    cr = sub.add_parser("craft", help="Tuan-Craft 组件工坊 (感通模式组件)")
    crsub = cr.add_subparsers(dest="skills_action")  # 复用 skills_action 分流
    crsub.add_parser("list", help="列出远程可用的 craft 组件")
    crsub.add_parser("installed", help="列出本地已安装的 craft 组件")
    ci = crsub.add_parser("install", help="安装 craft 组件到 ~/.tuan/craft/<name>/")
    ci.add_argument("name", help="组件名")
    cr.set_defaults(func="cmd_skills", craft_mode=True)


    # ---- migrate (旧版 ~/.kimi 配置/会话 → 新版 ~/.tuan 迁移) ----
    p = sub.add_parser(
        "migrate", help="旧版 ~/.kimi 配置/会话 → 新版 一键迁移 (检测/执行/状态)"
    )
    mgsub = p.add_subparsers(dest="migrate_cmd", required=True)
    st = mgsub.add_parser("status", help="查看是否已迁移 (只读)")
    st.add_argument("--source", default=None, help="旧版源目录 (默认 ~/.kimi)")
    de = mgsub.add_parser("detect", help="只读扫描旧版状态并汇报 (不写任何东西)")
    de.add_argument("--source", default=None, help="旧版源目录 (默认 ~/.kimi)")
    de.add_argument(
        "--target",
        dest="target",
        default=None,
        help="目标主目录 (仅状态展示, 默认 ~/.tuan)",
    )
    ru = mgsub.add_parser("run", help="执行迁移 (幂等/可逆/绝不覆盖用户改过的目标文件)")
    ru.add_argument("--source", default=None, help="旧版源目录 (默认 ~/.kimi)")
    ru.add_argument("--target", default=None, help="目标主目录 (默认 ~/.tuan)")
    p.set_defaults(func="cmd_migrate")

    # ---- network (联网/搜索配置基础设施, tuan net con = tuan network configuration) ----
    _add_network_parser(
        sub,
        "network",
        "联网/搜索配置管理 (查看/设定搜索上限、默认条数、截断、top_k、超时)",
        aliases=("net",),
    )

    # ---- help (只读打印帮助, 不进交互/不写配置) ----
    # 与 `tuan --help` 等效, 但符合 tuan help / tuan help <子命令> 的肌肉记忆。
    p = sub.add_parser("help", help="显示帮助 (tuan help [子命令])")
    p.add_argument("topic", nargs="?", help="子命令名 (省略则显示总览)")
    p.set_defaults(func="cmd_help")

    # ---- upgrade (自动更新 tuan 自身) ----
    p = sub.add_parser("upgrade", help="检查并升级 tuan 到最新版 (pip)")
    p.add_argument("--check", action="store_true", help="仅检查是否有新版本, 不安装")
    p.add_argument("--yes", "-y", action="store_true", help="跳过确认直接更新")
    p.add_argument("--version", help="安装指定版本 (如 0.3.1)")
    p.set_defaults(func="cmd_upgrade")

    # ---- permissions (权限规则查看 / 命中测试) ----
    p = sub.add_parser(
        "permissions", help="权限规则查看与命中测试"
    )
    psub = p.add_subparsers(dest="permissions_cmd")
    psub.add_parser("list", help="列出 permissions.rules 全部规则")
    cov = psub.add_parser("coverage", help="危险工具规则覆盖报告 (策略透明度, 差异化)")
    cov.add_argument("--json", action="store_true", help="结构化输出 (CI 消费)")
    t = psub.add_parser("test", help="测试某次工具调用会命中哪条规则 (只读, 不执行)")
    t.add_argument("tool", help="工具名, 如 run_shell")
    t.add_argument(
        "args_json",
        nargs="?",
        default="{}",
        help='工具参数 JSON, 如 \'{"command":"rm -rf /"}\'',
    )
    p.set_defaults(func="cmd_permissions")

    # ---- Claude Code 对齐 CLI 命令面 (docs/GAP-ANALYSIS-vs-ClaudeCode.md A2) ----
    p = sub.add_parser(
        "review",
        help="自动代码评审 (静态分析 + 逻辑审查 + 安全扫描, 输出评分报告)",
    )
    p.add_argument("path", nargs="?", default="", help="评审路径 (目录或文件, 默认工作区)")
    p.add_argument("--files", default="", help="逗号分隔的文件列表")
    p.add_argument(
        "--categories",
        default=None,
        help="评审类别 (security/logic/style/complexity, 逗号分隔; 默认全部)",
    )
    p.add_argument("--json", action="store_true", help="以 JSON 输出结构化结果")
    p.add_argument("--workspace", default=None, help="工作区目录 (默认当前目录)")
    p.set_defaults(func="cmd_review")

    p = sub.add_parser(
        "security-review",
        help="安全扫描评审 (仅 security 类别: 密钥/注入/XSS/pickle 等)",
    )
    p.add_argument("path", nargs="?", default="", help="扫描路径 (默认工作区)")
    p.add_argument("--files", default="", help="逗号分隔的文件列表")
    p.add_argument("--json", action="store_true", help="以 JSON 输出结构化结果")
    p.add_argument("--workspace", default=None, help="工作区目录 (默认当前目录)")
    p.set_defaults(func="cmd_security_review", security=True)

    p = sub.add_parser(
        "simplify",
        help="简化冗余技能 (检测相似技能对, 提议合并; --apply 实际执行)",
    )
    p.add_argument("--dry-run", action="store_true", help="只报告不合并 (默认)")
    p.add_argument("--apply", action="store_true", help="实际执行合并")
    p.add_argument("--threshold", type=float, default=0.7, help="相似度阈值 (默认 0.7)")
    p.add_argument("--workspace", default=None, help="工作区目录 (默认当前目录)")
    p.set_defaults(func="cmd_simplify")

    p = sub.add_parser(
        "debug",
        help="环境/配置/运行时诊断摘要 (python/cwd/home/config/环境变量)",
    )
    p.set_defaults(func="cmd_debug")

    # ---- auto-mode: Auto 模式分类器展示与测试 (对标 Claude Code auto-mode) ----
    p = sub.add_parser(
        "auto-mode",
        help="Auto 模式分类器: 展示工具风险基线; test 评估单次调用的自动批准决策",
    )
    p.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["list", "test", "current"],
        help="list=展示风险基线 (默认); test=评估单次调用; current=查询当前运行模式",
    )
    p.add_argument(
        "tool",
        nargs="?",
        default="",
        help="test 时: 要评估的工具名 (如 Bash / Edit)",
    )
    p.add_argument(
        "args",
        nargs="?",
        default="{}",
        help="test 时: 调用参数 JSON 对象 (如 '{\"command\":\"git status\"}')",
    )
    p.set_defaults(func="cmd_auto_mode")

    p = sub.add_parser(
        "batch",
        help="批量执行一组只读 slash 命令 (--file <命令文件> 或直接给命令)",
    )
    p.add_argument("commands", nargs="*", help="要批量执行的 slash 命令")
    p.add_argument("--file", dest="file", default=None, help="命令文件 (每行一条)")
    p.add_argument("--workspace", default=None, help="工作区目录 (默认当前目录)")
    p.set_defaults(func="cmd_batch")
