# 硬化与评审（/security-review）

> 本条目对应 `tuan_cli/cli/cmd_harden.py`、`tuan_cli/cli/safe/threat_scan.py`、`tuan_cli/harden/`。

## 是什么

青小团的**主动安全硬化**：

- `cli/cmd_harden.py`：`/security-review`（categories="security" 真接线，诊断 2026-11-15 核实）、`/review --security`。
- `cli/safe/threat_scan.py`：威胁扫描（`threat_scan` 命令）。
- `harden/`：硬化规则。
- `cli/safe/whitelist.py`：白名单。
- `cli/safe/learning.py`：学习闭环。

## 为什么

"safety-first"不能只靠被动拦截，还要**主动扫描威胁、评审安全、建立白名单**。硬化为四道闸门补上"持续改进"维度。

## 关键文件

| 文件 | 职责 |
|---|---|
| `cli/cmd_harden.py` | /security-review |
| `cli/safe/threat_scan.py` | 威胁扫描 |
| `cli/safe/whitelist.py` | 白名单 |
| `cli/safe/learning.py` | 学习 |
| `harden/` | 硬化规则 |

## 卖点

- `/security-review` 真接线（categories="security" 此前假接线已修）。
- 威胁扫描 + 白名单 + 学习齐备。
- `safe bench --quick` 安全不降级回归。

## 局限

- 威胁扫描规则为内部代码，无外部规则 DSL。
