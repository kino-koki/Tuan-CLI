"""Agent 的模型路由与工具集 mixin (自动路由 / 暴露级别 / 工具 schema)。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, cast
import inspect

if TYPE_CHECKING:
    from ..config import Config
    from ..vision.blocks import ImageRef
    from .kernel import Kernel
    from .model_router import AgentModelRouter


class AgentRoutingMixin:
    # ---- 跨 mixin 共享实例状态 (纯声明; 由 Agent.__init__ 初始化) ----
    config: "Config"
    kernel: "Kernel"
    model: Any
    registry: Any
    plan_mode: bool
    yolo: bool
    pending_images: List["ImageRef"]
    _router: "AgentModelRouter"

    def _maybe_route_model(self, task: str, override: int = 0, has_images: Optional[bool] = None) -> None:
        """按 router 配置自动选择/切换模型 —— 委托给 AgentModelRouter。"""
        self._router.maybe_route(task, override=override, has_images=has_images,
                                current_model=self.model, pending_images=self.pending_images)
        # 路由可能切换了模型, 同步到当前实例
        if self._router.last_route and self._router.last_route.get("switch"):
            self.model = self.kernel.require("model_adapter")


    def effective_tool_set(self) -> str:
        """当前生效的工具集名 (plan/yolo/standard), 与 plan_mode/yolo 实时同步。

        主循环据此向模型提供对应模式的工具清单 —— Plan 只给只读工具,
        YOLO/Standard 给全量工具 (危险操作的批准策略由权限闸门控制)。
        """
        self._tool_set = self._compute_tool_set()
        return self._tool_set


    def _compute_tool_set(self) -> str:
        if self.plan_mode:
            return "plan"
        if self.yolo:
            return "yolo"
        return "standard"


    def _resolve_exposure(self) -> str:
        """解析工具暴露档位 (minimal|standard|full)。

        config ``tools.exposure`` 可为 minimal/standard/full/auto; auto 按当前模型
        名启发式解析 (弱模型 → minimal, 否则 standard)。解析失败一律回退 standard,
        绝不因配置异常把工具集降成空 (fail-safe)。
        """
        from ..tools.tiers import DEFAULT_EXPOSURE, resolve_exposure
        raw: Optional[str] = None
        model: str = ""
        try:
            raw = self.config.get("tools.exposure", None)
        except Exception:  # noqa: BLE001
            raw = None
        try:
            model = self.config.get("model.model", "") or ""
        except Exception:  # noqa: BLE001
            model = ""
        try:
            return resolve_exposure(raw, model)
        except Exception:  # noqa: BLE001
            return DEFAULT_EXPOSURE


    def _schemas(self) -> Any:
        """取传给模型的工具清单 (按 effective_tool_set + exposure 过滤)。

        对 registry.schemas 做接口兼容: 若它接受 tool_set / exclude_tools / exposure
        关键字 (真实 ToolRegistry / 测试双), 则透传; 否则极简 registry (仅接受无参调用)
        退化为裸调, 保证主循环总能拿到 schema 列表而不会因 TypeError 中断模型调用。
        详见 test_tool_set_wiring (要求透传 tool_set) 与 test_router/test_vision
        (极简 fake 只接受 schemas())。这确保主循环能正常进入模型轮并推进转台切换。
        """
        sch = getattr(self.registry, "schemas", None)
        if sch is None:
            return []
        try:
            sig = inspect.signature(sch)
        except (TypeError, ValueError):
            sig = None  # 无法反射签名 → 保守透传 (真实 registry 支持关键字)
        params = list(sig.parameters.values()) if sig is not None else []
        has_kw = sig is None or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params
        )
        # 用 getattr 兜底: _schemas 在模型调用热路径上, 属性缺失不应让整个模型轮
        # 崩溃成 "[模型错误] 'Agent' object has no attribute ..."。正常构造时
        # __init__ 已设置这两个属性; 这里的兜底覆盖子类覆写 __init__ 未调用 super、
        # 以及测试用 Agent.__new__ 绕过 __init__ 的场景。
        tool_set = getattr(self, "_tool_set", None) or self.effective_tool_set()
        if has_kw or any(p.name == "tool_set" for p in params):
            kwargs: Dict[str, Any] = {
                "tool_set": tool_set,
                "exclude_tools": getattr(self, "exclude_tools", set()),
            }
            # 仅当目标 schemas 支持 exposure 时透传 (兼容只认 tool_set 的旧双)
            if has_kw or any(p.name == "exposure" for p in params):
                kwargs["exposure"] = getattr(self, "exposure", None)
            return sch(**kwargs)
        # 极简 registry (如测试双 `def schemas(self)`) 不接受关键字 → 裸调
        return sch()
