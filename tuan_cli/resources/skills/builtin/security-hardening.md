---
name: 安全加固
description: 安全编码最佳实践：输入验证/SQL参数化/密钥管理/权限控制/审计日志
tags: [security, hardening, injection, authentication, encryption]
priority: 9
updated_at: 0
use_count: 0
---

# 安全加固

安全不是功能，是属性。每一行代码都可能是攻击面。

## 核心原则

1. **永远不信任用户输入** — 所有外部数据都是脏的
2. **最小权限** — 只给必要的权限，不多给
3. **纵深防御** — 多层防护，不依赖单一安全机制
4. **fail-closed** — 异常时拒绝，而不是放行

## 输入验证

```python
# ✅ 白名单验证
def validate_username(name: str) -> str:
    if not re.match(r'^[a-zA-Z0-9_]{3,20}$', name):
        raise ValueError(f"Invalid username: {name}")
    return name

# ❌ 黑名单过滤 (总会漏掉新型攻击)
def validate_username_bad(name: str) -> str:
    if '<script>' in name:  # 只防 XSS，不防 SQL 注入
        raise ValueError("Invalid")
    return name  # 其他注入呢？
```

## SQL 注入防护

```python
# ✅ 参数化查询
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))

# ❌ 字符串拼接
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")  # SQL 注入！

# ❌ ORM 的 raw query 也要参数化
User.objects.raw(f"SELECT * FROM users WHERE id = {user_id}")  # 同样危险
```

## 命令注入防护

```python
import subprocess

# ✅ 参数列表 (不经过 shell)
subprocess.run(["git", "status"], check=True)

# ❌ 字符串拼接 (shell 注入)
subprocess.run(f"git {user_input}", shell=True)  # user_input 可以是 "; rm -rf /"
```

## 密钥管理

```python
import os

# ✅ 从环境变量读取
api_key = os.environ.get("API_KEY")
if not api_key:
    raise RuntimeError("API_KEY not set")

# ❌ 硬编码
api_key = "sk-1234567890abcdef"  # 永远不要这样做！

# ❌ 写入日志
logger.info(f"Using API key: {api_key}")  # 密钥泄露！
```

## XSS 防护

```python
# ✅ 转义输出
from markupsafe import escape
html = f"<p>{escape(user_input)}</p>"

# ❌ 直接插入
html = f"<p>{user_input}</p>  # user_input 可以是 <script>alert('xss')</script>"
```

## 路径穿越防护

```python
from pathlib import Path

# ✅ 规范化 + 检查前缀
def safe_path(base: str, user_path: str) -> Path:
    resolved = (Path(base) / user_path).resolve()
    if not str(resolved).startswith(str(Path(base).resolve())):
        raise ValueError("Path traversal detected")
    return resolved

# ❌ 直接拼接
dangerous = Path(base) / user_path  # user_path 可以是 "../../etc/passwd"
```

## 权限控制

```python
# ✅ RBAC: 基于角色的访问控制
def check_permission(user: User, resource: Resource, action: str) -> bool:
    role = user.role
    if role == "admin":
        return True
    if role == "editor" and action in ("read", "write"):
        return resource.owner_id == user.id
    if role == "viewer" and action == "read":
        return True
    return False  # 默认拒绝

# ❌ 硬编码权限
if user.name == "admin":  # 用户名可以被伪造！
    allow_all()
```

## 审计日志

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

## 依赖安全

```bash
# 扫描已知漏洞
pip audit
npm audit

# 锁定依赖版本
pip freeze > requirements.txt
# 或用 poetry/pdm 管理锁文件
```

## 代码审查安全清单

- [ ] 所有用户输入都经过验证
- [ ] SQL 查询使用参数化
- [ ] Shell 命令使用参数列表 (不拼接字符串)
- [ ] 密钥从环境变量读取，不硬编码
- [ ] 敏感数据不写入日志
- [ ] 文件路径经过规范化检查
- [ ] 异常处理不泄露内部信息
- [ ] 依赖已扫描已知漏洞
