"""UI 运行时偏好 —— 跨 TUI / REPL 共享的编辑器与底栏状态。

主题/配色 (/theme, /color) 直接改写 ``theme.C`` 颜色表即可下一帧生效;
但**编辑器模式** (vim) 与**自定义状态栏**属于应用级状态:

- TUI 的 ``Application.editing_mode`` 与 REPL 的 ``PromptSession(vi_mode=)``
  都在构造时定型;
- TUI 底栏自定义段需要跨帧缓存命令输出。

因此这里维护一小块运行时状态 + 监听器, 让 /vim 在会话内即时切换:

- 首次读取时从 ``~/.tuan/config.yaml`` 的 ``ui.vim_mode`` /
  ``ui.statusline_command`` 加载默认值;
- 前端 (TUI/REPL) 注册弱引用监听器, 值变化时同步自身键位;
- 弱引用避免测试反复构造 UI 实例时把旧实例钉在内存里。
"""

from __future__ import annotations

import threading
import weakref
from typing import Any, Callable, Dict, List, Optional

import logging
log = logging.getLogger(__name__)


_lock = threading.Lock()
_ui_cache: Optional[Dict[str, Any]] = None
_vim_mode: Optional[bool] = None
_statusline: Optional[str] = None
_listeners: List[Any] = []


def _read_ui_section() -> Dict[str, Any]:
    """从用户配置读 ``ui`` 段 (缺失/损坏/无权限一律返回空字典)。"""
    try:
        from pathlib import Path

        from .. import _yaml as yaml
        from ..config import home_dir

        cfg = Path(home_dir()) / "config.yaml"
        if not cfg.exists():
            return {}
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        ui = data.get("ui") if isinstance(data, dict) else None
        return dict(ui) if isinstance(ui, dict) else {}
    except Exception as exc:  # noqa: BLE001 - 偏好读取失败不应影响启动
        log.debug("_read_ui_section(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        return {}


def _ui_get(key: str, default: Any) -> Any:
    """读 ui 段单个键 (整段只加载一次)。"""
    global _ui_cache
    with _lock:
        if _ui_cache is None:
            _ui_cache = _read_ui_section()
        return _ui_cache.get(key, default)


def vim_mode() -> bool:
    """当前是否启用 vi 编辑模式 (首次调用时从用户配置加载)。"""
    global _vim_mode, _ui_cache
    with _lock:
        if _vim_mode is None:
            if _ui_cache is None:
                _ui_cache = _read_ui_section()
            _vim_mode = bool(_ui_cache.get("vim_mode", False))
        return _vim_mode


def set_vim_mode(enabled: bool) -> None:
    """设置 vi 编辑模式并通知已注册的前端 (TUI 热切换键位, REPL 重建输入会话)。"""
    global _vim_mode
    with _lock:
        _vim_mode = bool(enabled)
        refs = list(_listeners)
    for ref in refs:
        cb = ref()
        if cb is None:
            with _lock:
                if ref in _listeners:
                    _listeners.remove(ref)
            continue
        try:
            cb(bool(enabled))
        except Exception as exc:  # noqa: BLE001 - 单个前端异常不影响其他前端
            log.warning("set_vim_mode(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass


def statusline_command() -> str:
    """自定义底栏命令 (空串表示使用内置状态栏)。"""
    global _statusline, _ui_cache
    with _lock:
        if _statusline is None:
            if _ui_cache is None:
                _ui_cache = _read_ui_section()
            _statusline = str(_ui_cache.get("statusline_command", "") or "")
        return _statusline


def set_statusline_command(cmd: str) -> None:
    """设置/清除 (空串) 自定义底栏命令; TUI 下一次刷新即采用。"""
    global _statusline, _ui_cache
    with _lock:
        _statusline = str(cmd or "")
        if _ui_cache is not None:
            _ui_cache["statusline_command"] = _statusline


def add_listener(fn: Callable[[bool], None]) -> None:
    """注册 vim 模式变更回调 (弱引用, 绑定方法被回收后自动清理)。"""
    try:
        ref: Any = weakref.WeakMethod(fn)
    except TypeError:
        # 非绑定方法 (函数/lambda) 无法弱引用, 退化为强引用
        ref = lambda: fn
    with _lock:
        _listeners.append(ref)


def reset_for_tests() -> None:
    """清空运行时状态与监听器 (供测试隔离)。"""
    global _ui_cache, _vim_mode, _statusline
    with _lock:
        _ui_cache = None
        _vim_mode = None
        _statusline = None
        _listeners.clear()
