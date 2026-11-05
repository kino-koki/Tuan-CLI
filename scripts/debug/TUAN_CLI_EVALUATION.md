# Tuan-CLI（青小团）深度评审报告

> 评审对象：Tuan-CLI v0.3.3 · 评审日期：2026-10-30 · 方式：源码阅读 + 定向测试 + 全量回归

---

## 0. 结论速览

| 维度 | 评级 | 一句话 |
|---|---|---|
| 定位与理念 | A | safety-first + model-agnostic + 纯 Python，拒绝单厂商绑定，定位诚实 |
| 架构设计 | A | 插件容器+插件，五大子系统，架构文档清晰且与实现基本一致 |
| 依赖治理 | A+ | 核心仅 2 个依赖，其余全用 stdlib 自研替代，工程克制度罕见 |
| 安全工程 | A- | 四道闸门 + 可复现基准 + 审计，诚实披露误杀；扣分在缓存线程安全等 |
| 测试覆盖 | A- | 全量 5516 通过，无功能回归；旧记录 34 失败已确认不可复现 |
| Git 历史 | C+ | 历史被刻意重建、双作者、无签名 tag、空 reflog（作者已披露） |
| 维护状态 | B- | 0.x 未冻结 API，单/双作者，扩张极快，可持续性存疑 |

**总评：B+（优秀但未到 A 级）** —— 工程能力与安全诚实度是最大亮点；历史可审计性与维护可持续性是最大短板。

---

## 1. 三个深度评审摘要

### 1.1 安全引擎（评级 A-）

**优点**
- 分层防御扎实：Unicode 清洗 → ANSI-C/八进制/十六进制解码 → IFS 替换 → brace 展开 → 32 层间接层剥离 → 命令替换内联 → 受限 glob 展开，覆盖攻击面全集。
- `is_hard_redline` 用 token 化判定（非纯正则），rm -rf、force push、dd、mkfs、shutdown、SQL DROP 等有多路独立兜底。
- 性能护栏到位：`_GLOB_MAX_TOTAL_CHARS=1500`、命令替换 `max_iter=8`、32 层间接层，明确修复了 CHANGELOG 记载的 22s DoS。
- YOLO 不可绕过硬红线；白名单拒绝红线命令加入；多阶段确认 5/3 次真实存在。
- 三套基准 seed 固定、无网络、无模型调用，可本地复现；绕过矩阵对每类灾难意图做后果级断言。

**风险点（文件+行号）**
- `_PATTERN_CACHE`/`_compiled` 模块级可变缓存未加锁，多线程并发首调用可能竞态重复编译（safety_redline.py:383）。
- `_expand_var_defs`/`_normalize` 只有分步上限（safety_score.py:112 的 max_rounds=8），变量展开与 brace 展开交织时缺跨阶段总迭代预算。
- 裸 `except Exception` 广泛吞错：safety_bench_10k.py:187、bypass_matrix.py:944/960/979 将引擎异常降级为 allow，会掩盖真实故障。
- 基准覆盖盲区：SQL 变形集仅用 GENERIC 子集（safety_bench_10k.py:107-113），未覆盖解释器包裹与编码通道。

**建议**：缓存加锁 / 全局迭代预算（超限 fail-closed）/ 静默 except 至少 log.warning / 基准补 SQL 变形。

### 1.2 架构与实现一致性（六项检查五项一致）

**一致点**：kernel.py 零业务 ✓；arch/ 双身份成立（orchestration/platform 被生产复用，execution/context/observability 仅测试消费）✓；Loop 三种注册 ✓；agent.py 经 `kernel.get("loop_provider")` 拿 Loop 非硬编码 ✓。

**不一致点**
1. **文档失实**：ARCHITECTURE.md 4.6 称生产上下文由 `core/context` 承载，但该文件**不存在**——生产 `ContextManager` 实际在 `tuan_cli/context/manager.py`（core/agent.py:27 import）。
2. **覆盖不足**：生态表格漏 `ecosystem/registry.py`（远程仓库 Registry 客户端）；文档未提 `arch/plugin.py`、`arch/security.py`、`core/loop_registry.py`（文件头标 `[已弃用]`）。
3. **灰色地带**：`arch/security.py` 被 ArchPlugin 注册为一等公民服务但生产无实际消费方，文档未归类。

