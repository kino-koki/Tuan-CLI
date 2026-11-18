"""单一版本号源 (Single Source of Truth for tuan version).

所有子模块 (tuan_cli / tuan_cli.ecosystem / 各 CLI 命令) 都
应当从本文件导入 `__version__`, 不再各自硬编码。

历史上出现过:
- 主包 tuan_cli.__version__ = "0.3.1"
- tuan_cli.ecosystem.__version__ = "0.1.0"
两者语义混淆: 一个是"CLI 主程序版本", 另一个被误读为"生态互操作子模块
独立版本", 但实际上 ecosystem 只是 CLI 的一个功能域, 不应有自己的版本号。

规范:
    1. 主包 `tuan_cli/__init__.py` 通过 `from .version import __version__`
       获取版本, 对外暴露 `tuan_cli.__version__`。
    2. ecosystem 子模块不再定义自己的 `__version__`, 仅 re-export 主包版本。
    3. CLI 各命令 (cmd_upgrade / cmd_doctor / cmd_web / ui/repl / tui 等)
       统一 `from .. import __version__` (从主包读), 不再各自维护。

升级主包版本时只需修改本文件。
"""

# 单一版本号源: 升级时只改这里 (v0.3.2 起发布名 = tuan-cli)
# 版本策略: 一月一大更新 (+0.1), 每周一小更新 (+0.0.1)
# v0.3.4: 安全引擎攻击面修复 (ReDoS 护栏 + rsync --delete 目标端 + 信号类毁灭 +
#         反引号命令替换 mask 回归); API 冻结 (见 docs/API_FREEZE.md);
#         1.0 目标升级为「Linux 6.5+ / Windows 10+ / macOS 17+ 全平台最安全」。
# v0.4.0: 安全防线多路完善 (神经网络学习器等多路防御 + 全新安全模块);
#         新增 Qwen 办公 2.0 团队协作模式; CLI 命令简化 (合并/精简入口数量);
#         API 冻结点确立, 1.0 目标重定为由 GitHub STAR 数门控 (见 VERSION_POLICY.md)。
# v0.4.1: web 团队协作页 (GitHub 设备流登录 + 协作黑板) + MotionHarness
#         代码动画节点工作台 (/web ComfyUI 风格)。
# v0.4.2: 团组 (TeamGroup) —— Tuan 的团队核心: 最多 100 人纯本地团队,
#         供应商/模型授权互通 (key 所有者签名 + 时限≤90天 + 无云端传 key);
#         AgentCapability 统一能力门面 (融合 Kiro/Codebuff/Cursor/herdr/
#         kimicode/doubao-cli 等 17 项各家 Agent 核心理念为可插拔能力矩阵);
#         tuan team CLI 子命令 (create/show/add-member/register/issue/verify/
#         revoke-grant/revoke-member/audit/invite/import-invite);
#         团组审计日志 (team_audit.jsonl, 追加链不可篡改);
#         跨机邀请令牌 export_invite/import_invite (远程+局域网加入);
#         web 团组面板 (成员/供应商/授权三列管理 + 能力矩阵展示)。
# v0.4.5: 安全审计修复轮 —— 0.4.4 完整安全审计总报告的 P0 全部 6 项 + P1 12 项
#         + P2 7 项修复 (截断 fail-closed、Web/MCP 统一鉴权与审批票据、egress
#         交集收窄、out_path 边界、apikey 白名单、学习器 HMAC+投毒门、scene_js
#         强化、服务级破坏升红线等); 「真实接入」补齐 (Notebook/Artifact/
#         Messaging/Subagent/Workflow 五个工具插件接入 Agent 工具面);
#         构建/测试文件内容预扫描 (P1-07)。
__version__ = "0.4.5"
