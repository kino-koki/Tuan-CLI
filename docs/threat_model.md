# Tuan-CLI 威胁模型：P1/P2 攻击面现状

## 目的
本文档记录 2026-11 安全审计列出的 P1/P2 攻击面在当前代码中的处置状态：每个向量给出攻击面说明、现状结论（已覆盖 / 部分覆盖 / 未覆盖 / 待复核）与代码证据（file:line）。P0 项不在本文展开，统一见 `docs/security_remediation_20261118.md`。

## 范围
- 对象：Tuan-CLI 仓库（`tuan_cli/`）中与下列 11 个 P1/P2 攻击向量相关的代码路径。
- 结论分级：已覆盖 / 部分覆盖 / 未覆盖 / 待复核。
- 文末附汇总表与「范围与局限」。

## 方法
- 静态代码检视 + 定向 grep 取证；引用均为实际命中的 file:line。
- 不进行动态利用、 fuzzing 或运行时验证；无法快速确证的项如实标注「待复核」。

## 攻击面现状
### 1. Git 配置注入：`git -c core.hooksPath=` / `core.fsmonitor` / `core.pager`
**攻击面说明**：通过 `-c` 临时配置或写入 `.git/config` 把 `core.hooksPath` 指向攻击者目录，后续任意 git 操作都会执行该目录下的 hook，形成持久化 RCE；`fsmonitor`、`core.pager` 属同类「配置键即执行向量」。

**现状**：已覆盖。
- tuan_cli/ext/safety_redline.py:1469 — 硬红线模式 `git -c core.(hooksPath|fsmonitor|pager)=`。
- tuan_cli/ext/patterns_data/critical.py:1104、1121 — `git config core.hooksPath` 写入与 `core.sshCommand/core.fsmonitor/include.path` 亦判 critical。
- tests/test_audit_remediation.py:328 — `git -c core.hooksPath=/tmp/evil commit -m x` 断言 hard redline 且 block。

**关键缓解**：命令进入安全引擎即被 hard redline 拦截，不依赖事后审计。

**残余风险**：键名为枚举式防御，未列举的 git 配置键及 `GIT_CONFIG_*` 环境变量等价注入形态需持续补充。

### 2. `ssh ProxyCommand`
**攻击面说明**：`ssh -o ProxyCommand='任意命令'` 在建立连接前执行攻击者命令，可借「连接远程主机」的外壳夹带任意执行。

**现状**：已覆盖。
- tuan_cli/ext/safety_redline.py:1470 — 硬红线模式 `\bssh\b[^\n]*ProxyCommand\s*=`。
- tests/test_audit_remediation.py:329 — `ssh -o ProxyCommand='evil' host` 断言 hard redline 且 block。

**关键缓解**：含 ProxyCommand 的 ssh 命令直接红线拦截。

**残余风险**：其它可执行型 ssh 选项（如 `LocalCommand`）在模式库中无专门命中（grep 无结果），目前仅靠通用危险命令兜底。

### 3. `sed s///e`（替换结果执行标志）
**攻击面说明**：GNU sed 的 `s///e` 标志会把替换结果当作命令执行，攻击者可用看似文本处理的 sed 命令夹带任意命令执行。

**现状**：已覆盖。
- tuan_cli/ext/safety_redline.py:1471 — 硬红线模式，兼容任意分隔符与 flag 组合（`s[/|]…[/|]…[/|][a-zA-Z]*e\b`）。
- tuan_cli/ext/safety_patterns.py:1658 — 高危模式库同款，供评分引擎复用。
- tests/test_audit_remediation.py:330 — `sed -n 's/x/evil/e;p' f` 断言 hard redline 且 block。

**关键缓解**：`s///e` 形态（含混合 flag、任意分隔符）命中即红线拦截。

**残余风险**：模式限定 `s` 命令；GNU sed 原生 `e` 命令（如 `sed 'e cmd'`）等其它执行形态未见专门覆盖。

