"""生命周期域: 应用关闭与动画心跳。

本模块由 tui.py 的 QxtTUI 拆分而来, 方法体逐行原样迁移 (无逻辑改动)。
模块级常量/工具/小类集中在 `tuan_cli.tui.common`, 由 `from .common import *`
注入到本模块命名空间, 因此方法体内对模块级名字的引用保持不变。
"""

from __future__ import annotations

from .common import *  # noqa: F401,F403

from ..ui.slogans import mapping  # noqa: F401  (tui.py 顶部同名 import)

import logging
log = logging.getLogger(__name__)


class LifecycleMixin:
    """生命周期域: 应用关闭与动画心跳。"""

    # ---- 跨 mixin 共享实例属性/方法 (纯声明, 运行期不赋值) ----
    _app: Any
    _busy: Any
    _closed: Any
    _frame: Any
    _moon_frame: Any
    _running: Any
    _slogan_dispatch: Callable[..., Any]
    _slogan_lock: Any
    _slogan_log: Any
    _slogan_owner: Any
    # close() 封存的是 mapping.take_owner_log 的 SloganDecision 快照，
    # 与 _release_slogan_owner 的 dict 行共存 —— 元素类型按 Any 声明
    _slogan_sealed: Tuple[Any, ...]
    _streaming: Any

    def close(self) -> None:
            self._closed = True
            # slogans: close() 先记 session.exit → take_owner_log 取走 owner 桶
            # (避免被记成被动淘汰) → 在锁内把**全局桶返回的决策快照**封存为
            # sealed (含 session.exit, 供 slogan_closed_trace 回放)。
            try:
                self._slogan_dispatch("session.exit")
            except Exception as exc:  # noqa: BLE001
                log.warning("LifecycleMixin.close(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                pass
            sealed = mapping.take_owner_log(self._slogan_owner)
            with self._slogan_lock:
                self._slogan_sealed = sealed
            if self._app and self._app.is_running:
                self._app.exit()

    def _animate(self) -> None:
            while not self._closed:
                if self._busy or self._streaming or self._running:
                    # 模型思考/流式/工具期间: 月亮转圈, 每帧 120ms
                    self._moon_frame = (self._moon_frame + 1) % len(_MOON_FRAMES)
                    self._frame = (self._frame + 1) % len(_SPLASH_FRAMES)
                    time.sleep(_MOON_INTERVAL)
                else:
                    time.sleep(0.3)
                if self._app and self._app.is_running:
                    self._app.invalidate()
