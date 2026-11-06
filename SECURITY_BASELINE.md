# 安全基线（部署者必读）

> 本文面向**要把它跑在生产/托管环境里的人**，不是功能介绍。
> 目标是把「代码里有开关」和「部署时真的开了」分开说清楚，并明确当前设计**做不到什么**。
> 配套：`SECURITY.md` / `SECURITY_EN.md`（子系统权威说明）、`HARDENING.md`（加固工具）。

---

## 1. 一句话定位

Tuan-CLI 的安全模型是 **「确定性规则滤网 + 审计/回滚治理」**，边界主要落在**进程内的策略层**；
它不是「所有命令默认跑在 OS 级沙箱里」的执行器。这个差别决定了下面的部署要求：**必须在外面再垫一层隔离**。

不要只靠提示词、系统提示、模型对齐或静态红线来挡提示注入。自适应攻击下已发表的防御基本都可被绕过，
本项目 `bench/` 里的 10k / 5k / 2497 条数字是**自建静态数据集**，只用于回归门禁，不构成对抗真实攻击者的证明。

---

## 2. 本次加固（可复跑验证）

| 编号 | 问题 | 修复 |
|---|---|---|
| R1 | `SandboxManager.DEFAULT_POLICY.enforce_required=False` 与 `config/defaults.py` 的 `True` 冲突；`sandbox:` 段覆盖后漏写该键会静默降级为裸执行 | 两处统一为 `True`；新增「局部覆盖不丢失」回归用例 |
| R2 | 显式指定的强隔离后端不可用时 `fail-soft` 回落到 auto，可能最终落到 `local` 裸执行 | 返回 `(prefer, False)`，交由 `HardIsolationFilter` 在 `enforce_required=True` 时拒绝 |
| R3 | 6 处异常路径 `except: pass` = 静默放行（网络探测、红线引擎导入、网络红线判定、域名白名单、凭据扫描、域名解析） | 全部改为 fail-closed：拒绝或升级人工确认 |
| R4 | `pip/npm/yarn/pnpm/poetry/uv install`、`pytest/tox/nox/go test/cargo test/mvn/gradle/make` 被判「良性零确认」，但会执行仓库内 `postinstall` / `conftest.py` / `build.rs` / `Makefile` | L0 新增确认门控（`CONFIRM`，非 `DENY`），`--help/--version` 变体不触发 |
| R5 | 加固项只有文档、没有态势检查 | `tuan harden status` 输出 `enforce_required` / 默认禁网 / 域名白名单 / 强后端可用性，并列出待加固项 |
| R6 | E2 信任衰减**只有测试调用**：CLI 与 Web 都直接读 `record.level`，衰减从未生效；扫描异常 `except: pass` 静默放行；`last_used` 从不更新导致活跃工作区 30 天后被误判过期 | `check_trust()` 主链路自动衰减 + 敏感面指纹基线 + 扫描失败 fail-closed + `last_used` 自动维护 + 降级原因可观测 |
| R7 | E5 写风暴「不同文件数」按会话累计，触发后永久告警，与 60 秒滑动窗口矛盾；告警文案把次数误写成秒数 | 文件维度与次数维度共用窗口、告警态随窗口复位、修正文案 |

回归：`tests/test_fail_closed_regressions.py`（37 例）、`tests/test_e2_e5_hardening.py`（16 例）、
`bench/indep_verify.py`（29 例）、安全/i18n/文档一致性子集共 273 例通过。

```bash
python -m pytest tests/test_fail_closed_regressions.py tests/test_e2_e5_hardening.py -q
python bench/indep_verify.py
tuan harden status
```

---

## 3. 生产部署基线（务必照做）

### 3.1 外面必须垫一层

把**整个 Tuan 进程**放进一次性容器或 VM，而不是指望 `--isolation`：

- 只读挂载代码，工作区单独可写卷；
- 容器以非 root 运行，禁止挂载 `/var/run/docker.sock`；
- 出网走代理 + 域名白名单，默认拒绝；
- 不把长期密钥、云凭据、`~/.ssh` 放进同一文件系统视图；
- 用完即毁，不复用容器跑第二个不可信任务。

`--isolation` / `--sandbox` 是 **engine/process 级**隔离，用于缩小爆炸半径和隔离失败，
**不是完整 OS 沙箱**（README 已明确）。默认配置下，绝大多数命令**不进入** L3 强隔离。