### 4. SUID 注入（`chmod u+s` / `find -perm -4000`）
**攻击面说明**：给二进制设置 SUID 位（`chmod u+s`、`install -m 4755`）可预置 root 提权后门；`find -perm -4000` 枚举系统既有 SUID 文件，是提权前的侦察步骤。

**现状**：已覆盖。
- tuan_cli/ext/patterns_data/critical.py:501 — `chmod … u+s` 判 critical（SUID 提权后门）。
- tuan_cli/ext/safety_patterns.py:598-599 — `find … -perm -[246]xxx` 判高危（SUID 文件枚举侦察）。
- tests/test_audit_remediation.py:331 — `install -m 4755 /bin/sh /tmp/rootsh` 断言 hard redline 且 block。

**关键缓解**：设置 SUID 位即 critical 硬红线；枚举 SUID 文件判高危告警。

**残余风险**：file capabilities（`setcap`）等不经过 SUID 位的提权路径未在已验证模式内。

### 5. 出网域名白名单经工具参数放宽
**攻击面说明**：模型在工具参数里自带 `allowed_domains=["evil.example"]`，若被直接采信即可覆盖用户配置的全局出网白名单，为数据外泄开路。

**现状**：已覆盖。
- tuan_cli/sandbox/egress_allowlist.py:195-223 — `claim_from_args` 默认 `trusted=False`：工具参数声明只与全局策略**取交集**（source=`tool_args_intersect`），无全局策略时交集为空 → 一律拒绝。
- tests/test_audit_remediation.py:186-197 — 断言 `evil.example` 在有/无全局策略下均不可放行（P1-10）。

**关键缓解**：「只收窄、永不放宽」的交集语义，fail-closed。

**残余风险**：`trusted=True` 信任传递依赖调用方自律；`NetworkGuard.add_allowed_domain`（tuan_cli/core/network_guard.py:530，当前仓库内无调用方）若未来被暴露给模型输入即可放宽。

### 6. TTS / 视频 `out_path` 越界写
**攻击面说明**：TTS 与视频渲染工具接受 `out_path` 参数，若不校验可把任意内容写到工作区之外（任意路径写 → 篡改系统文件/持久化）。

**现状**：已覆盖。
- tuan_cli/ecosystem/mcp_server.py:667-675 — TTS `out_path` 经 `resolve()+relative_to` 校验，越界 fail-closed 返回 `out_path 越界` 错误（审计 P1-12）。
- tuan_cli/ecosystem/mcp_server.py:628-632 — 视频 pipeline `out_path` 同一边界检查。
- tests/test_audit_remediation.py:202-210 — 工作区外 wav 被拒绝且不落盘。

**关键缓解**：resolve 后必须位于工作区内，否则拒绝执行（fail-closed）。

**残余风险**：其余接受路径参数的 MCP 工具是否全部套用同一边界未逐一审计。

### 7. `iptables -F`（防火墙规则清空）
**攻击面说明**：`iptables -F` 清空全部防火墙规则，配合 `-X`/默认策略修改可使主机网络防护归零，为横向移动与数据外泄开路。

**现状**：已覆盖。
- tuan_cli/ext/safety_redline.py:1463 — 硬红线模式 `\biptables\b[^\n]*\s-F\b`（flush 服务级网络防护）。
- tuan_cli/ext/safety_patterns.py:1235、850-852 — `iptables -X` 清自定义链、DROP/REJECT/REDIRECT/DNAT 与默认策略修改均命中。
- tests/test_audit_remediation.py:324 — `iptables -F` 断言 hard redline 且 block。

**关键缓解**：flush/清链/改默认策略/加丢弃规则均判红线拦截。

**残余风险**：nftables 侧仅覆盖 `nft add rule drop/reject/queue`（tuan_cli/ext/safety_patterns.py:853-854），`nft flush ruleset`、`ufw reset` 等等价清空操作未见专门模式。

