"""``tuan kernel`` CLI 的单元测试 (cmd_kernel.py)。

内核可观测性。覆盖:
1. _get_kernel: 真实构建成功 / 失败回退空 Kernel
2. _cmd_kernel_events: 无事件 / 有事件 / limit / JSON / 按类型统计
3. _cmd_kernel_services: 无容器 / 正常 / 单服务过滤 / JSON / 无服务
4. _cmd_kernel_middleware: 无总线 / 正常 / JSON / 无中间件
5. cmd_kernel: 默认 events / 各子命令 / 未知子命令

通过 monkeypatch 打桩 _get_kernel 返回 fake Kernel。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_kernel as P


def _args(**kw) -> SimpleNamespace:
    base = dict(kernel_cmd=None, json=False, limit=0, service="")
    base.update(kw)
    return SimpleNamespace(**base)


class _FakeEv:
    def __init__(self, seq=1, ts=1000.0, type="activate", payload=None):
        self.seq = seq
        self.ts = ts
        self.type = type
        self.payload = payload or {}


class _FakeContainer:
    def __init__(self, services=None, owners=None):
        self.services = services or {}
        self.service_owners = owners or {}

    def contributions(self, name):
        return self.services.get(name, [])


class _FakeBus:
    def __init__(self, middleware=None):
        self.middleware_names = middleware or []


class _FakeKernel:
    def __init__(self, events=None, services=None, owners=None,
                 middleware=None, has_container=True, has_bus=True):
        self.events = events or []
        if has_container:
            self.services = _FakeContainer(services or {}, owners or {})
        if has_bus:
            self.bus = _FakeBus(middleware or [])


def _patch_kernel(monkeypatch, **kw) -> None:
    monkeypatch.setattr(P, "_get_kernel", lambda: _FakeKernel(**kw))


# ============================================================ _get_kernel


class TestGetKernel:
    def test_build_success(self) -> None:
        rc = P._get_kernel()
        assert rc is not None

    def test_fallback_empty_kernel(self, monkeypatch) -> None:
        def _raise():
            raise RuntimeError("boom")
        monkeypatch.setattr("tuan_cli.app.build_kernel", _raise)
        rc = P._get_kernel()
        assert rc is not None  # 回退空 Kernel


# ============================================================ events 子命令


class TestEvents:
    def test_empty(self, monkeypatch) -> None:
        _patch_kernel(monkeypatch, events=[])
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P._cmd_kernel_events(_args(), json_mode=False)
        assert rc == 0
        assert any("无事件" in p for p in printed)

    def test_with_events(self, monkeypatch) -> None:
        _patch_kernel(monkeypatch, events=[
            _FakeEv(seq=1, ts=1.0, type="activate"),
            _FakeEv(seq=2, ts=2.0, type="register"),
        ])
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P._cmd_kernel_events(_args(), json_mode=False)
        assert rc == 0
        text = "\n".join(printed)
        assert "事件总线" in text
        assert "activate" in text

    def test_limit(self, monkeypatch) -> None:
        _patch_kernel(monkeypatch, events=[
            _FakeEv(seq=i, ts=float(i), type="ev") for i in range(100)
        ])
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P._cmd_kernel_events(_args(limit=5), json_mode=False)
        assert rc == 0

    def test_json_output(self, monkeypatch, capsys) -> None:
        _patch_kernel(monkeypatch, events=[
            _FakeEv(seq=1, ts=1.0, type="activate"),
            _FakeEv(seq=2, ts=2.0, type="activate"),
        ])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_kernel_events(_args(), json_mode=True)
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["total"] == 2
        assert data["by_type"]["activate"] == 2
        assert len(data["events"]) == 2

    def test_non_numeric_ts(self, monkeypatch) -> None:
        _patch_kernel(monkeypatch, events=[
            _FakeEv(seq=1, ts="not-number", type="ev"),
        ])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_kernel_events(_args(), json_mode=False)
        assert rc == 0


# ============================================================ services 子命令


class TestServices:
    def test_no_container(self, monkeypatch) -> None:
        monkeypatch.setattr(P, "_get_kernel",
                            lambda: _FakeKernel(has_container=False))
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P._cmd_kernel_services(_args(), json_mode=False)
        assert rc == 1
        assert any("无服务容器" in p for p in printed)

    def test_normal(self, monkeypatch) -> None:
        _patch_kernel(monkeypatch,
                      services={"config": [("plugin", "before")]},
                      owners={"config": "ConfigPlugin"})
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P._cmd_kernel_services(_args(), json_mode=False)
        assert rc == 0
        text = "\n".join(printed)
        assert "config" in text
        assert "ConfigPlugin" in text

    def test_filter_by_name(self, monkeypatch) -> None:
        _patch_kernel(monkeypatch,
                      services={"config": [], "config": []},
                      owners={"config": "A", "config": "B"})
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_kernel_services(_args(service="config"), json_mode=False)
        assert rc == 0

    def test_json_output(self, monkeypatch, capsys) -> None:
        _patch_kernel(monkeypatch,
                      services={"config": [("p", "before"), ("p2", "after")]},
                      owners={"config": "Plugin"})
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_kernel_services(_args(), json_mode=True)
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["count"] == 1
        assert data["services"][0]["contributors"] == 2

    def test_empty(self, monkeypatch) -> None:
        _patch_kernel(monkeypatch, services={}, owners={})
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P._cmd_kernel_services(_args(), json_mode=False)
        assert rc == 0
        assert any("无服务" in p for p in printed)


# ============================================================ middleware 子命令


class TestMiddleware:
    def test_no_bus(self, monkeypatch) -> None:
        monkeypatch.setattr(P, "_get_kernel",
                            lambda: _FakeKernel(has_bus=False))
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P._cmd_kernel_middleware(_args(), json_mode=False)
        assert rc == 1
        assert any("无事件总线" in p for p in printed)

    def test_normal(self, monkeypatch) -> None:
        _patch_kernel(monkeypatch, middleware=["auth", "logging"])
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P._cmd_kernel_middleware(_args(), json_mode=False)
        assert rc == 0
        text = "\n".join(printed)
        assert "auth" in text
        assert "logging" in text

    def test_empty(self, monkeypatch) -> None:
        _patch_kernel(monkeypatch, middleware=[])
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P._cmd_kernel_middleware(_args(), json_mode=False)
        assert rc == 0
        assert any("无中间件" in p for p in printed)

    def test_json_output(self, monkeypatch, capsys) -> None:
        _patch_kernel(monkeypatch, middleware=["auth"])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_kernel_middleware(_args(), json_mode=True)
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["count"] == 1
        assert data["middleware"] == ["auth"]


# ============================================================ 入口


class TestCmdKernel:
    def test_default_events(self, monkeypatch) -> None:
        _patch_kernel(monkeypatch, events=[])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_kernel(_args())
        assert rc == 0

    def test_events_subcommand(self, monkeypatch) -> None:
        _patch_kernel(monkeypatch, events=[])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_kernel(_args(kernel_cmd="events"))
        assert rc == 0

    def test_services_subcommand(self, monkeypatch) -> None:
        _patch_kernel(monkeypatch, services={}, owners={})
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_kernel(_args(kernel_cmd="services"))
        assert rc == 0

    def test_middleware_subcommand(self, monkeypatch) -> None:
        _patch_kernel(monkeypatch, middleware=[])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_kernel(_args(kernel_cmd="middleware"))
        assert rc == 0

    def test_unknown_subcommand(self, monkeypatch) -> None:
        _patch_kernel(monkeypatch)
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_kernel(_args(kernel_cmd="bogus"))
        assert rc == 1
        assert any("未知" in p for p in printed)
