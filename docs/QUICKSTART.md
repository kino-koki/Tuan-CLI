# 青小团 CLI (Tuan-CLI) 快速上手指南

**版本:** 0.3.1 | **文档更新:** 2026-08-26

---

## 一、项目简介

青小团是一个**安全优先、会成长的插件化 Agent CLI**，融合了 DeepSeek Harness（微内核 + 模型中立）与 Hermes Agent（三层记忆 + 技能自进化）的理念。

### 核心特性

| 特性 | 说明 | 适用场景 |
|---|---|---|
| **安全红线 (Blast-Radius)** | 危险命令在执行前进行 blast-radius 分析并阻断 | 任何需要运行 shell 命令的场景 |
| **纯 Python 开箱即用** | 依赖极轻（pyyaml、rich、prompt_toolkit），无需 Node 工具链 | Windows/Linux/macOS 一致体验 |
| **模型中立** | 支持 51+ 家模型（含 Ollama/llama.cpp 本地） | 需要灵活切换模型的场景 |
| **自我进化闭环** | 从执行历史自动提炼规则与技能草稿 | 长期使用的开发者 |
| **进程级隔离** | 安全引擎可选独立 JSONL 子进程运行 | 需要最高安全级别的场景 |

---

## 二、快速开始（3 步）

### 步骤 1：安装

```bash
pip install tuan-cli
```

### 步骤 2：首次运行

```bash
tuan setup
```

这会启动初始化向导，帮你配置模型供应商、API Key 等基础设置。

### 步骤 3：开始使用

```bash
# 交互式对话（默认模式）
tuan

# 或直接运行任务
tuan run "帮我写一个 Python 函数计算斐波那契数列"
```

---

## 三、模式选择决策树

根据你的安全需求和场景，选择合适的运行模式：

```
开始
  │
  ├─> 我只是想快速对话，不关心安全？
  │     └─> 直接运行 `tuan`（默认标准模式）
  │           └─> 系统会在执行危险命令前提示你确认
  │
  ├─> 我在 CI/CD 环境中，需要自动批准？
  │     └─> 使用 `--yolo` 模式（自动批准危险操作）
  │           └─> tuan --yolo "你的任务"
  │
  ├─> 我在代码审查/规划阶段，不想修改任何文件？
  │     └─> 使用 `--plan` 模式（只读规划）
  │           └─> tuan --plan "分析这段代码"
  │
  └─> 我需要最高安全级别，即使牺牲性能？
        └─> 使用 `--isolation` 模式（进程级隔离）
              └─> tuan --isolation "你的任务"
```

### 模式对比

| 模式 | 命令 | 安全级别 | 性能 | 适用场景 |
|---|---|---|---|---|
| **标准模式** | `tuan` 或 `tuan --mode standard` | 中（需要确认） | 最高 | 日常开发 |
| **Yolo 模式** | `tuan --yolo` 或 `tuan --mode yolo` | 低（自动批准） | 最高 | CI/CD、已知安全环境 |
| **Plan 模式** | `tuan --plan` 或 `tuan --mode plan` | 最高（只读） | 高 | 代码审查、规划 |
| **Isolation 模式** | `tuan --isolation` | 最高（引擎独立进程） | 中（进程启动开销） | 安全敏感场景 |

### 权限模式（可选）

如果你更习惯 Claude Code 的权限模式，可以使用：

```bash
# 自动批准所有危险操作（等同于 --mode yolo）
tuan --permission-mode auto

# 完全不询问（等同于 --mode yolo）
tuan --permission-mode bypassPermissions

# 只读规划（等同于 --mode plan）
tuan --permission-mode plan
```

---

## 四、常见场景速查

### 场景 1：日常开发

```bash
# 1. 打开交互式对话
tuan

# 2. 让它帮你写代码
"写一个 Flask REST API，包含用户注册和登录接口"

# 3. 系统会在执行危险命令前提示确认
# 你可以手动输入 `y` 确认，或使用 `tuan --yolo` 自动批准
```

### 场景 2：CI/CD 中自动运行

```bash
# 使用 --yolo 自动批准，适合 CI 环境
tuan --yolo "运行测试并生成测试报告"

# 或使用 --print 输出到 stdout，方便管道化
tuan --print "分析代码并生成 lint 报告" > lint_report.txt
```

### 场景 3：代码审查（只读）

```bash
# 使用 --plan 模式，不会修改任何文件
tuan --plan "审查 src/ 目录下的所有 Python 文件，检查潜在的安全问题"

# 或使用 --permission-mode plan
tuan --permission-mode plan "重构这个模块，保持功能不变"
```

