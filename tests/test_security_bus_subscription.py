"""SecurityEventBus 订阅/解除订阅回归测试 (防 handler 泄漏)。"""

from __future__ import annotations

import time

from qingxiaotuan.core.security_bus import SecurityEvent, SecurityEventBus, SecurityEventType
from qingxiaotuan.harden.audit_export import AuditExporter


def _evt(etype: str = SecurityEventType.COMMAND_BLOCKED) -> SecurityEvent:
    return SecurityEvent(
        event_type=etype,
        timestamp=time.time(),
        payload={"cmd": "rm -rf /"},
        source="test",
        severity="critical",
    )


def test_on_and_emit_dispatch():
    bus = SecurityEventBus()
    seen = []
    bus.on(SecurityEventType.COMMAND_BLOCKED, lambda e: seen.append(e.event_type))
    bus.emit(_evt())
    assert seen == [SecurityEventType.COMMAND_BLOCKED]


def test_wildcard_matches_all():
    bus = SecurityEventBus()
    seen = []
    bus.on("*", lambda e: seen.append(e.event_type))
    bus.emit(_evt(SecurityEventType.REDLINE_HIT))
    bus.emit(_evt(SecurityEventType.NETWORK_BLOCKED))
    assert seen == [SecurityEventType.REDLINE_HIT, SecurityEventType.NETWORK_BLOCKED]


def test_off_wildcard_stops_dispatch():
    bus = SecurityEventBus()
    seen = []

    def h(e):
        seen.append(e.event_type)

    bus.on("*", h)
    bus.emit(_evt())
    assert len(seen) == 1

    assert bus.off("*", h) is True
    bus.emit(_evt())
    assert len(seen) == 1  # 不再收到


def test_off_specific_type_and_empty_cleanup():
    bus = SecurityEventBus()
    seen = []

    def h(e):
        seen.append(e.event_type)

    bus.on(SecurityEventType.REDLINE_HIT, h)
    assert bus.off(SecurityEventType.REDLINE_HIT, h) is True
    # 空列表应从 _handlers 移除
    assert SecurityEventType.REDLINE_HIT not in bus._handlers
    bus.emit(_evt(SecurityEventType.REDLINE_HIT))
    assert seen == []


def test_off_unknown_handler_returns_false():
    bus = SecurityEventBus()
    assert bus.off("*", lambda e: None) is False
    assert bus.off("some.type", lambda e: None) is False


def test_off_does_not_affect_other_handlers():
    bus = SecurityEventBus()
    seen_a, seen_b = [], []
    ha = lambda e: seen_a.append(e.event_type)  # noqa: E731
    hb = lambda e: seen_b.append(e.event_type)  # noqa: E731
    bus.on("*", ha)
    bus.on("*", hb)
    bus.off("*", ha)
    bus.emit(_evt())
    assert seen_a == []
    assert seen_b == [SecurityEventType.COMMAND_BLOCKED]


def test_exporter_attach_detach_no_leak():
    bus = SecurityEventBus()
    ex = AuditExporter(formats=("jsonl",))
    ex.attach(bus)
    assert len(bus._wildcard_handlers) == 1
    ex.detach()
    assert len(bus._wildcard_handlers) == 0
    # 重复 detach 安全
    ex.detach()
    assert len(bus._wildcard_handlers) == 0


def test_repeated_attach_detach_cycles():
    bus = SecurityEventBus()
    for _ in range(50):
        ex = AuditExporter(formats=("jsonl",))
        ex.attach(bus)
        ex.detach()
    assert len(bus._wildcard_handlers) == 0
