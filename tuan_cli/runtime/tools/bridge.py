"""bridge.py —— 把现有 Python 青小团工具系统接入 kernel 子树。

1. ``wrap_existing_tool``：把 ``tuan_cli.tools.base.Tool`` 适配成 kernel 的
   ``ExecutableTool``（handler 调用 + 按 dangerous/read_only 推导 approval_rule 与 accesses）。
2. ``KernelToolExecutorAdapter``：把现有 ``core/tool_executor.ToolExecutor`` 包装成
   kernel 风格的异步生成器 ``execute``，让既有引擎（只读并行 + 写串行）在 kernel 层可用。

为避免在 ``import tuan_cli.runtime.tools`` 时连带拉起全部内置工具插件，
对 ``tuan_cli.tools.base`` 与 ``core.tool_executor`` 采用惰性导入。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Callable, List, Optional

from .contract import (
    ExecutableToolContext,
    ExecutableToolResult,
    RunnableToolExecution,
    ToolAccesses,
)
from .executor import ToolExecutionResult

logger = logging.getLogger(__name__)


def wrap_existing_tool(
    tool: Any,
    *,
    workspace: str = ".",
    source: str = "builtin",
) -> "_WrappedTool":
    """把 ``tuan_cli.tools.base.Tool`` 适配成 kernel ``ExecutableTool``。

    推导规则：
    - read_only=True  -> approval_rule="read",  accesses=none()（可并行）
    - dangerous=True  -> approval_rule="dangerous", accesses=all()（保守串行）
    - 其它            -> approval_rule="default",  accesses=all()
    """
    return _WrappedTool(tool, workspace=workspace, source=source)


class _WrappedTool:
    """``tools.base.Tool`` 的 kernel``ExecutableTool`` 包装。"""

    def __init__(self, tool: Any, *, workspace: str, source: str) -> None:
        self._tool = tool
        self._workspace = workspace
        self._source = source

    # ---- ExecutableTool 接口字段 ----
    @property
    def name(self) -> str:
        return self._tool.name  # type: ignore[no-any-return]  # 包装对象为 Any

    @property
    def description(self) -> str:
        return self._tool.description  # type: ignore[no-any-return]  # 包装对象为 Any

    @property
    def parameters(self) -> Any:
        return self._tool.parameters

    @property
    def source(self) -> str:
        return self._source

    # ---- 资源访问推导 ----
    def _approval_rule(self) -> str:
        if getattr(self._tool, "read_only", False):
            return "read"
        if getattr(self._tool, "dangerous", False):
            return "dangerous"
        return "default"

    def _accesses(self) -> ToolAccesses:
        if getattr(self._tool, "read_only", False):
            return ToolAccesses.none()
        return ToolAccesses.all()

    # ---- resolve_execution ----
    def resolve_execution(self, input: Any) -> RunnableToolExecution:
        args = input if isinstance(input, dict) else {}

        async def execute(ctx: ExecutableToolContext) -> ExecutableToolResult:
            return await _run_base_handler(self._tool, args, self._workspace)

        return RunnableToolExecution(
            approval_rule=self._approval_rule(),
            execute=execute,
            accesses=self._accesses(),
        )


async def _run_base_handler(
    tool: Any, args: dict, workspace: str, *,
    tool_schema: Optional[dict] = None, hooks: Any = None,
) -> ExecutableToolResult:
    # 惰性导入：避免 import 期拉起全部工具插件
    from tuan_cli.tools.base import ToolContext
    from tuan_cli.hooks.input_validation import validate_updated_input

    # B3 续轮 XII（实测复现的真实缺口）：这条生产旁路此前**直接**
    # ``handler(ctx, **args)``，既没有 run_pre 也没有 updatedInput 的
    # schema 白名单 —— 外部 Agent 多给一个未知键就抛 TypeError，缺
    # required / 类型不符也无人校验。主链路 tools/base.py 早就修好了，
    # 这里漏了。现在按同一份 input_validation 真值裁决：
    #   deny -> 结构化拒绝调用；sanitized -> 丢未知键后执行。
    # 如实：无 schema 时 validate_updated_input 走保守子集并标
    # enforced=False，不把「没校验过」包装成「已通过校验」。
    schema = getattr(tool, "parameters", None)
    name = str(getattr(tool, "name", "") or "")
    raw = args if isinstance(args, dict) else {}
    verdict = validate_updated_input(raw, raw, schema, tool_name=name)
    if verdict.deny:
        return ExecutableToolResult(
            output=f"Tool {name} 参数校验拒绝: {verdict.reason}",
            is_error=True)
    eff = verdict.sanitized

    # B3: 桥接层接入 PreToolUse hook 改参校验。无 schema 时退化为保守子集
    # (enforced=False)，不声称通过校验；有 schema 时严格校验，deny → 不执行。
    if hooks is not None:
        try:
            d = hooks.run_pre(tool.name, args,
                              tool_schema=tool_schema or getattr(tool, "parameters", None))
        except TypeError:
            d = hooks.run_pre(tool.name, args)  # 老式 mock 无 tool_schema
        except Exception:
            d = None
        if getattr(d, "block", False):
            return ExecutableToolResult(
                output=f"Tool {tool.name} blocked by hook: {getattr(d, 'reason', '')}",
                is_error=True,
            )
        new_args = getattr(d, "args", None)
        if isinstance(new_args, dict) and new_args:
            try:
                from tuan_cli.hooks.input_validation import validate_updated_input
                v = validate_updated_input(
                    new_args, args, tool_schema or getattr(tool, "parameters", None),
                    tool_name=tool.name)
                if v.deny:
                    return ExecutableToolResult(
                        output=f"Tool {tool.name} hook 改参未通过校验: {v.reason}",
                        is_error=True,
                    )
                if v.enforced:
                    args = v.sanitized  # 严格校验通过的替换语义
                # 无 schema 保守子集 (enforced=False): 只挡未知键，不声称通过校验
            except Exception as exc:  # noqa: BLE001 - hook 改参失败不阻断调用
                logger.warning("Tool %s pre-execution hook error (ignored): %s",
                               tool.name, exc)

    # B3: 按 schema 过滤未知键（防止 hook 或上游注入额外参数）
    schema = tool_schema or getattr(tool, "parameters", None)
    if isinstance(schema, dict) and isinstance(args, dict):
        props = schema.get("properties", {})
        if props:
            required = set(schema.get("required", []))
            filtered = {k: v for k, v in args.items() if k in props}
            # 检查 required 字段
            missing = required - set(filtered.keys())
            if missing:
                return ExecutableToolResult(
                    output=f"Tool {tool.name} missing required: {sorted(missing)}",
                    is_error=True,
                )
            # 检查类型（简单 str/number/boolean/int）
            _TYPE_MAP = {"string": str, "number": (int, float), "integer": int, "boolean": bool}
            for k, v in filtered.items():
                expected = props.get(k, {}).get("type")
                py_type = _TYPE_MAP.get(expected)
                if py_type and not isinstance(v, py_type):
                    return ExecutableToolResult(
                        output=f"Tool {tool.name} param {k} type error: expected {expected}, got {type(v).__name__}",
                        is_error=True,
                    )
            args = filtered

    base_ctx = ToolContext(kernel=None, workspace=workspace)
    try:
        out = tool.handler(base_ctx, **eff)
        if asyncio.iscoroutine(out):
            out = await out
    except Exception as exc:  # noqa: BLE001
        return ExecutableToolResult(
            output=f"Tool {tool.name} failed: {type(exc).__name__}: {exc}", is_error=True
        )
    return ExecutableToolResult(output=str(out), is_error=False)


# ----------------------------------------------------- 适配现有 core 执行器


class KernelToolExecutorAdapter:
    """把 ``core/tool_executor.ToolExecutor`` 包装成 kernel 风格的异步生成器。

    既有的「只读并行 + 写串行 + 超时」批处理策略原样复用，仅做调用契约转换：
    kernel ``ToolCall`` -> 既有 dict 形式 -> core.execute_batch -> 结果回读为
    ``ToolExecutionResult``。
    """

    def __init__(self, core_executor: Any, registry: Any = None) -> None:
        # 惰性导入，仅在使用时校验类型
        from tuan_cli.core.tool_executor import ToolExecutor as CoreToolExecutor

        if not isinstance(core_executor, CoreToolExecutor):
            raise TypeError("core_executor 必须是 tuan_cli.core.tool_executor.ToolExecutor")
        self._core = core_executor
        self._registry = registry

    async def execute(
        self,
        calls: List[Any],
        *,
        signal: Any = None,
        turn_id: int = 0,
        trace: Any = None,
        on_tool_call: Optional[Callable[[dict], None]] = None,
    ) -> AsyncIterator[ToolExecutionResult]:
        from tuan_cli.tools.base import ToolContext

        messages: List[dict] = []
        core_calls = [
            {"id": c.id, "function": {"name": c.name, "arguments": c.arguments}} for c in calls
        ]
        ctx = ToolContext(kernel=None, workspace=".")

        def _on_tool(name: str, args: str) -> None:
            if on_tool_call is not None:
                on_tool_call({"tool_call_id": "", "name": name, "args": args})

        saved = self._core.messages
        self._core.messages = messages
        try:
            await asyncio.to_thread(
                self._core.execute_batch, core_calls, ctx, None, _on_tool, None
            )
        finally:
            self._core.messages = saved

        for m in messages:
            if m.get("role") != "tool":
                continue
            yield ToolExecutionResult(
                tool_call_id=m.get("tool_call_id", ""),
                tool_name=m.get("name", ""),
                result=ExecutableToolResult(
                    output=m.get("content", ""),
                    is_error=(m.get("status") != "ok"),
                ),
            )


__all__ = ["wrap_existing_tool", "KernelToolExecutorAdapter"]
