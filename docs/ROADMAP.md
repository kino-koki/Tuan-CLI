# 发布路线图：从 0.3.1 到 1.0

> 本文档回答两个问题：**API 什么时候冻结、怎么冻结**，以及**社区里程碑怎么走**。
> 配套约束见 [VERSION_POLICY.md](../VERSION_POLICY.md) 与 [TUAN.md](../TUAN.md)。
> 版本语义：`0.x` 允许破坏性调整（须公告 + 迁移提示），`1.0` 才承诺向后兼容。

## 1. 现状（2026-10-18）

- 当前版本 `0.3.1`，公共 API **未冻结**：CLI 子命令表面、配置 schema、工具协议、插件契约都还可能变。
- `CHANGELOG.md` 的 `[Unreleased]` 已积累一批修复与新特性（工作区路径、提示词档位、TUI 命令面板、WebUI 流式），按版本策略应发 `0.4.0`（含向后兼容新功能 → 升 MINOR）。
- 质量门禁已就位：安全基准 CI（`bench/security-bench.json` 对比）、版本策略门禁（`scripts/check_version_policy.py`）、mypy、pytest（含超时防挂起）。

## 2. 1.0 的定义：冻结清单

进入 `1.0` 意味着以下对外契约**只增不改、破坏性变更升 MAJOR**：

| 契约面 | 冻结内容 | 现状 |
|---|---|---|
| CLI 表面 | 全部子命令名、参数、退出码、`--print`/`-p` 语义 | 0.x 内仍可调整 |
| 配置 schema | `config.schema.json` 的键、类型、默认值语义 | 0.x 内仍可调整 |
| 工具协议 | 内置工具名与参数（shell/read/write/mcp 等） | 0.x 内仍可调整 |
| 插件契约 | `@plugin` 元数据、`kernel.provide/require`、事件总线语义 | 0.x 内仍可调整 |
| 记忆与账本格式 | `~/.tuan` 下 memory/sessions/security-audit.jsonl 的读写格式 | 0.x 内仍可调整 |
| 生态桥接格式 | `tuan ecosystem` 双向搬运的目录/文件格式（SKILL.md、`.claude/agents`、MCP 配置） | 0.x 内仍可调整 |

## 3. 分阶段计划

### 阶段一：0.4.0（下一个发版，1–2 周）
- 把 `[Unreleased]` 的特性与修复正式发版：工作区路径修复、提示词档位、TUI 命令面板、WebUI 流式/思考过程。
- ~~**补 provider 目录契约测试**：58 个 ProviderPreset 的结构校验（字段完整性、去重、key 命名规范），防止目录漂移。~~ ✅ 已完成：`tests/test_provider_catalog_contract.py`（8 个用例，`93da772`）。
- ~~**新增 `examples/` 示例集**（3 个可跑通场景）：安全拦截演示、生态互操作、离线模型（Ollama）。~~ ✅ 已完成：`examples/{safety_demo,ecosystem_scan,offline_ollama}.py` + README（`e72f347`）。
- 附加：`tuan safe bench --json` 机器可读输出 + `bench/results/` 时间序列存档，安全数字可直接进 CI（`d943f29`）。
- 发版动作：版本号 → `0.4.0`，`CHANGELOG` 归档，跑全量测试 + 安全基准 + mypy。

### 阶段二：0.5.x（API 收缩期，1–2 个月）
- **冻结 config schema 与插件契约**：此后这两个面只新增、不修改既有键/签名；任何修改视为破坏性变更并触发 MAJOR 讨论。
- 引入**契约测试**：对冻结面写兼容性断言（旧配置可被新版本读取、旧插件签名仍可用），CI 强制。
- CLI 表面进入「公告冻结」：改动需在 CHANGELOG 提供迁移提示 + 一个版本的过渡期。
- 同步发布 `migration` 工具：`tuan doctor` 增加「配置/插件兼容性体检」。

### 阶段三：1.0（冻结）
- CLI 表面、工具协议、记忆与账本格式全部冻结；向后兼容成为承诺。
- 发布节奏进入 LTS 语义：MAJOR 每 12–18 个月，MINOR 每月，PATCH 按需。

## 4. 社区里程碑（与版本并行）

| 里程碑 | 目标 | 可度量指标 |
|---|---|---|
| 示例与文档站 | 新手 10 分钟跑通 | examples/ 3 例 + QUICKSTART 更新 |
| 公开安全基准页 | 第三方可复跑 | `tuan safe bench` + 发布 HTML 报告到 GitHub Pages |
| 贡献者漏斗 | 外部首个 PR 合并 | GOOD_FIRST_ISSUES 清单被认领 |
| 发布节奏 | 每周一个 PATCH/文档更新 | 稳定且可预期的 release 频率 |
| 生态对标 | 与 Claude Code/Hermes 的对比报告定期更新 | `bench/vs_claude.py` 结果入库 |

## 5. 评审与变更

- 本路线图随版本策略一起维护：修改须走 PR + 版本策略门禁。
- 里程碑优先级可调整，但**冻结顺序建议保持**：先 schema/插件（内部契约），后 CLI/格式（用户契约）。
