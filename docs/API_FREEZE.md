# API 冻结声明 (API Freeze)

> 生效版本: **v0.3.4** (2026-11-03)
> 策略: 语义化版本 (SemVer) + 冻结期治理

## 冻结范围

以下公共 API 面自 v0.3.4 起进入冻结期。**破坏性改动**（移除 / 改签名 /
改语义）需走 **deprecation window**：先在新版本标记弃用（`DeprecationWarning` +
CHANGELOG 声明），保留至少 **1 个小版本**（如 0.3.x → 0.4.x），方可移除。

### 1. 包级导出 (`tuan_cli/__init__.py`)
- `Kernel`, `Plugin`, `plugin`, `ServiceContainer`, `MiddlewareEventBus`
- `__version__`

### 2. 安全引擎判定函数 (`tuan_cli/ext/safety_redline.py`)
签名冻结，语义冻结（危险度分档 ALLOW / RED 可确认 / HARD 永不自动）：

| 函数 | 语义 |
| --- | --- |
| `is_hard_redline(cmd) -> bool` | 永不自动执行的灾难命令 |
| `is_redline(cmd) -> bool` | 需用户确认的高危命令 |
| `is_extreme(cmd) -> bool` | 极高危档 |
| `has_dangerous_recursive_rm(text) -> bool` | rm -rf 危险目标 |
| `has_recursive_rm(text) -> bool` | rm -rf 任意目标 |
| `has_force_push(text) -> bool` | git force push |
| `has_win_recursive_delete(text) -> bool` | Windows 递归删除 |
| `has_system_shutdown(text) -> bool` | 关机/重启 |
| `has_rsync_delete_target(text) -> bool` | rsync --delete 危险目标端 |
| `has_auth_overwrite(text) -> bool` | 认证文件覆盖 |
| `is_benign_dev_command(cmd) -> bool` | 良性开发命令（降噪） |

### 3. 自动决策系统 (`tuan_cli/core/auto_mode.py`)
- `AutoModeClassifier` 类与 `assess(tool_name, tool_args) -> RiskAssessment` 方法
- `RiskAssessment` 数据类 (`level` / `reason` / `tool_name` / `matched_pattern` /
  `auto_approve` / `needs_confirm` / `rule_source`)
- `RiskLevel` 枚举 (SAFE/LOW/MODERATE/HIGH/CRITICAL)、`AutoModeRule` 数据类
- `assess_tool_risk` / `is_auto_approvable` 模块级便捷函数
- `TOOL_BASELINE_RISK` 工具基线风险表、`YOLO_EQUIVALENT_MODES` / `is_mode_yolo_equivalent`
- 语义: **倒数第二道防线**，完全本地、极低占用（纯 Python，无外部模型依赖），
  仅对 RED 级可确认命令给出本地决策建议；硬红线永不自动执行。
- **不越级护栏**: 自动决策的 `auto_approve` 绝不能放行安全引擎判定的红线命令。
  `PermissionPolicy.decide()` 在 auto_approve 放行前用 `ext.safety_engine.is_redline`
  兜底 fail-closed（安全引擎不可用时降级为需确认）—— AutoModeClassifier 自带正则
  远弱于安全引擎，无此护栏会在 `_hardening_confirm` 之前越级放行
  （rsync --delete / killall -9 -1 / dd / chmod -R 000 / mkfs / fork bomb 实测可绕）。

### 4. 内核插件协议 (`tuan_cli/core/kernel.py`)
- `@plugin` 装饰器参数 (`name` / `version` / `provides` / `requires`)
- `Plugin` 基类 `activate` / `deactivate` 生命周期
- `ServiceContainer` 注册/解析语义（懒工厂、类型安全、依赖注入）

### 5. CLI 命令名与斜杠命令
- 主命令名 (`tuan` 及子命令树) 与 `/slash` 命令名为用户脚本依赖面，冻结。
- 新增命令允许；重命名/移除走 deprecation window。

## 非冻结区

- 内部模块（`safety_normalize` / `safety_patterns` 内部函数与模式表）：可自由演进，
  仅需保证上方判定函数的外部语义不变（新增拦截面允许，放宽需评估）。
- 模式库内容（`_CRITICAL_PATTERNS` 等）：**允许追加**（收紧安全），
  **移除需记录**（可能放宽安全）。
- UI / TUI / 桌面端内部结构：不在冻结范围。

## 模式库维护约定

- 新增模式请同步补 `tests/` 回归用例（参考 `tests/test_safety_redteam_round4.py`）。
- `label` 是用户本地黑名单减负 (`tuan safe reduce <label>`) 的匹配键，
  改动 label 会影响既有用户的减负声明，谨慎处理。
- 正则需考虑 ReDoS：避免嵌套 `[^\n]*` 等灾难回溯形态；超长输入由
  `_COMMAND_MAX_LEN` / `_MATCH_LINE_MAX` 护栏兜底。

## 依据

- 「所有命令完全不绕过」的 1.0 目标要求判定面稳定可依赖，冻结是前提。
- 分层安全栈：**自动决策 (本地) → 硬红线 (永不自动)** —— 前者是后者的减负层，
  不可越级放行硬红线，不可被外部状态绕过。
