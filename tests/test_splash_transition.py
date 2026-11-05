"""TUI 上下文占用条回归测试 (旧 SplashTUI 已随旧 TUI 实现移除)。

锁定一个曾导致『只有吉祥物 + 100% 进度 + 无输入栏』的 bug:
  QxtTUI 的上下文占用条在 budget 未知/为 0 时不得显示 300000%/100% 这种荒谬值,
  应回落到 0%; 真实估算/预算应算出正确百分比。

注: 原 SplashTUI 启动屏测试已删除 —— SplashTUI 属于旧 TUI 实现,
已随 ui/splash.py 一起移除, 主入口统一使用 QxtTUI (内嵌加载屏)。
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_tuan_home():
    os.environ["TUAN_HOME"] = tempfile.mkdtemp()


def test_tui_context_zero_when_budget_unknown():
    """budget=0 时上下文占用条必须显示 0%, 不得出现 300000%/100%。"""
    _fresh_tuan_home()
    from tuan_cli.tui.tui import QxtTUI

    tui = QxtTUI(on_submit=lambda t: "ok", title="青小团", workspace=os.getcwd())
    tui.set_context_info(3000, 0)
    assert tui._context_pct == 0.0, "budget=0 时占用应为 0%"
    assert tui._ctx_budget == 0, "budget=0 时内部预算应保持 0 (falsy)"
    s = tui._context_string()
    assert "300000" not in s, "不得出现 300000% 荒谬值"
    assert "100%" not in s, "budget 未知时不得显示 100%"
    # i18n: 输出可能是中文"上下文"或英文"context", 检查百分比值而非前缀
    assert "0%" in s or "0.0%" in s, f"footer 应含 0%, 实际: {s}"


def test_tui_context_real_percentage():
    """真实估算/预算应算出正确百分比 (夹在 0~100)。"""
    _fresh_tuan_home()
    from tuan_cli.tui.tui import QxtTUI

    tui = QxtTUI(on_submit=lambda t: "ok", title="青小团", workspace=os.getcwd())
    tui.set_context_info(3000, 60000)
    s = tui._context_string()
    assert "5%" in s or "5.0%" in s, f"应含 5%, 实际: {s}"
    assert "3.0k" in s, f"应含 3.0k, 实际: {s}"
    assert "60.0k" in s, f"应含 60.0k, 实际: {s}"

    tui.set_context_info(65000, 60000)
    s = tui._context_string()
    assert "100" in s, f"超预算应夹到 100%, 实际: {s}"
