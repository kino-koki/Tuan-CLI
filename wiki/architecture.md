# 架构与内核 Kernel

> 本条目对应 `tuan_cli/core/kernel.py`、`tuan_cli/arch/`。

## 是什么

青小团的**插件容器式分层 Agent 宿主**底座，融合 DeepSeek Harness / Cordis 理念：

- **Kernel（插件容器）**：注册/装配/启动插件，管理生命周期。
- **ServiceContainer（服务注册表）**：懒工厂、钩子、类型化注入。
- **MiddlewareEventBus（事件总线）**：中间件管线，**append-only**（`kernel.py:591-596`），带 `_MAX_EVENTS=2000` 上限 + 溢出回调（`kernel.py:34-35,597-610`）。

## 为什么

提供"插件可插拔、服务可替换、事件可观测"的骨架，让 58 Provider、三主循环、多 Agent 派发等能力以统一模式挂载，而非散落的全局单例。

## 关键文件

| 文件 | 职责 |
|---|---|
| `core/kernel.py` | Kernel + ServiceContainer + MiddlewareEventBus |
| `arch/context.py` | 执行上下文（会话、owner、事务） |
| `arch/execution.py` | 执行模型 |
| `arch/platform.py` | 平台抽象（路径、OS 差异） |
| `arch/observability.py` | 轨迹/归因存储 |
| `arch/security.py` | 安全策略层 |
| `arch/orchestration.py` | 编排抽象 |
| `arch/plugin.py` | 插件基类/接口 |

## 卖点

- **纯 Python**，运行时仅 2 个第三方依赖（rich、prompt_toolkit）。
- 插件容器与事件总线是**零依赖内部实现**，非第三方框架。
- append-only 事件总线可观测（上限有意设计，防内存膨胀）。

## 局限

- 事件总线非无限 append-only（2000 条上限 + 溢出回调）。
- `ServiceContainer` 懒工厂依赖注入无编译期检查（运行时才报错）。
