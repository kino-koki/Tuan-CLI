---
name: tuan-security
description: >
  安全审计与加固技能。覆盖 OWASP Top 10、SAST/DAST、依赖扫描、认证授权、
  加密、密钥管理、安全头、CORS、CSRF、XSS、SQL 注入、SSRF、供应链安全、
  安全编码模式、渗透测试方法论、安全审计清单。当用户要求安全、security、
  安全审计、OWASP、注入、XSS、CSRF、加密、认证、授权、漏洞扫描、
  安全加固、安全编码、密钥管理、供应链安全时使用。
activation: proactive
priority: 92
provides:
  - security
  - owasp
  - sast
  - audit
suggests:
  - code-architect
  - tuan-api
triggers:
  - 安全
  - security
  - 安全审计
  - OWASP
  - 注入
  - XSS
  - CSRF
  - SQL 注入
  - 加密
  - 认证
  - 授权
  - 漏洞扫描
  - 安全加固
  - 安全编码
  - 密钥管理
  - 供应链安全
  - SAST
  - DAST
  - penetration test
  - vulnerability
license: MIT
metadata:
  version: "1.0.0"
---

# TUAN Security — 安全审计与加固

## OWASP Top 10 防护矩阵

| 编号 | 漏洞 | 风险 | 防护核心 |
|------|------|------|----------|
| A01 | 访问控制失效 | 高 | 服务端验证权限，不信任客户端 |
| A02 | 加密机制失效 | 高 | TLS 1.3、密钥轮换、不在代码中存密钥 |
| A03 | 注入 | 严重 | 参数化查询、输入白名单、ORM |
| A04 | 不安全设计 | 高 | 威胁建模、最小权限、防御性设计 |
| A05 | 安全配置错误 | 高 | 安全默认值、禁用调试、移除默认凭据 |
| A06 | 易受攻击和过时的组件 | 高 | 依赖扫描、自动更新、SBOM |
| A07 | 身份识别和认证失效 | 高 | MFA、密码策略、会话管理 |
| A08 | 软件和数据完整性失效 | 中 | CI/CD 安全、签名验证、完整性校验 |
| A09 | 安全日志和监控失效 | 中 | 审计日志、异常检测、告警 |
| A10 | SSRF | 中 | URL 白名单、内网隔离、DNS 过滤 |

## 认证与授权

### 认证模式

| 模式 | 适用场景 | 注意事项 |
|------|----------|----------|
| JWT (Bearer) | API、SPA | 短期有效期、刷新令牌、密钥轮换 |
| OAuth2 + PKCE | 第三方登录 | 授权码流程、PKCE 防拦截 |
| Session Cookie | 传统 Web | HttpOnly、Secure、SameSite=Strict |
| API Key | 服务间通信 | 限流、作用域限制、定期轮换 |
| mTLS | 微服务 | 证书轮换、证书固定 |

### 授权模式

```python
# RBAC (角色基)
class Permission:
    def __init__(self, user, resource, action):
        if action == "write":
            assert user.role in ("admin", "editor")
        if action == "read":
            assert user.role in ("admin", "editor", "viewer")
        # 资源级授权
        if resource.owner != user.id and user.role != "admin":
            raise PermissionError("无权访问此资源")
```

## 加密与密钥管理

```
# 密钥存储 (优先级)
1. 专用密钥管理器 (HashiCorp Vault, AWS KMS, GCP Secret Manager)
2. 云厂商密钥服务 (Azure Key Vault)
3. 环境变量 (仅开发环境)
4. 文件 (权限 600, 仅本地开发)

# 禁止
- 代码中硬编码密钥
- .git 提交密钥文件
- 日志中打印密钥
- URL 参数传递密钥
```

## 安全编码模式

### SQL 注入防护

```python
# 正确: 参数化查询
cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))

# 正确: ORM
User.query.filter_by(id=user_id).first()

# 错误: 字符串拼接
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")  # 注入!
```

### XSS 防护

```python
# 服务端渲染: 自动转义 (Django/Jinja2 默认)
# 客户端渲染: 使用 textContent 而非 innerHTML
# CSP 头: Content-Security-Policy: default-src 'self'
```

### CSRF 防护

```python
# 传统 Web: CSRF Token
<form>
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  <button type="submit">提交</button>
</form>

# API: SameSite=Strict Cookie 或自定义 Header
Authorization: Bearer <token>  # 浏览器不会自动附加自定义 Header
```

## 安全头配置