### 场景 4：安全敏感操作

```bash
# 使用 --isolation 模式，安全引擎在独立进程运行
tuan --isolation "在 test/ 目录下运行所有测试"

# 或组合使用：--isolation + --plan
tuan --isolation --plan "分析这个仓库的安全配置"
```

### 场景 5：后台运行任务

```bash
# 在后台运行，不阻塞终端
tuan agent "定期从 GitHub 下载最新数据并更新本地缓存"

# 查看后台任务进度
tuan bg list

# 查看日志
tuan bg logs <job_id>

# 等待任务完成
tuan bg wait <job_id>
```

---

## 五、核心子命令速查

### 会话管理

| 命令 | 说明 | 示例 |
|---|---|---|
| `tuan session list` | 列出最近的会话 | `tuan session list` |
| `tuan session resume <id>` | 恢复指定会话 | `tuan session resume 1` |
| `tuan session delete <id>` | 删除会话 | `tuan session delete 1` |
| `tuan session replay <id>` | 回放会话（事件溯源） | `tuan session replay 1` |
| `tuan session trajectory show <id>` | 显示会话轨迹摘要 | `tuan session trajectory show 1` |

### 开发循环

| 命令 | 说明 | 示例 |
|---|---|---|
| `tuan dev "任务"` | 自主开发循环（分析→实现→自测→核实→汇报） | `tuan dev "添加用户认证功能"` |
| `tuan dev codedev demo` | 代码开发演示 | `tuan dev codedev demo` |
| `tuan dev codedev doctor` | 检查子系统健康度 | `tuan dev codedev doctor` |
| `tuan dev codedev retrieve <task>` | 检索相关代码上下文 | `tuan dev codedev retrieve "如何实现文件上传"` |

### 安全管理

| 命令 | 说明 | 示例 |
|---|---|---|
| `tuan safe status` | 安全系统状态概览 | `tuan safe status` |
| `tuan safe allow <命令>` | 把命令加入白名单 | `tuan safe allow "rm -rf /tmp"` |
| `tuan safe deny <命令>` | 从白名单移除 | `tuan safe deny "rm -rf /tmp"` |
| `tuan safe blacklist` | 列出内置黑名单模式 | `tuan safe blacklist` |
| `tuan safe reduce <关键字>` | 抑制黑名单模式（本地减负） | `tuan safe reduce dd` |
| `tuan safe bench` | 一键复现安全基准 | `tuan safe bench --quick` |

### 配置管理

| 命令 | 说明 | 示例 |
|---|---|---|
| `tuan config get <key>` | 读取配置项 | `tuan config get model.provider` |
| `tuan config set <key> <value>` | 写入配置 | `tuan config set model.provider openai` |
| `tuan config dump` | 打印最终配置 | `tuan config dump` |
| `tuan config dump-default` | 打印内置默认配置 | `tuan config dump-default` |
| `tuan config profiles` | 列出可用预设 profile | `tuan config profiles` |

### 模型管理

| 命令 | 说明 | 示例 |
|---|---|---|
| `tuan models` | 配置/热切换模型供应商 | `tuan models` |
| `tuan models current` | 显示当前模型配置 | `tuan models current` |
| `tuan models list <provider>` | 列出某供应商的模型 | `tuan models list deepseek` |
| `tuan models switch <provider> <model>` | 热切换模型（当前会话） | `tuan models switch deepseek deepseek-chat` |
| `tuan models test` | 连通性测试 | `tuan models test --provider deepseek` |

### 记忆管理

| 命令 | 说明 | 示例 |
|---|---|---|
| `tuan memory list` | 查看长期记忆 | `tuan memory list` |
| `tuan memory search <query>` | 全文检索记忆 | `tuan memory search "我的 API Key"` |

### 定时任务

| 命令 | 说明 | 示例 |
|---|---|---|
| `tuan cron add <name> "<prompt>"` | 添加定时任务 | `tuan cron add "daily" "每天早上9点发送周报"` |
| `tuan cron list` | 列出任务 | `tuan cron list` |
| `tuan cron enable/disable <id>` | 启用/禁用任务 | `tuan cron enable 1` |
| `tuan cron start/stop/status` | 管理 Cron 守护 | `tuan cron start` |
| `tuan cron run <id>` | 立即执行任务 | `tuan cron run 1` |

### 自我改进

| 命令 | 说明 | 示例 |
|---|---|---|
| `tuan improve summarize` | 复盘执行历史，预览经验与规则 | `tuan improve summarize` |
| `tuan improve apply` | 把经验固化为规则与技能草稿 | `tuan improve apply` |

