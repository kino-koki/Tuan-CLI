"""mode 解析测试: 锁定「tuan 默认 standard, 只有 --yolo / --mode yolo 才进 yolo」的行为。

回归背景: 用户配置里 mode.default 被写成 yolo 后, 裸 `tuan` 会默认进入 yolo 模式。
本测试确保 _apply_mode_override 的优先级正确: yes(--yolo) > mode(--mode) > 配置值。
"""

from tuan_cli.app import build_kernel
from tuan_cli.cli.commands import _apply_mode_override


def _kernel_with_mode(tuan_home, value: str):
    kernel = build_kernel()
    config = kernel.require("config")
    config.data.setdefault("mode", {})["default"] = value
    return kernel


def test_bare_tuan_uses_config_standard(tuan_home):
    """裸 tuan (无 --yolo / --mode): 应使用配置值, 配置为 standard 则 standard。"""
    kernel = _kernel_with_mode(tuan_home, "standard")
    assert _apply_mode_override(kernel, None, yes=False) == "standard"


def test_bare_tuan_respects_config_yolo(tuan_home):
    """裸 tuan 但配置为 yolo: 尊重配置 (这是 tuan mode yolo 的显式意图)。"""
    kernel = _kernel_with_mode(tuan_home, "yolo")
    assert _apply_mode_override(kernel, None, yes=False) == "yolo"


def test_yolo_flag_forces_yolo_even_when_config_standard(tuan_home):
    """--yolo 应强制 yolo, 即使配置是 standard。"""
    kernel = _kernel_with_mode(tuan_home, "standard")
    assert _apply_mode_override(kernel, None, yes=True) == "yolo"


def test_mode_argument_overrides_config(tuan_home):
    """--mode standard 应覆盖配置里的 yolo。"""
    kernel = _kernel_with_mode(tuan_home, "yolo")
    assert _apply_mode_override(kernel, "standard", yes=False) == "standard"


def test_yolo_flag_beats_mode_argument(tuan_home):
    """--yolo 与 --mode 同时给出时, --yolo (yes) 优先。"""
    kernel = _kernel_with_mode(tuan_home, "standard")
    assert _apply_mode_override(kernel, "standard", yes=True) == "yolo"
