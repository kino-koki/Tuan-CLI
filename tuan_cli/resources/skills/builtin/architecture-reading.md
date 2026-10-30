---
name: 架构阅读
description: 快速理解陌生代码库/模块的架构脉络，定位核心抽象与数据流，避免一头扎进实现细节
activation: auto
triggers: 架构, 读代码, 理解代码, 代码库, codebase, 模块结构
provides: code-architect
suggests: codebase-navigation, safe-refactor
priority: 72
updated_at: 0
use_count: 0
---
# 架构阅读

读陌生代码库，先建地图，再进房间。别从入口逐行读——那样永远只见到走廊。

## 先看入口与清单
- README、docs/、CONTRIBUTING：作者想让你先看什么，往往就是主干。
- 构建/依赖清单（package.json / pyproject.toml / go.mod / Cargo.toml）：依赖图即架构骨架。

## 找核心抽象
- 先找「被最多人引用」的类型/接口/模块。用全局搜索数引用，引用越多越是核心。
- 关注接口与实现分离处：interface / trait / protocol / abstract base —— 那里是扩展点。
- 区分「框架代码」与「业务代码」：框架决定整体走向，业务塞在缝隙里。

## 沿数据流走一遍
- 选一条端到端主路径（如：请求进 → 结果出），跟着函数调用走一遍。
- 记录：谁创建数据、谁变换、谁持久化、谁返回给外部。画出最小数据流图。

## 识别分层与边界
- 分层（UI / 服务 / 领域 / 基础设施）是否清晰？跨层依赖是否有倒置？
- 模块边界靠什么通信：函数调用、消息、事件、RPC？边界越松散越好读。

## 产出
- 用一段话概括：这个系统是什么、解决什么问题、主干路径长什么样。
- 列出 3-5 个关键文件/模块及各自职责，供后续深入时直接定位。
