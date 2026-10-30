"""GoalMixin 单元测试 (core/agent_goal.py) —— Goal 模式的独立职责。

对标 Claude Code /goal: 设定完成条件, 循环直到满足。
覆盖: set_goal / clear_goal / _check_goal_satisfied / _handle_goal 的
主路径 + 边界 + 异常隔离。
"""
from __future__ import annotations

from tuan_cli.core.agent_goal import GoalMixin


class _Resp:
    def __init__(self, content: str):
        self.content = content


class _Model:
    """模拟模型: 返回固定文本, 记录收到的 check_messages。"""

    def __init__(self, text: str):
        self._text = text
        self.last_messages = None

    def chat(self, messages, tools=None, stream=False):
        self.last_messages = messages
        return _Resp(self._text)


class _Agent(GoalMixin):
    """最小宿主 Agent: 注入 GoalMixin 依赖的四个属性。"""

    def __init__(self, model=None):
        self._goal = None
        self._goal_check_prompt = None
        self.messages = []
        self.model = model or _Model("NO")
        self._cancel_event = None
        self._session_append = None
        self._session_events = []

    def _append(self, *a, **kw):
        self._session_events.append((a, kw))


# ---------------------------------------------------------------- set_goal / clear_goal

def test_set_goal_uses_default_template():
    ag = _Agent()
    ag.set_goal("all tests pass")
    assert ag._goal == "all tests pass"
    assert ag._goal_check_prompt is not None
    assert "all tests pass" in ag._goal_check_prompt
    assert "YES" in ag._goal_check_prompt  # 内置模板含 YES/NO 判定指令


def test_set_goal_custom_check_prompt_used():
    ag = _Agent()
    ag.set_goal("fix lint", check_prompt="CUSTOM: is it done?")
    assert ag._goal_check_prompt == "CUSTOM: is it done?"


def test_clear_goal_resets():
    ag = _Agent()
    ag.set_goal("goal")
    ag.clear_goal()
    assert ag._goal is None
    assert ag._goal_check_prompt is None


# ---------------------------------------------------------------- _check_goal_satisfied

def test_check_yes_returns_true():
    ag = _Agent(_Model("YES"))
    ag.set_goal("g")
    assert ag._check_goal_satisfied("response") is True


def test_check_no_returns_false():
    ag = _Agent(_Model("NO, more work needed"))
    ag.set_goal("g")
    assert ag._check_goal_satisfied("response") is False


def test_check_dict_result_content():
    ag = _Agent(_Model("YES"))
    ag.set_goal("g")
    # 模型返回 dict 形态 (与部分适配器一致)
    ag.model = _DictModel({"message": {"content": "YES"}})
    assert ag._check_goal_satisfied("response") is True


def test_check_str_result():
    ag = _Agent(_Model("yes"))  # 小写也接受 (startswith 前 upper)
    ag.set_goal("g")
    ag.model = _StrModel("yes")
    assert ag._check_goal_satisfied("response") is True


def test_check_without_goal_returns_false():
    ag = _Agent(_Model("YES"))
    # 未 set_goal
    assert ag._check_goal_satisfied("response") is False


def test_check_model_exception_isolated():
    ag = _Agent(_Model("YES"))
    ag.set_goal("g")

    class Boom(Exception):
        pass

    def _boom(*a, **kw):
        raise Boom("model down")

    ag.model.chat = _boom
    # 异常必须被隔离为未满足, 不向外抛
    assert ag._check_goal_satisfied("response") is False


def test_check_prompt_contains_latest_response():
    ag = _Agent(_Model("YES"))
    ag.set_goal("g")
    ag._check_goal_satisfied("the-latest-agent-answer")
    # 校验 check_messages 里确实把最新响应喂给了模型
    last = ag.model.last_messages
    assert last is not None
    assert "the-latest-agent-answer" in last[-1]["content"]


# ---------------------------------------------------------------- _handle_goal

def test_handle_goal_achieved_notifies_and_clears():
    ag = _Agent(_Model("YES"))
    ag.set_goal("g")
    ag._session_append = ag._append
    raw = []
    ag._handle_goal("final answer", iteration=1, max_iter=5, raw_on_token=raw.append)
    assert ag._goal is None                      # 达成后清除
    assert ag._goal_check_prompt is None
    assert raw and "达成" in raw[0]              # 通知用户
    assert ag._session_events                    # 写入 session 事件
    assert ag._session_events[-1][0][0] == "goal.achieved"


def test_handle_goal_not_achieved_injects_continue():
    ag = _Agent(_Model("NO"))
    ag.set_goal("g")
    ag._session_append = ag._append
    ag.messages = []
    ag._handle_goal("partial", iteration=2, max_iter=10, raw_on_token=None)
    # 未达成且还有轮次 → 注入继续提示
    assert ag._goal == "g"
    assert ag.messages and "继续" in ag.messages[-1]["content"]
    assert ag._session_events[-1][0][0] == "goal.continue"


def test_handle_goal_not_achieved_no_continue_at_max():
    ag = _Agent(_Model("NO"))
    ag.set_goal("g")
    ag._session_append = ag._append
    ag.messages = []
    ag._handle_goal("partial", iteration=10, max_iter=10, raw_on_token=None)
    # 已达上限 → 不再注入继续 (由上层决定放弃)
    assert ag.messages == []


def test_handle_goal_model_error_returns_early():
    ag = _Agent(_Model("NO"))
    ag.set_goal("g")
    ag._session_append = ag._append
    ag.messages = []
    ag._handle_goal("[模型错误] upstream", iteration=1, max_iter=5, raw_on_token=None)
    # 模型错误 → 不判定也不注入
    assert ag._goal == "g"
    assert ag.messages == []


def test_handle_goal_cancelled_returns_early():
    ag = _Agent(_Model("YES"))
    ag.set_goal("g")
    ag._session_append = ag._append
    ag.messages = []

    class _Cancelled:
        def is_set(self):
            return True

    ag._cancel_event = _Cancelled()
    ag._handle_goal("answer", iteration=1, max_iter=5, raw_on_token=None)
    # 取消 → 即使模型回 YES 也不判定不清除
    assert ag._goal == "g"


def test_handle_goal_without_goal_is_noop():
    ag = _Agent(_Model("YES"))
    ag._session_append = ag._append
    ag.messages = []
    ag._handle_goal("x", iteration=1, max_iter=5, raw_on_token=None)
    assert ag.messages == []  # 无 goal → 什么都不做


# ---------------------------------------------------------------- 辅助 stub

class _DictModel:
    def __init__(self, payload):
        self._payload = payload
        self.last_messages = None

    def chat(self, messages, tools=None, stream=False):
        self.last_messages = messages
        return self._payload


class _StrModel:
    def __init__(self, text):
        self._text = text
        self.last_messages = None

    def chat(self, messages, tools=None, stream=False):
        self.last_messages = messages
        return self._text