### 3.2 配置（`config.yaml`）

```yaml
sandbox:
  enabled: true
  backend: auto                      # 确保机器上真有 docker / bwrap / seatbelt 之一
  enforce_required: true             # 无强后端时拒绝, 绝不裸执行 (必须保持 true)
  deny_unknown_shell: true           # 未知信任工作区的 shell 直接拒绝
  allowed_domains:                   # 出网域名白名单, 生产不要留空
    - pypi.org
    - registry.npmjs.org
    - github.com
  resource:
    deny_network_by_default: true     # 默认禁网 (出厂为 false, 生产请开启)
    max_memory_mb: 2048
    max_timeout: 300
    isolate_copy_threshold: high

security:
  network:
    deny_remote_exec: true
    deny_data_exfil: true
    one_way_mode: true
    egress_cidr_allow: []            # 按需收紧
  mcp:
    audit_enabled: true
    block_on_injection: true
```

> 开启 `deny_network_by_default` 后，含网络特征的命令会 `network=False + isolate=True`。
> 若机器上没有可用强后端且 `enforce_required=true`，这些命令会被**拒绝**——这是预期行为，
> 不是 bug：先装好隔离运行时，再谈出网。

### 3.3 运行态检查清单

- [ ] `tuan harden status` 显示 `fail-closed=OK`、`默认禁网=OK`、强后端非空
- [ ] `tuan harden repro-lock --verify --out requirements.lock` 通过（依赖未漂移）
- [ ] `tuan harden sbom` 产出 SPDX，且发布件与 SBOM 对应
- [ ] 审计日志落在进程外的追加式存储（WORM / 自签名链），不要只信工作区里的 `.git/logs`
- [ ] 发布 tag 已签名（`git tag -s`），且能从干净 checkout 复现构建
- [ ] 对不可信仓库跑任务时，人工审批通道可用且**审批超时按拒绝处理**

---

## 4. 已知局限（不回避）

1. **规则层在前、内核层在后**：L3 强隔离只在 `verdict.isolate` 为真时触发，而 `isolate` 主要由「severity ≥ high」或「开启默认禁网」置位。这不是「所有命令默认在 OS 沙箱内」。要获得与内核级沙箱等价的保证，只能靠 §3.1 的外部容器/VM。
2. **网络管控是「看命令文本」**：`NetworkGuard` 识别命令串里的域名/IP/CIDR 特征，不是出网路径上的强制拦截。绕过字符串识别的外传（如被注入的子进程自行联网）需要外部代理兜底。
3. **静态基准 ≠ 对抗鲁棒性**：自建 10k 对抗样本、2497 条 bypass matrix 用于回归；项目未提供第三方自适应红队报告。误杀/漏拦数字请自行本地复跑后再引用。
4. **YOLO 仍会放大风险**：`--yolo` 自动批准本需确认的操作（硬红线仍拒）。托管服务不要开；也不要把「永远允许」类持久规则交给模型提议。
5. **发布溯源**：发布时建议为 tag 签名（`git tag -s`），并在每次发布附上提交 SHA、文件清单哈希与工具链版本，使「发布件是否等于测试件」可独立核验。
6. **成熟度**：单人维护、无第三方安全审计、无公开 CVE/公告流程。`SECURITY_EN.md §8` 的 E1–E8 仍是未完成项，其中 E1（MCP server 信任分级 / 会话内可撤销授权）、E2（信任自动衰减）、E5（写风暴检测）与安全直接相关，优先级最高。

---

## 5. 不要做的事

- 不要在没有外部容器/VM 的宿主机上，用长期云凭据跑不可信仓库的自主任务；
- 不要为了「少弹窗」把 `enforce_required` 改回 `false` 或把 `deny_network_by_default` 永久关掉；
- 不要把 `pip install` / `pytest` 的确认当成噪音批量「始终允许」；
- 不要用 `bench/` 的数字对外宣称「100% 防提示注入」。

---

## 6. 复现

```bash
pip install -e ".[dev]"
python -m pytest tests/test_fail_closed_regressions.py -q
python -m pytest tests/test_sandbox_system.py tests/test_security_integration.py -q
python bench/indep_verify.py
python -m tuan_cli.cli.cmd_harden status   # 或安装后: tuan harden status
```