```http
# 核心安全头
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Content-Security-Policy: default-src 'self'; script-src 'self'
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

## 安全审计清单

### 代码审计
- [ ] 无硬编码密钥/密码
- [ ] 参数化查询，无 SQL 拼接
- [ ] 输入验证 (类型、长度、范围)
- [ ] 输出转义 (HTML、JSON、URL)
- [ ] 文件上传限制 (类型、大小)
- [ ] 认证检查在每个需要权限的端点
- [ ] 授权检查在资源级别
- [ ] 错误信息不泄露内部细节
- [ ] 日志不记录敏感数据

### 配置审计
- [ ] HTTPS 强制 (HSTS)
- [ ] 安全头已配置
- [ ] CORS 配置正确 (非 *)
- [ ] 调试模式关闭
- [ ] 错误页面自定义 (非默认)
- [ ] 默认凭据已更改
- [ ] 不需要的端点已禁用

### 依赖审计
- [ ] 依赖扫描通过 (npm audit / pip-audit / cargo audit)
- [ ] 无已知 CVE
- [ ] 依赖版本固定 (lock file)
- [ ] SBOM 已生成

## 检查清单

- [ ] OWASP Top 10 全部防护
- [ ] 认证机制正确
- [ ] 授权机制正确 (资源级)
- [ ] 加密传输 (TLS 1.3)
- [ ] 密钥管理安全
- [ ] 安全头配置
- [ ] CORS 配置
- [ ] 依赖扫描通过
- [ ] 安全日志
- [ ] 错误处理不泄露信息
- [ ] 输入验证和输出转义
```

## 安全编码实践（实战代码示例）

> 以下内容源自原 `security-hardening` 技能，已合并至本技能。

### 核心原则

1. **永远不信任用户输入** — 所有外部数据都是脏的
2. **最小权限** — 只给必要的权限，不多给
3. **纵深防御** — 多层防护，不依赖单一安全机制
4. **fail-closed** — 异常时拒绝，而不是放行

### 输入验证

```python
# 推荐: 白名单验证
def validate_username(name: str) -> str:
    if not re.match(r'^[a-zA-Z0-9_]{3,20}$', name):
        raise ValueError(f"Invalid username: {name}")
    return name

# 反例: 黑名单过滤 (总会漏掉新型攻击)
def validate_username_bad(name: str) -> str:
    if '<script>' in name:  # 只防 XSS，不防 SQL 注入
        raise ValueError("Invalid")
    return name  # 其他注入呢？
```

### SQL 注入防护

```python
# 推荐: 参数化查询
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))

# 反例: 字符串拼接
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")  # SQL 注入！

# 反例: ORM 的 raw query 也要参数化
User.objects.raw(f"SELECT * FROM users WHERE id = {user_id}")  # 同样危险
```

### 命令注入防护

```python
import subprocess

# 推荐: 参数列表 (不经过 shell)
subprocess.run(["git", "status"], check=True)

# 反例: 字符串拼接 (shell 注入)
subprocess.run(f"git {user_input}", shell=True)  # user_input 可以是 "; rm -rf /"
```

### 密钥管理

```python
import os

# 推荐: 从环境变量读取
api_key = os.environ.get("API_KEY")
if not api_key:
    raise RuntimeError("API_KEY not set")

# 反例: 硬编码
api_key = "sk-1234567890abcdef"  # 永远不要这样做！

# 反例: 写入日志
logger.info(f"Using API key: {api_key}")  # 密钥泄露！
```

### XSS 防护

```python
# 推荐: 转义输出
from markupsafe import escape
html = f"<p>{escape(user_input)}</p>"

# 反例: 直接插入
html = f"<p>{user_input}</p>  # user_input 可以是 <script>alert('xss')</script>"
```

### 路径穿越防护

```python
from pathlib import Path

# 推荐: 规范化 + 检查前缀
def safe_path(base: str, user_path: str) -> Path:
    resolved = (Path(base) / user_path).resolve()
    if not str(resolved).startswith(str(Path(base).resolve())):
        raise ValueError("Path traversal detected")
    return resolved

# 反例: 直接拼接
dangerous = Path(base) / user_path  # user_path 可以是 "../../etc/passwd"
```

### 权限控制

```python
# 推荐: RBAC: 基于角色的访问控制
def check_permission(user: User, resource: Resource, action: str) -> bool:
    role = user.role
    if role == "admin":
        return True
    if role == "editor" and action in ("read", "write"):
        return resource.owner_id == user.id
    if role == "viewer" and action == "read":
        return True
    return False  # 默认拒绝

# 反例: 硬编码权限
if user.name == "admin":  # 用户名可以被伪造！
    allow_all()
```

### 审计日志

```python
import logging
import time

audit_log = logging.getLogger("audit")

def audit_action(user: str, action: str, resource: str, result: str):
    """记录所有安全相关操作。"""
    audit_log.info(
        "user=%s action=%s resource=%s result=%s ts=%.3f",
        user, action, resource, result, time.time(),
    )
    # 审计日志不应该被用户控制的内容污染 (防止日志注入)
```

### 依赖安全

```bash
# 扫描已知漏洞
pip audit
npm audit

# 锁定依赖版本
pip freeze > requirements.txt
# 或用 poetry/pdm 管理锁文件
```