### 8. 凭证读取与转移（~/.ssh、~/.aws、.npmrc + 外传）
**攻击面说明**：读取 `~/.ssh`、`~/.aws`、`.npmrc` 等凭证文件并经网络/编码通道外传，是凭证窃取的核心链路（读取 → 落盘/转移 → 外发）。

**现状**：已覆盖。
- tuan_cli/ext/security_gate.py:322-330 — `_SYSTEM_PATH_RE` 覆盖 `.ssh/.aws/.gnupg/.kube/.docker/.npmrc/.pypirc/.netrc/.gitconfig`、`id_rsa/id_ed25519` 等私钥与 `.pem/.key/.p12/.pfx`；命中即「需确认」（ defense-in-depth，非放行）。
- tuan_cli/core/taint_exfil.py:34-76 — 污点追踪：凭证源（.ssh/.aws/私钥/历史/令牌环境变量）× 外部汇（curl/scp/base64/`/dev/tcp`/剪贴板）× 数据流（重定向/管道/tee/cp/mv/install/dd），fail-closed、只收紧不放行。
- tests/test_audit_remediation.py:327 — `cp ~/.ssh/id_rsa /tmp/x` 断言 hard redline 且 block。

**关键缓解**：敏感路径读取需确认 + 凭证转移升红线 + 数据流污点判定，三重独立防线。

**残余风险**：正则启发式对新型凭证文件名与非常规编码/隐蔽通道可能漏检，属纵深防御而非完备保证。

### 9. 硬红线被本地黑名单抑制绕过
**攻击面说明**：本地黑名单抑制文件本身可被 Agent 写入；若硬红线 label 也能被抑制，Agent 可「自我提权」关闭针对自己的拦截。

**现状**：已覆盖。
- tuan_cli/ext/safety_redline.py:546-564 — `_label_suppressed` 对 `_CRITICAL_LABELS` 一律返回 False（不可抑制）；任何异常（导入/读取失败）也按「未抑制」处理，保持默认拦截。
- tuan_cli/ext/safety_redline.py:600-604 — 抑制仅对非 critical 正则模式生效；token 化硬红线（rm -rf / force push 等）走独立判定，完全不受抑制影响。
- tests/test_audit_remediation.py:339-349 — 即使强制抑制表对任意 label 返回 True，critical label 仍判定为未抑制（P1-18）。

**关键缓解**：critical label 硬编码不可抑制 + 异常 fail-closed。

**残余风险**：非 critical label 仍可被本地抑制（设计内的「黑名单减负」）；若某模式被错误降档为非 critical，则存在被滥用空间。

### 10. 配对码进入 WebSocket hello
**攻击面说明**：若 WebSocket hello 帧回带配对码，任何能连上端口的人都能「回传刚收到的码」完成自配对，远程控制通道被未授权接管。

**现状**：已覆盖。
- tuan_cli/web/dispatch_server.py:142-159 — hello 载荷仅含 protocol/hostname/version/agents 等；配对码只打印到本机 stderr 由用户手工输入（审计 P1-19：配对码绝不进 hello）。
- tuan_cli/web/dispatch_server.py:181-199、205-221 — `pair` 消息必须匹配 `session.pair_code`，错误即 4401 关闭；未配对连接不得 `list_agents`/`dispatch`。
- tuan_cli/core/remote_control.py:47-51 — 远控会话带一次性 token 消费、设备指纹绑定、确认尝试防爆破计数。

**关键缓解**：配对码不出网（仅本机 stderr 展示）+ 未配对会话权限隔离 + token 一次性/设备绑定。

**残余风险**：配对码会写入本机审计事件（如 dispatch_server.py:167 `pairing_expired`、:193 `pair_ok` 携带 code），能读本机审计日志者在 TTL 窗口内仍存在重放可能。

