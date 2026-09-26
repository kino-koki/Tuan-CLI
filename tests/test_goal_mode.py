"""测试: Goal 模式增强引擎 (core/goal_mode.py)。

覆盖:
- set_goal 生成目标 ID + LLM 拆解为子步骤
- 步骤状态机: 验证通过则推进, 全部完成目标 done
- /goal status 展示行
- clear 清除并删除持久化文件
- 持久化: 同工作区新实例可恢复进度
- 最大自动续轮数: 持续未验证通过时超限标记 failed 并不再续轮
"""

from __future__ import annotations

import json
import os

from qingxiaotuan.core.goal_mode import (
    DEFAULT_MAX_AUTO_ITERATIONS,
    DONE,
    FAILED,
    IN_PROGRESS,
    GoalEngine,
)


class _FakeLLM:
    """脚本化 LLM: 第一次调用返回拆解 JSON, 之后按脚本回答 YES/NO。"""

    def __init__(self, decompose_steps, verdits=("YES",)):
        self.decompose = json.dumps(decompose_steps, ensure_ascii=False)
        self.verdits = list(verdits)
        self.calls: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        # 拆解请求含"任务拆解专家"
        if "任务拆解专家" in prompt:
            return self.decompose
        if self.verdits:
            return self.verdits.pop(0)
        return "NO"


def _make_engine(tmp_path, **kw) -> GoalEngine:
    return GoalEngine(str(tmp_path), **kw)


# ----------------------------------------------------------------- 设置与拆解

def test_set_goal_creates_id_and_steps(tmp_path):
    llm = _FakeLLM(["写失败测试", "修复代码", "跑通 pytest"])
    eng = _make_engine(tmp_path, llm=llm)
    state = eng.set_goal("让测试全部通过")

    assert state["description"] == "让测试全部通过"
    assert state["status"] == IN_PROGRESS
    assert len(state["goal_id"]) >= 8
    assert [s["description"] for s in state["steps"]] == ["写失败测试", "修复代码", "跑通 pytest"]
    # 第一步自动置为进行中
    assert state["steps"][0]["status"] == IN_PROGRESS
    assert state["steps"][1]["status"] == "pending"
    # 已落盘
    assert os.path.isfile(tmp_path / ".qxt" / "goal.json")


def test_set_goal_without_llm_falls_back_to_line_split(tmp_path):
    eng = _make_engine(tmp_path)
    state = eng.set_goal("第一步\n第二步;第三步")
    assert len(state["steps"]) == 3


# ----------------------------------------------------------------- 执行闭环

def test_verify_advances_steps_until_done(tmp_path):
    llm = _FakeLLM(["步骤A", "步骤B"], verdits=["YES", "YES"])
    eng = _make_engine(tmp_path, llm=llm)
    eng.set_goal("目标")

    # 第一轮: 验证步骤A 通过 -> 完成; 仍有步骤B -> 返回续轮提示
    prompt1 = eng.on_turn_complete("我做完了步骤A")
    assert prompt1 is not None and "步骤B" in prompt1
    assert eng.state["steps"][0]["status"] == DONE
    assert eng.state["steps"][1]["status"] == IN_PROGRESS

    # 第二轮: 步骤B 通过 -> 全部完成 -> 目标 done, 不再续轮
    prompt2 = eng.on_turn_complete("我做完了步骤B")
    assert prompt2 is None
    assert eng.state["status"] == DONE
    assert all(s["status"] == DONE for s in eng.state["steps"])


def test_runner_deterministic_verification_for_tests_step(tmp_path):
    runner_calls: list[str] = []

    def fake_runner(cmd: str):
        runner_calls.append(cmd)
        return (True, "all passed")

    llm = _FakeLLM(["跑通 pytest 全部测试"])
    eng = _make_engine(tmp_path, llm=llm, runner=fake_runner)
    eng.set_goal("让测试通过")

    prompt = eng.on_turn_complete("跑了测试")
    # 步骤含 pytest -> 走 runner 确定性验证, 不再调 LLM 验收
    assert runner_calls and "pytest" in runner_calls[0]
    assert prompt is None
    assert eng.state["status"] == DONE


# ----------------------------------------------------------------- 展示

def test_summary_lines_show_step_status(tmp_path):
    llm = _FakeLLM(["甲", "乙"])
    eng = _make_engine(tmp_path, llm=llm)
    eng.set_goal("某目标")
    lines = eng.summary_lines()
    text = "\n".join(lines)
    assert "某目标" in text
    assert "1." in text and "甲" in text
    assert "2." in text and "乙" in text


# ----------------------------------------------------------------- 清除与持久化

def test_clear_removes_state_and_file(tmp_path):
    llm = _FakeLLM(["a", "b"])
    eng = _make_engine(tmp_path, llm=llm)
    eng.set_goal("目标")
    assert eng.status() is not None

    eng.clear()
    assert eng.status() is None
    assert not os.path.isfile(tmp_path / ".qxt" / "goal.json")


def test_state_persists_and_recovers_in_new_engine(tmp_path):
    llm = _FakeLLM(["甲", "乙"])
    eng = _make_engine(tmp_path, llm=llm)
    eng.set_goal("持久化目标")
    # 完成第一步
    llm.verdits = ["YES"]
    eng.on_turn_complete("干完甲")

    # 新实例 (模拟新会话) 从磁盘恢复
    eng2 = GoalEngine(str(tmp_path))
    st = eng2.status()
    assert st is not None
    assert st["description"] == "持久化目标"
    assert st["steps"][0]["status"] == DONE
    assert st["steps"][1]["status"] == IN_PROGRESS
    assert eng2.max_auto_iterations == DEFAULT_MAX_AUTO_ITERATIONS


# ----------------------------------------------------------------- 最大续轮数

def test_max_auto_iterations_stops_loop_and_marks_failed(tmp_path):
    llm = _FakeLLM(["永远做不完的一步"], verdits=["NO"])
    eng = _make_engine(tmp_path, llm=llm, max_auto_iterations=3)
    eng.set_goal("死循环目标")

    p1 = eng.on_turn_complete("还没好")
    p2 = eng.on_turn_complete("还没好")
    p3 = eng.on_turn_complete("还没好")
    # 前两轮都应返回续轮提示
    assert p1 is not None and p2 is not None
    # 第 3 轮达到上限: 目标 failed, 不再续轮
    assert p3 is None
    assert eng.state["status"] == FAILED
    assert eng.state["iterations"] == 3
    # 之后再也不会续轮
    assert eng.on_turn_complete("再试") is None


def test_disabled_engine_never_continues(tmp_path):
    llm = _FakeLLM(["甲"])
    eng = _make_engine(tmp_path, llm=llm, enabled=False)
    eng.set_goal("目标")
    assert eng.on_turn_complete("任意回复") is None
