---
name: tuan-observability
description: >
  可观测性技能。覆盖结构化日志、指标 (Prometheus/OpenTelemetry)、分布式追踪
  (Jaeger/Tempo)、告警 (Alertmanager)、仪表盘 (Grafana)、SLO/SLI/SLA、
  健康检查、错误追踪 (Sentry)、日志聚合 (ELK/Loki)。当用户要求日志、
  日志、监控、metrics、指标、tracing、追踪、告警、alerting、dashboard、
  仪表盘、SLO、SLI、SLA、可观测性、observability、APM、错误追踪、
  OpenTelemetry、Prometheus、Grafana、ELK、Loki、Jaeger 时使用。
activation: proactive
priority: 82
provides:
  - observability
  - logging
  - metrics
  - tracing
  - alerting
suggests:
  - tuan-docker
  - tuan-ci-cd
  - tuan-security
triggers:
  - 日志
  - 日志
  - 监控
  - metrics
  - 指标
  - tracing
  - 追踪
  - 告警
  - alerting
  - dashboard
  - 仪表盘
  - SLO
  - SLI
  - SLA
  - 可观测性
  - observability
  - APM
  - 错误追踪
  - OpenTelemetry
  - Prometheus
  - Grafana
  - ELK
  - Loki
  - Jaeger
license: MIT
metadata:
  version: "1.0.0"
---

# TUAN Observability — 可观测性

## 三大支柱

| 支柱 | 回答的问题 | 工具 |
|------|-----------|------|
| 日志 (Logs) | 发生了什么？ | JSON 结构化日志、Loki、ELK |
| 指标 (Metrics) | 表现如何？ | Prometheus、OpenTelemetry |
| 追踪 (Traces) | 在哪里慢？ | OpenTelemetry、Jaeger、Tempo |

## 结构化日志

```python
import logging
import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
)

logger = structlog.get_logger()

# 好: 结构化日志 (可查询、可聚合)
logger.info("request.completed", method="GET", path="/users", status=200, latency_ms=45)

# 坏: 非结构化日志 (难查询)
logger.info(f"GET /users 200 45ms")
```

### 日志级别

| 级别 | 用途 | 示例 |
|------|------|------|
| TRACE | 详细调试 | 每个请求的 SQL 参数 |
| DEBUG | 开发调试 | 函数调用细节 |
| INFO | 正常事件 | 请求完成、部署完成 |
| WARN | 可恢复异常 | 重试、降级、限流 |
| ERROR | 错误 | 请求失败、服务不可用 |
| CRITICAL | 严重错误 | 数据损坏、服务完全不可用 |

## 指标

### RED 方法 (请求-错误-持续时间)

```promql
# 请求率
rate(http_requests_total[1m])

# 错误率
rate(http_requests_total{status=~"5.."}[1m]) / rate(http_requests_total[1m])

# 持续时间 (P50/P95/P99)
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[1m]))
```

### USE 方法 (使用率-饱和度-错误率)

| 资源 | 使用率 | 饱和度 | 错误率 |
|------|--------|--------|--------|
| CPU | cpu_usage | cpu_waiting | - |
| 内存 | mem_usage | oom_kills | - |
| 磁盘 | disk_usage | io_wait | io_errors |
| 网络 | net_throughput | queue_depth | net_errors |
| 数据库 | connections | connection_pool_wait | query_errors |

### SLO/SLI/SLA

```yaml
# SLO 定义
slo:
  name: api-availability
  target: 99.95%
  window: 30d
  slis:
    - name: error-rate
      good-events: http_requests_total{status!~"5.."}
      total-events: http_requests_total
    - name: latency
      good-events: http_request_duration_seconds{le="1"}
      total-events: http_request_duration_seconds
  error-budget: 21.9m/month  # 99.95% of 30d
```

## 分布式追踪

```python
from opentelemetry import trace
from opentelemetry.exporter.jaeger import JaegerSpanExporter

tracer = trace.get_tracer(__name__)

async def handle_request(request):
    with tracer.start_as_current_span("handle_request") as span:
        span.set_attribute("http.method", request.method)
        span.set_attribute("http.path", request.path)
        
        # 下游调用自动传播 context
        result = await db.query(...)  # 自动创建子 span
        span.set_attribute("db.rows", result.rowcount)
```

### 追踪上下文传播

```
请求 → [trace_id: abc123, span_id: 001]
  └─ HTTP 请求 → [trace_id: abc123, span_id: 002]
       └─ DB 查询 → [trace_id: abc123, span_id: 003]
       └─ 缓存读取 → [trace_id: abc123, span_id: 004]
```

## 告警规则

```yaml
groups:
  - name: api-alerts
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "API 错误率 > 5%"
          description: "过去 5 分钟错误率 {{ $value }}，超过 5% 阈值"
      
      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 2
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "P95 延迟 > 2s"
```

### 告警最佳实践

1. **告警疲劳**：只告警真正需要立即行动的问题
2. **分级**：critical (立即) / warning (工作时间) / info (仅记录)
3. **关联**：告警包含 trace_id、request_id、runbook 链接
4. **抑制**：上游故障抑制下游告警
5. **维护窗口**：计划内维护暂停告警

## 检查清单

- [ ] 结构化 JSON 日志
- [ ] 日志级别正确使用
- [ ] RED 指标已埋点
- [ ] 关键 SLO 已定义
- [ ] 分布式追踪已接入
- [ ] 告警规则已配置
- [ ] 仪表盘已创建
- [ ] 日志保留策略已配置
- [ ] 采样率合理 (生产 10-100%)
- [ ] 敏感数据已从日志中移除
```
