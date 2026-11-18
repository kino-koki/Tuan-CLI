# 安全审计修复报告 (2026-11-18)

> 对应《Tuan-CLI 0.4.4 完整安全审计总报告》的修复落地清单。
> 每项: 审计编号 → 修复方式 → 回归证据。全部改动已推送 main。

## P0 (端到端可利用) — 6/6 修复

| 编号 | 修复 | 回归 |
|---|---|---|
| P0-01 截断绕过 | `_clamp_command` 超长命令替换为必命中红线哨兵; `_match_any` 超长行滑窗全覆盖 (512 窗/256 步长) | test_audit_remediation::test_truncation_* |
| P0-02 口径漂移 | `decide_mcp_tool` 对 run_shell 增加不截断 score() critical/block + 硬红线判定 | test_entrypoint_consistency |
| P0-03 Web 无鉴权 | `/api/*` 统一令牌鉴权 (首页 Set-Cookie HttpOnly+SameSite=Lax, 兼容 X-Tuan-Token); POST 同源校验 | test_web_requires_token / test_web_cross_origin_post_rejected |
| P0-04 匿名提权 | 高危 shell 审批改服务端一次性票据 (绑定命令/60s/用后即焚); 自报 approved 失效 | test_approval_ticket_not_self_reported |
| P0-05 MCP run_shell | `_h_run_shell` 增加不截断 score() critical/block 判定 | test_entrypoint_consistency |
| P0-06 团组明文密钥 | secret 移出 team_group.json → 独立 0600 侧文件; `/api/file` 拒读 `.tuan/`; grant/issue 不收请求体 owner | test_sensitive_file_read_blocked / test_create_and_persist |

## P1 — 12 项修复

| 编号 | 修复 |
|---|---|
| P1-08 | 工作区命令目录 (.tuan/.claude commands) 默认不加载, env/config 显式开启 |
| P1-09 | git -c hooksPath/fsmonitor/pager、ssh ProxyCommand、sed s///e、SUID 升红线 |
| P1-10 | egress 工具参数域名只与全局策略取交集 (只收窄) |
| P1-12/13 | TTS / video_pipeline 的 out_path 必须 resolve 后在工作区内 |
| P1-14 | apply_apikey 环境变量名白名单 (*_API_KEY) |
| P1-15 | 凭证读取 (cat /etc/shadow, ~/.ssh/id_rsa) score() 升 critical, 与硬红线口径一致 |
| P1-16 | iptables -F / systemctl mask/停用安全服务 / kubectl delete 关键资源 升红线 |
| P1-17 | 凭证转移 (cp/mv/rsync .ssh 私钥, /etc/shadow) 升红线 |
| P1-18 | 硬红线 label 不可被本地黑名单抑制 |
| P1-19 | Dispatch 配对码不进 WebSocket hello (仅本机 stderr); list_agents/approval 需 is_paired |
| P1-20 | scene_js 剥注释 + 危险能力匹配 (import/Function/binding/require/globalThis/拆写) |

## P2 — 7 项修复

| 编号 | 修复 |
|---|---|
| P2-21 | 学习器权重文件 HMAC-SHA256 签名 (0600 密钥文件), 篡改/越界拒绝载入 |
| P2-22 | observe() 的 safe 标签仅接受 user_confirm/cli 来源 (防在线投毒) |
| P2-24 | 仅排除模式 (!pattern) 的 allow/ask 权限规则跳过并告警 |
| P2-25 | sed s///e 红线覆盖 (部分; 启发式覆盖持续) |
| P2-26 | config.set_user 落盘失败不更新内存视图 |
| P2-28 | _guard_safety_check 异常真 fail-closed (旧代码注释与实现相反) |
| P2-32 | MCP ctx 提供只读 config kernel 视图, egress 策略查询不再被吞失效 |

## 如实保留的偏差

- **P1-07**: 良性开发命令的构建文件内容预扫描已实现 (阶段 1.7, 64KB/文件,
  1500+200 分块); 「默认信任工作区内容」的信任模型本身是文档化设计选择,
  更严格的 trust 级联 (untrusted 全禁) 留待产品决策。
- **P1-11**: 工具参数越权已封死; 「未配置全局策略时 egress 层不生效」的默认
  保留 (全局严格拒绝会阻断无策略部署的正常使用)。建议用户配置
  `permissions.network.allow_domains`。
- **P2-27**: network_guard 补齐 IP 整数/十六进制变体 (deny/high);
  tools/web.py 的 SSRF 解析层本就更强 (getaddrinfo 全解析)。
- **P2-29**: 静默吞异常治理 — 全仓 silent=0、SEC fallback=0 (护栏测试锁定);
  「设计内降级」日志规模是治理轮次的有意产物。
- **P2-30**: 已改 isolation/executor 的关键 assert; 其余低危 assert 暂留。
- **P2-31**: audio 路径边界已实现; 报告中的 ffmpeg 还原可行性仍未实测 (原审计亦未坐实)。
- **E-01~E-07**: 治理类 — 19 个 WIP 失败已在此前轮次修复; 版本号已同步 0.4.4;
  文档/发布流程建议不在代码修复范围。

## 验证

- 新增 `tests/test_audit_remediation.py` 21 例 (对应报告 §12.4) 全绿。
- 受影响套件全部重跑绿: gate/mcp/redline/sandbox 209、web 293、egress/权限 64、
  safety rounds 5-16/24_27 + redteam + risk_sandbox 118、team 51、codeanim 38、
  mh/workbench、dispatch/b3xv/security_modules 281、权限/学习器 161。
- 门禁: 版本政策 ✓ / shell=True 白名单 ✓ / 引擎镜像无漂移 ✓ / 护栏 silent=0 ✓。
