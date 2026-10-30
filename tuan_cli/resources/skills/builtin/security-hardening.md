---
name: 安全加固
description: 提交/发布前的安全加固清单，覆盖注入、认证、依赖、密钥、传输与日志等风险面
activation: auto
triggers: 安全, security, 加固, 漏洞, CVE, 渗透
provides: tuan-security
suggests: code-review-checklist, yolo-safety-checklist
priority: 82
updated_at: 0
use_count: 0
---
# 安全加固

安全不是「加个校验」，是「每个输入边界都默认拒绝」。按面扫一遍，别只盯注入。

## 注入面
- SQL：一律参数化，禁止字符串拼接。
- 命令执行：优先用参数列表（subprocess list / execvp），禁止 shell=True 拼接。
- HTML/模板：默认转义；白名单标签才允许。
- 路径：用路径解析并校验在允许根内，防 ../ 穿越。

## 认证与授权
- 密码用慢哈希（argon2/bcrypt），禁止 MD5/SHA1。
- 会话/令牌：设置过期、轮换、绑定设备/来源。
- 每个敏感操作都做授权检查，不能只做「是否登录」判断。

## 依赖与供应链
- 锁定依赖版本（lockfile），CI 里跑依赖审计（pip-audit / npm audit）。
- 不引入维护停滞或已知漏洞的包；新依赖先查 CVE。

## 密钥与机密
- 密钥只从环境变量/密钥管理服务读，不进代码、不进日志、不进 VCS。
- 日志脱敏：不打印 token、密码、身份证号、手机号。

## 传输与存储
- 传输层强制 TLS；禁止降级到明文。
- 敏感数据静态加密；备份同样加密并限制访问。

## 收尾
- 默认最小权限：服务账号只给所需的最小 scope。
- 错误信息不泄漏内部细节（堆栈/路径/SQL）给用户。
