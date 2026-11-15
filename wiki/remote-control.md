# 远程控制与通知

> 本条目对应 `tuan_cli/core/remote_control.py`、`tuan_cli/core/security_alert.py`、`tuan_cli/vision/`。

## 是什么

对标 Claude Code 2.1.239 Remote Control：

- **QR 码配对**：手机扫码后可远程控制终端会话。
- **跨设备推送**：任务完成/失败/预算告警推送（`send_notification` 回调机制）。
- **告警**（`security_alert.py`）：SecurityAlerter + AlertRecord，桌面通知 + Notification hook 派发（按 owner 分桶）。
- **视觉**（`vision/`，3 文件/235 行）：截图/图像能力。

## 为什么

让青小团**可被手机远程控制**、关键事件跨设备通知，是"生产可用"的体验层。

## 关键文件

| 文件 | 职责 |
|---|---|
| `core/remote_control.py` | QR 配对 + 跨设备推送 |
| `core/security_alert.py` | 安全告警 + 通知 |
| `vision/` | 视觉能力 |

## 卖点

- Notification hook 按 **owner 分桶**派发（并发会话互不覆盖，B3 续轮 VII 已修）。
- 后台线程显式携带 owner（contextvar 不跨线程，O4 已修）。
- 告警 hook 派发在调用线程捕获 owner 烘进记录。

## 局限

- 远程控制依赖外部推送对象（配对状态持久 ~/.tuan）。
- 视觉能力较薄（3 文件/235 行）。
