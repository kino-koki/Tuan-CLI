---
name: tuan-api
description: >
  API 设计与实现技能。覆盖 REST、GraphQL、gRPC、WebSocket、Server-Sent Events、
  OpenAPI/Swagger、API 网关、限流、认证授权、版本管理、向后兼容。当用户要求
  设计 API、API、REST、GraphQL、gRPC、接口设计、API 实现、API 文档、
  认证授权、API 网关、限流、API 版本时使用。
activation: proactive
priority: 88
provides:
  - api-design
  - rest-api
  - graphql
  - grpc
suggests:
  - code-architect
  - tuan-docs
  - tuan-security
triggers:
  - API
  - api
  - REST
  - RESTful
  - GraphQL
  - gRPC
  - WebSocket
  - 接口设计
  - API 实现
  - API 文档
  - 认证授权
  - API 网关
  - 限流
  - API 版本
  - OpenAPI
  - Swagger
  - endpoint
  - HTTP
  - webhook
license: MIT
metadata:
  version: "1.0.0"
---

# TUAN API — API 设计与实现

## 协议选择矩阵

| 场景 | 推荐协议 | 理由 |
|------|----------|------|
| 公共 API / 跨语言 | REST | 简单、生态丰富、调试方便 |
| 强类型契约 / 微服务 | gRPC | 高性能、IDL 契约、双向流 |
| 复杂查询 / 聚合 | GraphQL | 灵活查询、避免过度获取 |
| 实时推送 / 通知 | WebSocket / SSE | 双向通信、低延迟 |
| 事件驱动 / 集成 | Webhook | 异步、松耦合 |

## REST 设计原则

### 资源命名

```
正确:
GET    /api/v1/users           # 列表
GET    /api/v1/users/{id}      # 单个
POST   /api/v1/users           # 创建
PUT    /api/v1/users/{id}      # 全量更新
PATCH  /api/v1/users/{id}      # 部分更新
DELETE /api/v1/users/{id}      # 删除

嵌套资源 (适度):
GET    /api/v1/users/{id}/orders   # 用户的订单
GET    /api/v1/orders/{id}         # 独立访问订单

错误:
GET    /api/v1/getUsers          # 动词命名
GET    /api/v1/user              # 单数 (除非是单例)
```

### 状态码

| 状态码 | 用途 | 示例 |
|--------|------|------|
| 200 | 成功 | GET/PUT/PATCH 成功 |
| 201 | 创建成功 | POST 返回资源 |
| 204 | 成功无响应体 | DELETE 成功 |
| 400 | 请求格式错误 | 缺少必填字段 |
| 401 | 未认证 | 缺少 token |
| 403 | 无权限 | 权限不足 |
| 404 | 不存在 | 资源 ID 不存在 |
| 409 | 冲突 | 重复创建 |
| 422 | 语义错误 | 输入合法但业务不允许 |
| 429 | 限流 | 请求过于频繁 |
| 500 | 服务器错误 | 内部错误 |

### 错误响应格式

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "请求体格式错误",
    "details": [
      {"field": "email", "message": "邮箱格式不正确"}
    ],
    "request_id": "req-abc123"
  }
}
```

## GraphQL 模式

```graphql
# Schema
type User {
  id: ID!
  name: String!
  email: String!
  orders: [Order!]! @connection
}

type Query {
  user(id: ID!): User
  users(limit: Int = 20, offset: Int = 0): [User!]!
}

# 查询
query GetUser {
  user(id: "123") {
    id
    name
    orders { id total status }
  }
}
```

## gRPC 模式

```protobuf
syntax = "proto3";
package tuan.v1;

service TaskService {
  rpc CreateTask(CreateTaskRequest) returns (Task);
  rpc GetTask(GetTaskRequest) returns (Task);
  rpc ListTasks(ListTasksRequest) returns (stream Task);  // 服务端流
  rpc WatchTasks(WatchRequest) returns (stream TaskEvent); // 服务端流
}

message CreateTaskRequest {
  string title = 1;
  string priority = 2;
}

message Task {
  string id = 1;
  string title = 2;
  string status = 3;
  google.protobuf.Timestamp created_at = 4;
}
```

## 版本管理

```
URL 路径:  /api/v1/  /api/v2/     # 最常用，清晰
Header:    Accept: application/vnd.tuan.v2+json   # 更优雅但复杂
媒体类型:  Content-Type: application/vnd.tuan.v1+json
```

## 认证与授权

```
认证 (你是谁):
  Bearer Token / JWT          # API Key / OAuth2 / Session Cookie

授权 (你能做什么):
  RBAC (角色)                  # admin / editor / viewer
  ABAC (属性)                  # 基于用户属性、资源属性动态判断
  Scope / Permission           # OAuth2 scope: read:tasks write:tasks
```

## 限流策略

| 策略 | 实现 | 适用 |
|------|------|------|
| 固定窗口 | 每分钟 100 请求 | 简单 API |
| 滑动窗口 | 过去 60 秒 100 请求 | 更平滑 |
| 令牌桶 | 速率 10/s，桶大小 20 | 突发容忍 |
| 漏桶 | 恒定速率 10/s | 严格平滑 |

```http
# 响应头
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1704067200
Retry-After: 30
```

## 检查清单

- [ ] 资源命名使用名词复数
- [ ] 状态码语义正确
- [ ] 错误响应格式统一
- [ ] 分页 (limit/offset 或 cursor)
- [ ] 排序和过滤支持
- [ ] 幂等性 (POST/PUT/DELETE)
- [ ] 认证和授权
- [ ] 限流策略
- [ ] API 版本管理
- [ ] OpenAPI/Swagger 文档
- [ ] 向后兼容策略
```
