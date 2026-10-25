---
name: tuan-docs
description: >
  技术文档写作技能。覆盖 README、API 文档、架构文档、用户指南、变更日志、
  设计文档、ADR（架构决策记录）、贡献指南、部署文档。当用户要求写文档、
  文档、README、API 文档、设计文档、架构文档、用户指南、技术文档、文档、
  文档写作、写文档、文档审查时使用。
activation: proactive
priority: 80
provides:
  - documentation
  - technical-writing
  - docs
suggests:
  - code-architect
triggers:
  - 文档
  - 文档
  - README
  - API 文档
  - 设计文档
  - 架构文档
  - 用户指南
  - 技术文档
  - 文档
  - 文档写作
  - 写文档
  - 文档审查
  - docs
  - documentation
  - readme
  - api-docs
  - design-doc
  - adr
  - changelog
  - contributing
license: MIT
metadata:
  version: "1.0.0"
---

# TUAN Docs — 技术文档写作

## 文档类型矩阵

| 类型 | 受众 | 核心问题 | 模板 |
|------|------|----------|------|
| README | 新用户 | 这是什么？怎么用？ | 概述→安装→快速开始→配置→示例 |
| API 文档 | 开发者 | 怎么调？ | 端点→参数→响应→错误码→示例 |
| 架构文档 | 工程师 | 为什么这样设计？ | 背景→目标→方案→权衡→决策记录 |
| ADR | 决策者 | 为什么选这个？ | 状态→背景→决策→后果→备选方案 |
| 用户指南 | 终端用户 | 怎么完成任务？ | 场景→步骤→截图→排错 |
| 部署文档 | 运维 | 怎么上线？ | 环境→配置→部署→验证→回滚 |
| 变更日志 | 所有人 | 改了什么？ | 版本→新增→变更→修复→破坏性变更 |

## 写作原则

1. **读者优先**：先告诉读者"这是什么、谁该读、读完能做什么"
2. **代码即文档**：能运行的示例 > 描述性的文字
3. **错误优先**：先写"常见错误和解决方案"，再写"理想流程"
4. **版本同步**：文档与代码同仓库、同 PR、同 review
5. **简洁**：一句话能说清的不用两句

## README 模板

```markdown
# 项目名

一句话描述项目做什么。

## 快速开始

```bash
# 安装
pip install myproject

# 运行
python -m myproject serve
```

## 配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| PORT | 8080 | 监听端口 |
| DB_URL | sqlite:///data.db | 数据库连接 |

## 示例

```python
from myproject import Client

client = Client()
result = client.do_something("hello")
print(result)
```

## 贡献

请阅读 CONTRIBUTING.md。

## 许可证

MIT
```

## API 文档模板

```markdown
## POST /api/v1/tasks

创建任务。

### 请求

```json
{
  "title": "新任务",
  "priority": "high",
  "assignee": "user-123"
}
```

### 响应 (201)

```json
{
  "id": "task-456",
  "title": "新任务",
  "priority": "high",
  "created_at": "2026-01-01T00:00:00Z"
}
```

### 错误码

| 状态码 | 错误码 | 说明 |
|--------|--------|------|
| 400 | INVALID_INPUT | 请求体格式错误 |
| 401 | UNAUTHORIZED | 未认证 |
| 422 | CONFLICT | 任务已存在 |
```

## ADR 模板

```markdown
# ADR-001: 选择 PostgreSQL 作为主数据库

## 状态
已接受 (2026-01-01)

## 背景
项目需要 ACID 事务支持和全文搜索。

## 决策
使用 PostgreSQL 16，通过 SQLAlchemy ORM 访问。

## 后果
- 正面：成熟的生态、ACID 事务、全文搜索
- 负面：运维复杂度增加、需要监控连接池
- 备选方案：MySQL（兼容性更好但全文搜索较弱）、MongoDB（不适合事务场景）
```

## 检查清单

- [ ] 标题和一句话描述清晰
- [ ] 快速开始可在 5 分钟内跑通
- [ ] 所有配置项有默认值和说明
- [ ] 代码示例可直接运行
- [ ] 错误码和解决方案完整
- [ ] 版本变更记录
- [ ] 无 emoji
- [ ] 链接可访问
```