### 生态互操作

| 命令 | 说明 | 示例 |
|---|---|---|
| `tuan ecosystem scan` | 探测本机 Claude Code / Hermes 及其资产 | `tuan ecosystem scan` |
| `tuan ecosystem status` | 连接状态 + 资产计数 + 开关 | `tuan ecosystem status` |
| `tuan ecosystem import <kind>` | 导入对方生态资产到青小团 | `tuan ecosystem import skills` |
| `tuan ecosystem export <kind>` | 导出青小团资产到对方生态 | `tuan ecosystem export skills` |
| `tuan ecosystem serve` | 以 MCP stdio server 运行 | `tuan ecosystem serve` |

### 迁移工具

| 命令 | 说明 | 示例 |
|---|---|---|
| `tuan migrate status` | 查看是否已迁移 | `tuan migrate status` |
| `tuan migrate detect` | 扫描旧版状态（只读） | `tuan migrate detect` |
| `tuan migrate run` | 执行迁移 | `tuan migrate run` |

### 帮助与教程

| 命令 | 说明 | 示例 |
|---|---|---|
| `tuan help` | 显示总帮助 | `tuan help` |
| `tuan help <子命令>` | 显示子命令帮助 | `tuan help dev` |
| `tuan tutorial list` | 列出可用教程 | `tuan tutorial list` |
| `tuan tutorial run <name>` | 运行教程 | `tuan tutorial run safety` |

---

## 六、调试与诊断

### 环境健康检查

```bash
# 基础检查
tuan doctor

# 额外跑上下文压缩存活自检
tuan doctor --compact

# JSON 输出，适合脚本消费
tuan doctor --json

# 检查网络配置
tuan doctor --network
```

### 查看版本

```bash
# 查看当前版本
tuan --version

# 或
tuan --v  # 注意：无子命令时 -v 会打印版本提示，不是直接显示
```

### 查看详细日志

```bash
# -v: 工具调用与计时
tuan dev -v "你的任务"

# -vv: 系统提示与完整请求
tuan dev -vv "你的任务"

# -vvv: 原始 API 与完整 token
tuan dev -vvv "你的任务"
```

### 查看所有注册的命令

```python
# 在 Python 中查看
from tuan_cli.cli.parser import _get_all_registered_commands
print(_get_all_registered_commands())
```

---

## 七、常见问题（FAQ）

### Q1: 如何在 CI/CD 中使用？

```bash
# 使用 --yolo 自动批准，--bare CI 纯净模式
tuan --yolo --bare "你的任务"

# 或使用 --print 输出到 stdout
tuan --print "你的任务" > output.txt
```

### Q2: 如何指定工作区？

```bash
tuan --workspace /path/to/project "你的任务"
```

### Q3: 如何限制最大花费？

```bash
tuan --max-cost 0.1 "你的任务"  # 限制单次会话最大花费 0.1 美元
```

### Q4: 如何限制交互轮数？

```bash
tuan --max-turns 10 "你的任务"  # 限制最多 10 轮交互
```

### Q5: 如何使用 JSON Schema 输出？

```bash
# 定义 JSON Schema
tuan --json-schema '{"type":"object","properties":{"answer":{"type":"string"}}}' "你的任务"

# 严格模式（仅合法 JSON，无多余文字）
tuan --json-schema '{"type":"object","properties":{"answer":{"type":"string"}}}' --json-schema-strict "你的任务"

# 自动修复重试
tuan --json-schema '{"type":"object","properties":{"answer":{"type":"string"}}}' --json-schema-retries 5 "你的任务"
```

### Q6: 如何自定义工具白名单？

```bash
tuan --allowed-tools "Bash(npm test),Read,Write" "你的任务"
```

### Q7: 如何查看所有子命令？

```bash
tuan help commands
```

### Q8: 如何运行教程？

```bash
# 列出可用教程
tuan tutorial list

# 运行某个教程
tuan tutorial run safety
```

### Q9: 如何更新到最新版本？

```bash
tuan upgrade
```

---

## 八、进阶技巧

### 技巧 1：使用 Profile 切换配置

```bash
# 使用指定 profile
tuan --profile production "你的任务"

# profiles 目录: ~/.tuan/profiles/
```

### 技巧 2：使用 Patch 临时覆盖配置

```bash
tuan --patch patch.toml "你的任务"
```

### 技巧 3：使用 Resume 续会话

```bash
# 续最近一个会话
tuan --resume

# 续指定会话
tuan --resume 1

# 续指定会话并指定任务
tuan --resume 1 "继续完成这个任务"
```

### 技巧 4：使用 Undo 回滚

