# 会话与快照

> 本条目对应 `tuan_cli/session/`。

## 是什么

青小团的**会话生命周期管理**：

- 会话创建/恢复/关闭。
- 会话快照（断点）。
- `headless_resume`：headless 会话断点恢复。
- 会话 owner（contextvar，线程安全）。

## 为什么

让青小团能**跨会话恢复**（长任务中途断电 → 恢复继续），且并发会话互不干扰（owner 分桶）。

## 关键文件

| 文件 | 职责 |
|---|---|
| `session/` | 会话生命周期 |
| `core/remote_control.py` | 会话 owner 分桶通知 |

## 卖点

- 会话断点恢复（headless_resume）。
- 会话 owner 分桶（B3 续轮 VII 已修，266 测试绿）。

## 局限

- 会话恢复依赖外部进程存活（非系统级 daemon）。
