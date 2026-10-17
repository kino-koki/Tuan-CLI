"""YOLO 授权语义 + TUI 确认卡片 回归测试。

锁定两件事 (二者都是"开了 yolo 还要一个个敲 y"的同一类体验问题的两面):

1. yolo 是「用户已预先授权自动批准」, 不能与 standard 的严格兜底同时生效:
   非致命、非极高危的命令在 yolo 下应自动放行; 致命红线与极高危仍硬拦。
2. 命令确认不再走 run_in_terminal(print+input) —— 那条路把提示打到输入框
   所在的光标位置, 长命令会撑破输入框边框。现在挂起一张对话区底部卡片,
   工具线程阻塞在 Event 上, 用户在输入框敲 y/n 后唤醒。
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.core.kernel import Kernel
from tuan_cli.core.ipc_client import ExternalEngineManager
from tuan_cli.config.loader import Config
from tuan_cli.config.plugin import ConfigPlugin
from tuan_cli.tools.external import ExternalToolsPlugin
from tuan_cli.tools.shell import ShellPlugin, _pre_exec_guard, _strict_shell_enabled
from tuan_cli.tools.base import ToolContext
from tuan_cli.tui.tui import QxtTUI, _disp_width

AVAIL = set(ExternalEngineManager().list_engines())
HAVE_SAFETY = "safety" in AVAIL


def _kernel_with_safety() -> Kernel:
    from tuan_cli.tools import ToolRegistryPlugin

    k = Kernel()
    k.register(ConfigPlugin(Config(profile="default")))
    ToolRegistryPlugin().activate(k)
    ExternalToolsPlugin().activate(k)
    ShellPlugin().activate(k)
    return k


def _build_ctx(kernel: Kernel, *, yolo: bool = False, confirm=None) -> ToolContext:
    return ToolContext(kernel=kernel, workspace=".", yolo=yolo, confirm=confirm)


# ================================================================ 1. 严格模式 vs YOLO

def test_strict_mode_defaults_on_for_standard(monkeypatch):
    """standard: 严格兜底默认开启 (保守默认不变)。"""
    monkeypatch.delenv("TUAN_STRICT_SHELL", raising=False)
    assert _strict_shell_enabled(yolo=False) is True


def test_strict_mode_off_under_yolo(monkeypatch):
    """yolo: 严格兜底关闭 —— 这才是"开 yolo 不用再敲 y"的关键。"""
    monkeypatch.delenv("TUAN_STRICT_SHELL", raising=False)
    assert _strict_shell_enabled(yolo=True) is False


def test_strict_env_var_overrides_yolo(monkeypatch):
    """显式环境变量无条件优先 (用户显式意图 > 模式推断)。"""
    monkeypatch.setenv("TUAN_STRICT_SHELL", "1")
    assert _strict_shell_enabled(yolo=True) is True
    monkeypatch.setenv("TUAN_STRICT_SHELL", "0")
    assert _strict_shell_enabled(yolo=False) is False


@pytest.mark.skipif(not HAVE_SAFETY, reason="safety 引擎不可用")
def test_yolo_auto_approves_non_benign_command(monkeypatch):
    """yolo 下非良性但非红线的命令自动放行, 不再弹人工确认。"""
    monkeypatch.delenv("TUAN_STRICT_SHELL", raising=False)
    k = _kernel_with_safety()
    ctx = _build_ctx(k, yolo=True, confirm=lambda p: False)  # 即使确认通道恒拒
    for cmd in ("systemctl restart nginx", "kill -9 1234", "docker rm -f abc"):
        assert _pre_exec_guard(ctx, cmd) is None, f"yolo 下不应拦截: {cmd}"


@pytest.mark.skipif(not HAVE_SAFETY, reason="safety 引擎不可用")
def test_yolo_still_blocks_hard_redline(monkeypatch):
    """给 yolo 权力但不给免死金牌: 致命红线任何模式都硬拦。"""
    monkeypatch.delenv("TUAN_STRICT_SHELL", raising=False)
    k = _kernel_with_safety()
    ctx = _build_ctx(k, yolo=True, confirm=lambda p: True)
    for cmd in ("rm -rf /", "rm -rf /home", ":(){ :|:& };:"):
        reason = _pre_exec_guard(ctx, cmd)
        assert reason is not None, f"yolo 漏拦致命红线: {cmd}"


@pytest.mark.skipif(not HAVE_SAFETY, reason="safety 引擎不可用")
def test_standard_mode_unchanged(monkeypatch):
    """standard 行为完全不变: 非良性命令仍需人工确认。"""
    monkeypatch.delenv("TUAN_STRICT_SHELL", raising=False)
    k = _kernel_with_safety()
    calls = []
    ctx = _build_ctx(k, yolo=False, confirm=lambda p: calls.append(p) or True)
    assert _pre_exec_guard(ctx, "systemctl restart nginx") is None
    assert len(calls) == 1, "standard 下应弹 1 次确认"


# ================================================================ 2. TUI 确认卡片

class _FakeApp:
    """最小 Application 替身: 只提供 confirm() 需要的 is_running / invalidate。"""

    def __init__(self) -> None:
        self.is_running = True

    def invalidate(self) -> None:
        pass


def _make_tui() -> QxtTUI:
    tui = QxtTUI(on_submit=lambda s: None)
    tui._app = _FakeApp()
    return tui


def _wait_pending(tui: QxtTUI, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while tui._confirm_pending is None and time.time() < deadline:
        time.sleep(0.01)
    return tui._confirm_pending is not None


def _run_confirm(tui: QxtTUI, **kw):
    """在后台线程跑 confirm(), 返回结果容器与线程。"""
    box: dict = {}
    th = threading.Thread(
        target=lambda: box.update(v=tui.confirm(kw.get("prompt", "rm -rf ./build"),
                                                expected=kw.get("expected"))),
        daemon=True,
    )
    th.start()
    return box, th


def test_confirm_hangs_card_and_accepts_y():
    tui = _make_tui()
    box, th = _run_confirm(tui)
    assert _wait_pending(tui), "confirm() 应挂起确认卡片"
    tui._resolve_confirm("y")
    th.join(5)
    assert box.get("v") is True
    assert tui._confirm_pending is None


def test_confirm_rejects_n():
    tui = _make_tui()
    box, th = _run_confirm(tui)
    assert _wait_pending(tui)
    tui._resolve_confirm("n")
    th.join(5)
    assert box.get("v") is False


def test_confirm_invalid_input_keeps_card():
    """无效输入不消费卡片 (用户可重输), 也不放行。"""
    tui = _make_tui()
    box, th = _run_confirm(tui)
    assert _wait_pending(tui)
    tui._resolve_confirm("maybe")
    assert tui._confirm_pending is not None, "无效输入后卡片应仍在"
    tui._resolve_confirm("y")
    th.join(5)
    assert box.get("v") is True


def test_confirm_code_required_when_expected():
    """有确认码时 y 不能绕过, 必须精确键入。"""
    tui = _make_tui()
    box, th = _run_confirm(tui, expected="X7K2")
    assert _wait_pending(tui)
    tui._resolve_confirm("y")                 # y 不该绕过确认码
    assert tui._confirm_pending is not None
    tui._resolve_confirm("X7K2")
    th.join(5)
    assert box.get("v") is True


def test_cancel_confirm_unblocks_thread():
    """退出时解冻: 结果按拒绝处理, 线程不被永久挂住。"""
    tui = _make_tui()
    box, th = _run_confirm(tui)
    assert _wait_pending(tui)
    tui.cancel_confirm()
    th.join(5)
    assert not th.is_alive(), "cancel_confirm 后线程应结束"
    assert box.get("v") is False


def test_confirm_card_never_exceeds_box_width():
    """卡片每行都不超出盒子宽度 —— 这正是旧方案撑破输入框的失效点。"""
    tui = _make_tui()
    tui._confirm_pending = {
        "prompt": "Get-ChildItem " + "A" * 400,   # 超长命令
        "expected": "X7K2",
        "event": threading.Event(),
        "result": False,
    }
    out = tui._render_confirm_card()
    text = "".join(seg for _, seg in out)
    width = tui._box_width()
    for line in text.split("\n"):
        assert _disp_width(line) <= width, f"卡片行超宽 ({_disp_width(line)}>{width}): {line[:40]}"
    assert "X7K2" in text, "确认码应在卡片中可见"


def test_confirm_card_wraps_long_command():
    """长命令折行铺开而非截断: 命令尾部 (可能是危险参数) 必须可见。"""
    tui = _make_tui()
    cmd = "rm -rf " + "/".join(f"seg{i}" for i in range(40))
    tui._confirm_pending = {"prompt": cmd, "expected": None,
                            "event": threading.Event(), "result": False}
    text = "".join(seg for _, seg in tui._render_confirm_card())
    assert "seg39" in text, "长命令尾部被截断, 用户看不到完整命令"


def test_confirm_falls_back_to_terminal_without_app():
    """无运行中的应用 (headless) 时退回终端 input, 不抛异常。"""
    import io
    tui = QxtTUI(on_submit=lambda s: None)
    tui._app = None
    import builtins
    real_input = builtins.input
    builtins.input = lambda *a, **k: "y"
    try:
        assert tui.confirm("ls") is True
    finally:
        builtins.input = real_input