```bash
# 查看影响半径
tuan undo --impact

# 回滚到第 3 步
tuan undo 3

# 回滚所有
tuan undo all
```

### 技巧 5：使用 Project 层隔离

```bash
# 初始化项目结构
tuan project init

# 查看项目信息
tuan project info
```

---

## 九、安全最佳实践

### 1. 默认使用标准模式

```bash
tuan  # 或 tuan --mode standard
```

### 2. 在 CI/CD 中使用 Yolo 模式

```bash
tuan --yolo --bare "你的任务"
```

### 3. 在代码审查中使用 Plan 模式

```bash
tuan --plan "审查这段代码"
```

### 4. 使用白名单管理信任的命令

```bash
# 添加到白名单
tuan safe allow "npm install"

# 查看白名单
tuan safe list
```

### 5. 定期运行安全基准

基准脚本按仓库根定位: 源码/`pip install -e` 环境自动认, 普通 pip 安装请设
环境变量 `TUAN_REPO_ROOT=<仓库根>` (install.ps1 与 tuan.bat 已自动设好)。

```bash
# 快速模式（2000 条样本，约 30 秒）
tuan safe bench --quick

# 全量模式（10000 条样本）
tuan safe bench

# 检查数字回归
tuan safe bench --check
```

**独立验证新口径 (v0.3.1)**: `bench/indep_verify.py` 的期望已按新口径标注 ——
相对路径递归强删 (`rm -rf ./dist`) 降为「可确认级」综合红线, 仍拦截但不再算
误杀; 灾难目标 (`rm -rf /` `~` `*`) 保持硬红线。第三方跑一遍即 29/29。

### 6. 定期更新安全策略

```bash
tuan safe update
```

---

## 十、获取帮助

### 在线资源

- **GitHub 仓库:** https://github.com/kino-koki/Tuan-CLI
- **问题反馈:** https://github.com/kino-koki/Tuan-CLI/issues
- **变更日志:** https://github.com/kino-koki/Tuan-CLI/blob/main/CHANGELOG.md

### 本地帮助

```bash
# 查看所有子命令
tuan help commands

# 查看特定子命令帮助
tuan help dev
tuan help safe
tuan help session

# 查看 doctor 诊断报告
tuan doctor
```

---

## 附录：快速命令参考

### 常用命令组合

```bash
# 日常开发（标准模式）
tuan "你的任务"

# CI/CD（自动批准）
tuan --yolo --bare "你的任务"

# 代码审查（只读）
tuan --plan "审查代码"

# 安全敏感操作（进程隔离）
tuan --isolation "运行测试"

# 后台运行
tuan agent "定时任务"

# 查看会话
tuan session list
tuan session resume 1

# 配置模型
tuan models switch deepseek deepseek-chat

# 查看安全状态
tuan safe status
```

### 参数速查

| 参数 | 说明 | 示例 |
|---|---|---|
| `--mode` | 运行模式 | `--mode yolo` |
| `--yolo` | 等同于 `--mode yolo` | `tuan --yolo "任务"` |
| `--plan` | 等同于 `--mode plan` | `tuan --plan "任务"` |
| `--isolation` | 进程级隔离 | `tuan --isolation "任务"` |
| `--print` | 非交互输出到 stdout | `tuan --print "任务"` |
| `--bare` | CI 纯净模式 | `tuan --bare "任务"` |
| `--workspace` | 指定工作区 | `tuan --workspace /path/to/project "任务"` |
| `--max-cost` | 最大花费限制（USD） | `tuan --max-cost 0.1 "任务"` |
| `--max-turns` | 限制交互轮数 | `tuan --max-turns 10 "任务"` |
| `--allowed-tools` | 工具白名单 | `tuan --allowed-tools "Read,Write" "任务"` |
| `--json-schema` | 结构化输出 | `tuan --json-schema '{"type":"object"}' "任务"` |
| `--json-schema-strict` | 严格 JSON 模式 | `tuan --json-schema '{"type":"object"}' --json-schema-strict "任务"` |
| `--json-schema-retries` | JSON 校验重试次数 | `tuan --json-schema '{"type":"object"}' --json-schema-retries 5 "任务"` |
| `--profile` | 使用指定 profile | `tuan --profile production "任务"` |
| `--patch` | 临时配置覆盖 | `tuan --patch patch.toml "任务"` |
| `--verbose` | 详细日志级别 | `tuan --v "任务"` |
| `--resume` | 续会话 | `tuan --resume 1` |

---

**最后更新:** 2026-08-26
**版本:** 0.3.0
**维护者:** tuan_cli team
