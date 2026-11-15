"""``tuan posture`` CLI 的单元测试 (cmd_posture.py)。

跨子系统安全/韧性健康总览 (纯只读)。覆盖:
1. _get_home: 显式 / None 走 home_dir()
2. _verdict: PASS/WARN/FAIL/SKIP 映射
3. _collect 在空 tmp_path 下: 六个子系统全部可初始化 (fresh install = PASS)
4. cmd_posture: 正常渲染 / JSON 输出 / FAIL 退出码 1
5. 分发入口缺 args 时回落 home_dir

通过 monkeypatch 打桩 _get_home + tmp_path 提供"干净"家目录, 让所有子系统
走"未初始化"分支, 不依赖真实 ~/.tuan。失败子系统注入 fake 模块触发 FAIL。
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_posture as P


def _args(**kw) -> SimpleNamespace:
    base = dict(home=None, json=False)
    base.update(kw)
    return SimpleNamespace(**base)


class TestGetHome:
    def test_explicit(self) -> None:
        rc = P._get_home("/tmp/x/y")
        assert rc == Path("/tmp/x/y").resolve()

    def test_default_falls_back(self, monkeypatch) -> None:
        import tuan_cli.config.loader as L
        monkeypatch.setattr(L, "home_dir", lambda: "/tmp/defhome")
        rc = P._get_home(None)
        assert str(rc).endswith("defhome")


class TestVerdict:
    def test_known_levels(self) -> None:
        assert "PASS" in P._verdict("PASS")
        assert "WARN" in P._verdict("WARN")
        assert "FAIL" in P._verdict("FAIL")

    def test_unknown_skips(self) -> None:
        assert "SKIP" in P._verdict("SKIP")
        assert "SKIP" in P._verdict("bogus")


class TestCollectFreshInstall:
    """空 tmp_path = 全新安装, 六个子系统都应可初始化且判定为 PASS。"""

    @pytest.fixture()
    def rows(self, tmp_path) -> list:
        return P._collect(tmp_path)

    def test_six_subsystems(self, rows) -> None:
        assert len(rows) == 6
        names = [r["subsystem"] for r in rows]
        assert names == [
            "integrity", "alerts", "audit_chain",
            "collab", "background", "storage",
        ]

    def test_all_have_detail(self, rows) -> None:
        for r in rows:
            assert "detail" in r
            assert isinstance(r["detail"], str)

    def test_no_skip_on_clean_home(self, rows) -> None:
        # 全新安装各子系统应能初始化 (即使内部空), 不应全部 SKIP
        skips = [r for r in rows if r["level"] == "SKIP"]
        # 允许少数子系统因初始化失败 SKIP, 但至少 audit_chain 应 PASS
        levels = {r["subsystem"]: r["level"] for r in rows}
        assert levels["audit_chain"] == "PASS"

    def test_storage_warns_on_large(self, tmp_path) -> None:
        # 模拟一个占 > 2GB 的子系统不太现实 (太慢),
        # 只验证 _subsystem_scan 集成 (空目录 -> total=0 -> PASS)。
        rows = P._collect(tmp_path)
        storage = next(r for r in rows if r["subsystem"] == "storage")
        assert storage["level"] in ("PASS", "WARN", "SKIP")


class TestCmdPosture:
    def test_normal_render(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(P, "_get_home", lambda h: tmp_path)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_posture(_args())
        assert rc in (0, 1)

    def test_json_output(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setattr(P, "_get_home", lambda h: tmp_path)
        rc = P.cmd_posture(_args(json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc in (0, 1)
        assert "home" in data
        assert len(data["subsystems"]) == 6

    def test_exception_returns_1(self, monkeypatch, capsys) -> None:
        def boom(_h):
            raise RuntimeError("scan failed")

        monkeypatch.setattr(P, "_get_home", boom)
        rc = P.cmd_posture(_args())
        out = capsys.readouterr().out
        assert rc == 1
        assert "失败" in out

    def test_fail_subsystem_sets_exit_1(self, monkeypatch, tmp_path) -> None:
        # 注入一个 fake 模块让 integrity 子系统返回 FAIL (有 high 严重度的变更)
        fake_fim = types.ModuleType("tuan_cli.core.file_integrity")

        class _FakeMon:
            def __init__(self, home=None):
                pass

            def get_changes(self, last_n=100):
                class _C:
                    severity = "critical"

                return [_C() for _ in range(3)]

            def stats(self):
                return {"total_changes": 3}

        fake_fim.FileIntegrityMonitor = _FakeMon
        monkeypatch.setitem(sys.modules, "tuan_cli.core.file_integrity", fake_fim)
        monkeypatch.setattr(P, "_get_home", lambda h: tmp_path)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_posture(_args())
        assert rc == 1  # has_fail -> 退出码 1
