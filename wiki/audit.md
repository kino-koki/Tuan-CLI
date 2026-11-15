# 可观测性与审计

> 本条目对应 `tuan_cli/audit/`（4 文件/779 行）、`tuan_cli/arch/observability.py`、`tuan_cli/cli/safe/`。

## 是什么

- **审计存储**（`audit/store.py`）：JSON 序列化（151 行）+ 原子写（416 行），记录安全决策/事件。
- **轨迹与归因**（`arch/observability.py`，24-191 行）：轨迹存储、归因。
- **安全 CLI**（`cli/safe/`）：audit_view、bench_report、learning、observe_trend、threat_scan、whitelist、_shared。

## 为什么

"可观测性已完整"是诊断结论之一：审计事件流可追溯（who/what/decision/timestamp），安全评审、威胁扫描、趋势观察齐备。

## 关键文件

| 文件 | 职责 |
|---|---|
| `audit/store.py` | 审计存储（原子写） |
| `audit/report.py` | 审计报告 |
| `arch/observability.py` | 轨迹/归因 |
| `cli/safe/threat_scan.py` | 威胁扫描 |
| `cli/safe/observe_trend.py` | 趋势观察 |

## 卖点

- 审计存储原子写（崩溃不半截）。
- 安全评审 /security-review 真接线（categories="security"）。
- 威胁扫描 + 白名单 + 学习闭环齐备。

## 局限

- 无 trace_id/correlation_id 传播、无结构化日志器、无耗时埋点（诊断 2026-11-15：observability 是轨迹存储，无 request_id 传播）。