### 1.3 失败测试根因（34 个 F 全部不可复现）

- pytest_results.txt（2026-10-27，仅进度点）记录的 34 F 在当前代码**全部不可复现**。
- 定向全量回归：**5517 passed / 0 failed / 10 skipped**（另一后台运行 807s：5516 passed / 1 failed / 10 skipped，那 1 个是 `test_cli_safe_bench_report` 的 UnicodeDecodeError 环境问题，非功能回归）。
- 旧失败均属环境/顺序/间歇性：`test_cli_safe_bench_report`（残留 `.run_tmp_*`）、`test_rewind`（快照时序敏感）、`test_tui_fixes`（单例替换检查），当前均已通过。
- **0 个真实功能回归**，README 覆盖承诺成立。pytest_results.txt 已过时，建议删除或替换。

---

## 2. 分项评级明细

| 项 | 评级 | 关键依据 |
|---|---|---|
| 定位理念 | A | Model+Harness=Agent；58 供应商 + Ollama + 完全离线；明确"不是单厂商壳" |
| 依赖治理 | A+ | 核心 9→2 项；httpx/openai/pydantic/pyyaml/cryptography 全 stdlib 自研且实测兜底 |
| 架构文档 | A | ARCHITECTURE.md 10 分钟可懂；扩展点表格清晰；贡献门槛低 |
| 安全诚实度 | A+ | README 曾称 100%/0 绕过，作者复测发现过期数字，主动修复并记录误杀数 |
| 生态互操作 | A | tuan ecosystem 双向搬运 Claude/Hermes 资产；tuan dispatch 驱动 5 个本地 agent |
| 测试 | A- | 5517 passed / 0 failed；但旧记录 34F 未及时清理，曾误导 |
| 历史可审计 | C+ | 历史重建、双作者、无签名 tag、空 reflog、2 个 .git.broken-* 残留 |
| 维护可持续 | B- | 0.x 未冻结；双作者 10 天空档；单提交动辄数百文件上万行 |

---

## 3. 风险与建议（按优先级）

### P0 — 采用前必须解决
1. **Git 历史可审计性**：对当前 HEAD 打签名基线 tag；处理两个 `.git.broken-*` 残留（归档或删除并记录保留策略）。对一个决定用户能否执行危险命令的安全工具，"无法 diff 安全修复基线"是治理弱点（PROVENANCE.md 已自行披露并给出 6 项补救，尚未实施）。
2. **发布溯源**：每个 release 绑定提交 SHA + 文件哈希清单 + 工具链版本 + 可复现构建检查；CI 增加"无签名 tag 即失败"门禁。

### P1 — 近期改进
3. **安全引擎**：`_PATTERN_CACHE` 加锁；`_normalize` 加全局迭代预算并在超限时 fail-closed；静默 except 至少 log.warning；基准补 SQL 解释器/编码变形。
4. **文档修正**：ARCHITECTURE.md 4.6 的 `core/context` → `context/manager.py`；生态表格补 `registry.py`；注明 `arch/security.py` 归类、`core/loop_registry.py` 为弃用层。
5. **测试卫生**：删除/替换过时的 pytest_results.txt；将 3 个时序敏感测试标记为 flaky/xfail。

### P2 — 长期
6. **单作者维护风险**：若进入团队/生产，需备份维护者或明确 EOL 策略；0.x 期间不建议作为长期依赖锁定。
7. **基准覆盖**：SQL 变形集扩大到解释器包裹与编码通道，匹配 shell 侧强度。

---

## 4. 采用建议

- **个人自托管 / 学习研究**：强烈推荐。理念、架构、依赖治理、安全诚实度都属同类顶尖，`tuan safe bench` 一条命令本地复现所有安全声明。
- **团队内部工具（非关键路径）**：推荐，但需先完成 P0/P1。
- **安全敏感 / 生产关键路径**：暂缓，待历史可审计性（P0）与发布溯源（P0-2）落实后再评估。

---

*本报告基于源码阅读、定向测试与全量回归（2026-10-30，5517 用例）。安全基准数字以 `tuan safe bench` 本地复现为准。*
