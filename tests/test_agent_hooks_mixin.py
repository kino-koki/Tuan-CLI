"""HooksMixin 单元测试 (core/agent_hooks.py) —— 用户级 Hooks 分发 + Auto Memory。

承载三类生命周期副作用, 全部异常隔离、绝不阻断主循环:
- _notify_hook: 通知类 hook (Stop/SubagentStop/PreCompact);
- _run_prompt_submit_hooks: UserPromptSubmit hook 注入附加上下文;
- _auto_memory_extract: Auto Memory 后台抽取 (不调额外 LLM)。
"""
from __future__ import annotations

from unittest import mock

from tuan_cli.core.agent_hooks import HooksMixin


class _Ctx:
    def __init__(self, hooks=None):
        self.hooks = hooks


class _Hooks:
    """模拟 HookManager: 记录 enabled/run 调用。"""

    def __init__(self, enabled_events=(), notify_result=None, prompt_result=""):
        self._enabled_events = set(enabled_events)
        self._notify_result = notify_result
        self._prompt_result = prompt_result
        self.calls = []

    def enabled_for(self, event):
        return event in self._enabled_events

    def run_notify(self, event, payload):
        self.calls.append(("notify", event, payload))
        if self._notify_result:
            raise self._notify_result

    def run_user_prompt_submit(self, prompt):
        self.calls.append(("prompt", prompt))
        return self._prompt_result


class _Agent(HooksMixin):
    def __init__(self, hooks=None, kernel=None, last_user_input=""):
        self.ctx = _Ctx(hooks)
        self.kernel = kernel or _Kernel()
        self._last_user_input = last_user_input


class _Kernel:
    """模拟 kernel (含 get + 事件总线)。"""

    def __init__(self, extractor=None):
        self._extractor = extractor
        self.events = []

    def get(self, name):
        return self._extractor if name == "auto_extractor" else None

    def emit(self, event, payload=None):
        self.events.append((event, payload))


class _Extractor:
    """模拟 Auto 抽取器。"""

    def __init__(self):
        self.turns = []

    def process_turn_async(self, user_text, answer, kernel=None):
        self.turns.append((user_text, answer, kernel))


# ---------------------------------------------------------------- _hooks 获取

def test_hooks_returns_ctx_hooks():
    h = _Hooks()
    ag = _Agent(hooks=h)
    assert ag._hooks() is h


def test_hooks_returns_none_when_no_ctx():
    ag = _Agent()
    ag.ctx = None
    assert ag._hooks() is None


def test_hooks_returns_none_when_ctx_has_no_hooks():
    ag = _Agent(hooks=None)
    assert ag._hooks() is None


# ---------------------------------------------------------------- _notify_hook

def test_notify_hook_dispatches_when_enabled():
    h = _Hooks(enabled_events=("Stop",))
    ag = _Agent(hooks=h)
    ag._notify_hook("Stop", {"reason": "user"})
    assert h.calls == [("notify", "Stop", {"reason": "user"})]


def test_notify_hook_skips_when_disabled():
    h = _Hooks(enabled_events=())
    ag = _Agent(hooks=h)
    ag._notify_hook("Stop", {})
    assert h.calls == []  # 未启用 → 不调用 run_notify


def test_notify_hook_skips_when_no_hooks():
    ag = _Agent(hooks=None)
    # 无 hooks → 静默返回, 不抛
    ag._notify_hook("Stop", {})


def test_notify_hook_exception_isolated():
    h = _Hooks(enabled_events=("Stop",), notify_result=RuntimeError("boom"))
    ag = _Agent(hooks=h)
    # 异常隔离: 不向外抛
    ag._notify_hook("Stop", {})


# ---------------------------------------------------------------- _run_prompt_submit_hooks

def test_prompt_submit_returns_injected_context():
    h = _Hooks(enabled_events=("UserPromptSubmit",), prompt_result="附加上下文")
    ag = _Agent(hooks=h)
    assert ag._run_prompt_submit_hooks("原提示") == "附加上下文"
    assert h.calls == [("prompt", "原提示")]


def test_prompt_submit_returns_empty_when_disabled():
    h = _Hooks(enabled_events=(), prompt_result="不应返回")
    ag = _Agent(hooks=h)
    assert ag._run_prompt_submit_hooks("p") == ""


def test_prompt_submit_returns_empty_when_no_hooks():
    ag = _Agent(hooks=None)
    assert ag._run_prompt_submit_hooks("p") == ""


def test_prompt_submit_exception_isolated():
    h = _Hooks(enabled_events=("UserPromptSubmit",))
    h.run_user_prompt_submit = mock.Mock(side_effect=RuntimeError("boom"))
    ag = _Agent(hooks=h)
    assert ag._run_prompt_submit_hooks("p") == ""


# ---------------------------------------------------------------- _auto_memory_extract

def test_auto_memory_extract_with_user_input(monkeypatch):
    extractor = _Extractor()
    ag = _Agent(kernel=_Kernel(extractor=extractor), last_user_input="我喜欢 TypeScript")

    # 让 build_extractor 返回我们的 stub
    import tuan_cli.memory.auto_extractor as ae
    monkeypatch.setattr(ae, "build_extractor", lambda kernel: extractor)

    ag._auto_memory_extract(answer="好的")
    assert extractor.turns == [("我喜欢 TypeScript", "好的", ag.kernel)]


def test_auto_memory_extract_skips_empty_input():
    ag = _Agent(kernel=_Kernel(), last_user_input="")
    ag._auto_memory_extract(answer="x")  # 空输入 → 静默返回


def test_auto_memory_extract_build_extractor_none():
    import tuan_cli.memory.auto_extractor as ae
    ag = _Agent(kernel=_Kernel(), last_user_input="有内容")
    monkeypatch = _Patch(ae, "build_extractor", lambda kernel: None)
    ag._auto_memory_extract(answer="x")  # None → 静默返回
    monkeypatch.undo()


def test_auto_memory_extract_exception_isolated():
    ag = _Agent(kernel=_Kernel(), last_user_input="有内容")
    import tuan_cli.memory.auto_extractor as ae
    monkeypatch = _Patch(ae, "build_extractor",
                         lambda kernel: (_ for _ in ()).throw(RuntimeError("boom")))
    ag._auto_memory_extract(answer="x")  # 异常隔离
    monkeypatch.undo()


def test_auto_memory_extract_process_turn_async_exception_isolated():
    class _BoomExtractor:
        def process_turn_async(self, *a, **kw):
            raise RuntimeError("boom")

    ag = _Agent(kernel=_Kernel(), last_user_input="有内容")
    import tuan_cli.memory.auto_extractor as ae
    monkeypatch = _Patch(ae, "build_extractor", lambda kernel: _BoomExtractor())
    ag._auto_memory_extract(answer="x")  # 抽取过程异常也隔离
    monkeypatch.undo()


# ---------------------------------------------------------------- 辅助 stub

class _Patch:
    """极简 monkeypatch (避免 fixture 依赖, 支持手动 undo)。"""

    def __init__(self, obj, name, value):
        self._obj = obj
        self._name = name
        self._orig = getattr(obj, name)
        setattr(obj, name, value)

    def undo(self):
        setattr(self._obj, self._name, self._orig)
