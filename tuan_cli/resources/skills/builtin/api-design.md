---
name: API 设计
description: RESTful API 设计模式：资源命名/状态码/错误处理/版本控制/认证授权
tags: [api-design, rest, http, endpoint, routing]
priority: 7
updated_at: 0
use_count: 0
---

# API 设计

好的 API 像好的代码：自解释、一致、可预测。

## 资源命名

```
✅ 正确:
GET    /api/v1/users          # 列表
GET    /api/v1/users/123      # 单个
POST   /api/v1/users          # 创建
PUT    /api/v1/users/123      # 全量更新
PATCH  /api/v1/users/123      # 部分更新
DELETE /api/v1/users/123      # 删除

❌ 错误:
GET /api/v1/getUsers          # 动词不应该是 URL 的一部分
POST /api/v1/user/create      # 同上
GET /api/v1/user/delete/123   # DELETE 应该用 HTTP 方法
```

## 状态码

| 场景 | 状态码 | 说明 |
|---|---|---|
| 成功创建 | 201 Created | POST 成功 |
| 成功无内容 | 204 No Content | DELETE 成功 |
| 客户端错误 | 400 Bad Request | 参数错误 |
| 未认证 | 401 Unauthorized | 缺少/无效 token |
| 无权限 | 403 Forbidden | 有 token 但权限不够 |
| 不存在 | 404 Not Found | 资源不存在 |
| 冲突 | 409 Conflict | 重复创建 |
| 服务端错误 | 500 Internal Server Error | 未预期的错误 |
| 限流 | 429 Too Many Requests | 速率限制 |

## 错误响应格式

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid email format",
    "details": [
      {
        "field": "email",
        "issue": "must be a valid email address",
        "value": "not-an-email"
      }
    ]
  }
}
```

## 分页

```json
// 请求
GET /api/v1/users?page=2&per_page=20

// 响应
{
  "data": [...],
  "pagination": {
    "page": 2,
    "per_page": 20,
    "total": 150,
    "total_pages": 8
  }
}
```

## 认证

```
# Bearer Token (推荐)
Authorization: Bearer <token>

# API Key (简单场景)
X-API-Key: <key>

# OAuth2 (第三方集成)
Authorization: OAuth <access_token>
```

## 版本控制

```
# URL 路径 (最直观)
/api/v1/users
/api/v2/users

# 请求头 (更 RESTful)
Accept: application/vnd.myapi.v2+json

# 查询参数 (最简单)
/api/users?version=2
```

## 幂等性

| 方法 | 幂等 | 说明 |
|---|---|---|
| GET | ✅ | 多次请求结果相同 |
| PUT | ✅ | 全量替换 |
| DELETE | ✅ | 删除多次结果相同 |
| POST | ❌ | 可能创建多个 |
| PATCH | ❌ | 取决于实现 |

POST 幂等化：客户端生成 `Idempotency-Key`，服务端去重。

## 速率限制

```
# 响应头
X-RateLimit-Limit: 100        # 窗口内最大请求数
X-RateLimit-Remaining: 67     # 剩余请求数
X-RateLimit-Reset: 1625000000 # 窗口重置时间 (Unix 时间戳)
```

## 安全

- 所有 API 强制 HTTPS
- 敏感操作 (删除/支付) 要求二次认证
- CORS 白名单，不设 `Access-Control-Allow-Origin: *`
- 请求体大小限制 (防 DoS)
- 输入验证 + 参数化查询
