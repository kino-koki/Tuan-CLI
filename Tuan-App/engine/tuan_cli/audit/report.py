"""审计报告导出: 支持多种格式的合规审计报告。

支持格式:
- JSON: 结构化数据
- CSV: 电子表格兼容
- Markdown: 可读性报告
- HTML: 可视化报告
- SOC2: 合规报告格式
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .store import AuditEvent, AuditQuery, AuditStore


class AuditReportGenerator:
    """审计报告生成器。"""
    
    def __init__(self, store: AuditStore) -> None:
        self.store = store
    
    def generate(
        self,
        output_path: str,
        fmt: str = "markdown",
        query: Optional[AuditQuery] = None,
        title: str = "青小团审计报告",
    ) -> Dict[str, Any]:
        """生成审计报告。
        
        Args:
            output_path: 输出文件路径
            fmt: 格式 (json/csv/markdown/html/soc2)
            query: 查询条件
            title: 报告标题
        
        Returns:
            {"path": str, "count": int, "fmt": str}
        """
        events = self.store.query(query)
        
        if fmt == "json":
            return self._generate_json(events, output_path)
        elif fmt == "csv":
            return self._generate_csv(events, output_path)
        elif fmt == "markdown":
            return self._generate_markdown(events, output_path, title)
        elif fmt == "html":
            return self._generate_html(events, output_path, title)
        elif fmt == "soc2":
            return self._generate_soc2(events, output_path, title)
        else:
            raise ValueError(f"不支持的格式: {fmt}")
    
    def _generate_json(self, events: List[AuditEvent], path: str) -> Dict[str, Any]:
        """生成 JSON 格式报告。"""
        records = []
        for ev in events:
            records.append({
                "seq": ev.seq,
                "timestamp": ev.ts,
                "iso_time": datetime.fromtimestamp(ev.ts, tz=timezone.utc).isoformat(),
                "event_type": ev.type,
                "payload": ev.payload,
            })
        
        target = Path(path)
        from tuan_cli.core.atomicio import atomic_write_text
        atomic_write_text(target, json.dumps(records, ensure_ascii=False, indent=2))
        return {"path": str(target), "count": len(records), "fmt": "json"}
    
    def _generate_csv(self, events: List[AuditEvent], path: str) -> Dict[str, Any]:
        """生成 CSV 格式报告。"""
        import io
        target = Path(path)
        from tuan_cli.core.atomicio import atomic_write_text
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(["序号", "时间戳", "ISO时间", "事件类型", "载荷"])
        for ev in events:
            iso = datetime.fromtimestamp(ev.ts, tz=timezone.utc).isoformat()
            writer.writerow([
                ev.seq,
                ev.ts,
                    iso,
                    ev.type,
                    json.dumps(ev.payload, ensure_ascii=False),
                ])
        atomic_write_text(target, buf.getvalue())
        return {"path": str(target), "count": len(events), "fmt": "csv"}
    
    def _generate_markdown(
        self, events: List[AuditEvent], path: str, title: str
    ) -> Dict[str, Any]:
        """生成 Markdown 格式报告。"""
        lines = []
        lines.append(f"# {title}")
        lines.append("")
        lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"> 事件总数: {len(events)}")
        lines.append("")
        
        # 统计摘要
        type_counts: Dict[str, int] = {}
        for ev in events:
            type_counts[ev.type] = type_counts.get(ev.type, 0) + 1
        
        lines.append("## 统计摘要")
        lines.append("")
        lines.append("| 事件类型 | 数量 |")
        lines.append("|---------|------|")
        for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
            lines.append(f"| {t} | {c} |")
        lines.append("")
        
        # 事件详情
        lines.append("## 事件详情")
        lines.append("")
        
        for ev in events:
            iso = datetime.fromtimestamp(ev.ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"### [{ev.seq}] {ev.type}")
            lines.append("")
            lines.append(f"- **时间**: {iso}")
            lines.append(f"- **类型**: {ev.type}")
            lines.append("")
            
            if ev.payload:
                lines.append("**载荷**:")
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(ev.payload, ensure_ascii=False, indent=2))
                lines.append("```")
                lines.append("")
        
        target = Path(path)
        from tuan_cli.core.atomicio import atomic_write_text
        atomic_write_text(target, "\n".join(lines))
        return {"path": str(target), "count": len(events), "fmt": "markdown"}
    
    def _generate_html(
        self, events: List[AuditEvent], path: str, title: str
    ) -> Dict[str, Any]:
        """生成 HTML 格式报告。"""
        # 统计
        type_counts: Dict[str, int] = {}
        for ev in events:
            type_counts[ev.type] = type_counts.get(ev.type, 0) + 1
        
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 2px solid #007bff; padding-bottom: 10px; }}
        .meta {{ color: #666; margin-bottom: 20px; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 20px 0; }}
        .stat-card {{ background: #f8f9fa; padding: 15px; border-radius: 6px; text-align: center; }}
        .stat-value {{ font-size: 2em; font-weight: bold; color: #007bff; }}
        .stat-label {{ color: #666; font-size: 0.9em; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f8f9fa; font-weight: 600; }}
        tr:hover {{ background: #f5f5f5; }}
        .event-type {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.85em; }}
        .type-tool {{ background: #e3f2fd; color: #1565c0; }}
        .type-model {{ background: #f3e5f5; color: #7b1fa2; }}
        .type-security {{ background: #ffebee; color: #c62828; }}
        .type-other {{ background: #e8f5e9; color: #2e7d32; }}
        .payload {{ background: #f8f9fa; padding: 10px; border-radius: 4px; font-family: monospace; font-size: 0.9em; white-space: pre-wrap; max-height: 200px; overflow-y: auto; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{title}</h1>
        <div class="meta">
            <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>事件总数: {len(events)}</p>
        </div>
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-value">{len(events)}</div>
                <div class="stat-label">总事件数</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{len(type_counts)}</div>
                <div class="stat-label">事件类型</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{events[0].seq if events else 0}</div>
                <div class="stat-label">起始序号</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{events[-1].seq if events else 0}</div>
                <div class="stat-label">结束序号</div>
            </div>
        </div>
        
        <h2>事件类型分布</h2>
        <table>
            <tr><th>类型</th><th>数量</th><th>占比</th></tr>
"""
        
        for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
            pct = c / len(events) * 100 if events else 0
            html += f'            <tr><td>{t}</td><td>{c}</td><td>{pct:.1f}%</td></tr>\n'
        
        html += """        </table>
        
        <h2>事件详情</h2>
        <table>
            <tr><th>序号</th><th>时间</th><th>类型</th><th>载荷</th></tr>
"""
        
        for ev in events:
            iso = datetime.fromtimestamp(ev.ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            payload_json = json.dumps(ev.payload, ensure_ascii=False, indent=2)
            # 根据类型选择样式
            type_class = "type-other"
            if "tool" in ev.type:
                type_class = "type-tool"
            elif "model" in ev.type:
                type_class = "type-model"
            elif "security" in ev.type or "auth" in ev.type:
                type_class = "type-security"
            
            html += f"""            <tr>
                <td>{ev.seq}</td>
                <td>{iso}</td>
                <td><span class="event-type {type_class}">{ev.type}</span></td>
                <td><div class="payload">{payload_json[:500]}{'...' if len(payload_json) > 500 else ''}</div></td>
            </tr>
"""
        
        html += """        </table>
    </div>
</body>
</html>"""
        
        target = Path(path)
        target.write_text(html, encoding="utf-8")
        return {"path": str(target), "count": len(events), "fmt": "html"}
    
    def _generate_soc2(
        self, events: List[AuditEvent], path: str, title: str
    ) -> Dict[str, Any]:
        """生成 SOC2 合规报告格式。"""
        # SOC2 相关事件类型
        soc2_event_types = [
            "user.login", "user.logout", "user.created", "user.deleted",
            "permission.changed", "permission.granted", "permission.revoked",
            "data.access", "data.modified", "data.deleted",
            "security.alert", "security.blocked", "security.allowed",
            "config.changed", "config.exported",
            "tool.executed", "tool.denied", "tool.failed",
            "model.switched", "model.error",
        ]
        
        # 过滤相关事件
        relevant_events = [ev for ev in events if ev.type in soc2_event_types]
        
        # 统计
        access_events = [ev for ev in relevant_events if "access" in ev.type or "login" in ev.type]
        modification_events = [ev for ev in relevant_events if "modified" in ev.type or "changed" in ev.type]
        security_events = [ev for ev in relevant_events if "security" in ev.type or "blocked" in ev.type]
        
        report = {
            "report_type": "SOC2 Compliance Report",
            "generated_at": datetime.now().isoformat(),
            "period": {
                "start": datetime.fromtimestamp(events[0].ts).isoformat() if events else None,
                "end": datetime.fromtimestamp(events[-1].ts).isoformat() if events else None,
            },
            "summary": {
                "total_events": len(events),
                "relevant_events": len(relevant_events),
                "access_events": len(access_events),
                "modification_events": len(modification_events),
                "security_events": len(security_events),
            },
            "controls": {
                "CC6.1": {
                    "name": "Logical Access Controls",
                    "description": "系统限制对信息和系统功能的访问",
                    "findings": f"检测到 {len(access_events)} 个访问相关事件",
                    "status": "PASS" if len(access_events) < 100 else "REVIEW",
                },
                "CC6.2": {
                    "name": "Access Authorization",
                    "description": "在授予对系统的访问权限之前，系统会先验证并授权用户",
                    "findings": f"检测到 {len(security_events)} 个安全事件",
                    "status": "PASS" if len(security_events) < 10 else "REVIEW",
                },
                "CC7.1": {
                    "name": "System Monitoring",
                    "description": "系统监控组件的安全事件",
                    "findings": f"共记录 {len(events)} 个审计事件",
                    "status": "PASS",
                },
            },
            "events": [
                {
                    "seq": ev.seq,
                    "timestamp": datetime.fromtimestamp(ev.ts, tz=timezone.utc).isoformat(),
                    "type": ev.type,
                    "category": self._categorize_event(ev.type),
                    "payload": ev.payload,
                }
                for ev in relevant_events[:1000]  # 限制数量
            ],
        }
        
        target = Path(path)
        from tuan_cli.core.atomicio import atomic_write_text
        atomic_write_text(target, json.dumps(report, ensure_ascii=False, indent=2))
        return {"path": str(target), "count": len(relevant_events), "fmt": "soc2"}
    
    def _categorize_event(self, event_type: str) -> str:
        """将事件类型分类为 SOC2 控制域。"""
        if "login" in event_type or "logout" in event_type or "access" in event_type:
            return "Access Control"
        elif "modified" in event_type or "changed" in event_type or "deleted" in event_type:
            return "System Operations"
        elif "security" in event_type or "blocked" in event_type:
            return "Security Operations"
        elif "tool" in event_type:
            return "System Operations"
        elif "model" in event_type:
            return "System Operations"
        else:
            return "Other"


def generate_report(
    store: AuditStore,
    output_path: str,
    fmt: str = "markdown",
    query: Optional[AuditQuery] = None,
    title: str = "青小团审计报告",
) -> Dict[str, Any]:
    """便捷函数: 生成审计报告。"""
    generator = AuditReportGenerator(store)
    return generator.generate(output_path, fmt, query, title)