### 11. `scene_js` 注释填充绕过
**攻击面说明**：场景 JS 以注释填充或字符串拆写绕过静态黑名单（如 `import("child"+"process")`、`globalThis["Function"]`、`process.binding`），在渲染侧实现任意代码执行。

**现状**：已覆盖。
- tuan_cli/web/mh_runner.py:158-188 — `validate_scene_js` 先剥离 `/* */` 注释再判定禁止调用/拆写动态执行/进程边界访问；注释不可作为绕过载体。
- tuan_cli/web/mh_runner.py:284-294 — `write_scene_js` 落盘前强制校验，校验失败不写盘。
- tests/test_audit_remediation.py:299-316 — 四类注释填充/拆写载荷全部被拒，正常场景脚本不受影响（P1-20）。

**关键缓解**：写入前静态字符串校验（永不 eval），注释先剥离再扫描。

**残余风险**：静态校验无法覆盖全部 JS 混淆与未枚举的全局对象/间接调用形态，新绕过需持续补充规则。

## 汇总表

| # | 攻击向量 | 现状 | 关键缓解 | 残余风险 |
|---|----------|------|----------|----------|
| 1 | `git -c core.hooksPath/fsmonitor/pager` | 已覆盖 | 硬红线模式 + critical 打分 | 未列举配置键 / `GIT_CONFIG_*` 环境变量形态 |
| 2 | `ssh ProxyCommand` | 已覆盖 | 硬红线拦截 | `LocalCommand` 等其它执行选项未单列 |
| 3 | `sed s///e` | 已覆盖 | 红线（任意分隔符/flag 组合） | GNU sed 原生 `e` 命令未单列 |
| 4 | SUID 注入（u+s / -perm -4000） | 已覆盖 | chmod u+s critical；find -perm 高危 | `setcap` 等 capabilities 路径未验证 |
| 5 | 出网白名单经工具参数放宽 | 已覆盖 | 交集语义只收窄 + 无策略即拒 | `trusted=True` 误用 / `add_allowed_domain` 暴露面 |
| 6 | TTS/视频 `out_path` 越界 | 已覆盖 | resolve + relative_to fail-closed | 其它路径型 MCP 工具未逐一审计 |
| 7 | `iptables -F` | 已覆盖 | 硬红线（-F/-X/策略/DROP 族） | `nft flush ruleset`、`ufw reset` 未单列 |
| 8 | 凭证读取与转移 | 已覆盖 | 敏感路径确认 + 红线 + 污点追踪 | 启发式对新型凭证/隐蔽通道可能漏检 |
| 9 | 本地黑名单抑制硬红线 | 已覆盖 | critical label 不可抑制 + fail-closed | 非 critical 抑制仍可用（设计内） |
| 10 | 配对码进 WebSocket hello | 已覆盖 | hello 不含配对码 + 未配对权限隔离 | 配对码入本机审计日志，TTL 内可被本机读者重放 |
| 11 | `scene_js` 注释填充绕过 | 已覆盖 | 写入前剥注释静态校验 | 新混淆/间接调用形态需持续补充 |

## 范围与局限
- 本文为**静态代码检视 + 定向 grep 取证**，未做动态利用、fuzzing 或运行时验证；结论反映「代码中存在对应防线与回归测试」，不等同于渗透测试通过。
- 模式库、污点追踪、scene_js 校验均为**正则/字符串启发式**，是纵深防御的一层，不构成安全边界保证；绕过形态持续演变，规则需随之更新。
- **本文未覆盖 ≠ 安全**：未列入的攻击面、以及文中标注的未验证分支（`trusted=True` 调用方、非 critical 抑制、其它路径型工具、nftables/ufw 等价命令）仍需按向量逐一复核。
- 读者应在自己所在的 commit 重新执行文中 grep 与 `tests/test_audit_remediation.py` 相关用例复核现状，勿直接采信本文结论。
