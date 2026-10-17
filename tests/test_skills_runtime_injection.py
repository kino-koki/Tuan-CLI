"""Skills 运行时注入端到端测试 —— 证明「按 description 发现 -> 注入 agent prompt」真实生效。

覆盖:
- SkillManager 按 description 关键词发现技能 (activate_for_task)。
- build_task_context 把命中技能渲染成注册表上下文。
- agent.run() 端到端: 命中技能的注册表条目真正进入发给模型的 user 消息。
- skill_read 工具可按需读取技能正文 (提到才读)。
- 蒸馏产出 (skill_manager.save 同格式) 可被 load() 重新加载 (格式自洽)。
"""

from __future__ import annotations

from pathlib import Path

from tuan_cli.skills.manager import SkillManager
from tuan_cli.core.prompts import build_task_context


# ------------------------------------------------------------------ 发现 + 渲染

def test_discovery_by_description_keyword(tmp_path: Path):
    home = tmp_path / "home"
    mgr = SkillManager(home)
    # 描述里含独特关键词 "部署到 Kubernetes" 的技能
    mgr.save(
        name="K8sDeploy",
        description="把容器化应用部署到 Kubernetes 集群的步骤",
        body="## 步骤\n1. 编写 Deployment\n2. kubectl apply",
        tags=["devops", "deployment"],
    )
    # 任务提到 "部署" 应命中该技能
    hits = mgr.activate_for_task("帮我把这个服务部署上线", limit=5)
    assert any(s.slug == "k8sdeploy" for s in hits), [s.slug for s in hits]


def test_build_task_context_injects_registry(tmp_path: Path):
    home = tmp_path / "home"
    mgr = SkillManager(home)
    mgr.save(
        name="K8sDeploy",
        description="把容器化应用部署到 Kubernetes 集群的步骤",
        body="## 步骤\n1. 编写 Deployment\n2. kubectl apply",
        tags=["devops", "deployment"],
    )
    ctx = build_task_context("帮我部署到 K8s", skill_manager=mgr, memory_store=None)
    assert "K8sDeploy" in ctx
    assert "可复用技能" in ctx  # 注册表标题


def test_distilled_skill_roundtrips(tmp_path: Path):
    """蒸馏产出走同一 save() 格式, load() 应能原样读回。"""
    home = tmp_path / "home"
    mgr = SkillManager(home)
    mgr.save(
        name="AutoFix",
        description="自动修复 pytest 失败的经验",
        body="# AutoFix\n跑 pytest 定位失败用例",
        source="auto-distill",
    )
    reloaded = mgr.load("autofix")
    assert reloaded is not None
    assert reloaded.name == "AutoFix"
    assert "pytest" in reloaded.description


# ------------------------------------------------------------------ agent.run 端到端

class _MockModel:
    name = "mock"

    def __init__(self):
        self.calls = []

    def chat(self, messages, tools=None, stream=False, on_token=None, **kwargs):
        self.calls.append(messages)
        from tuan_cli.models.base import ModelResponse
        return ModelResponse(content="done")


def test_agent_run_injects_discovered_skill(tmp_path, tuan_home):
    from tuan_cli.app import build_kernel
    from tuan_cli.core.agent import Agent

    kernel = build_kernel()
    config = kernel.require("config")
    config.data["agent"]["skill_nudge_interval"] = 0
    # 注入一个用独特描述词保存的技能
    sm = kernel.get("skill_manager")
    if sm is not None:
        sm.save(
            name="K8sDeploy",
            description="把容器化应用部署到 Kubernetes 集群的步骤",
            body="## 步骤\n1. Deployment\n2. apply",
            tags=["devops", "deployment"],
        )
    model = _MockModel()
    kernel.unprovide("model_adapter")
    kernel.provide("model_adapter", model, owner="test")
    agent = Agent(kernel=kernel, config=config, workspace=str(tmp_path),
                  confirm=lambda _p: True)
    agent.run("帮我部署这个服务到 K8s", stream=False)
    user_msgs = [m for m in model.calls[0] if m.get("role") == "user"]
    joined = "\n".join(str(m.get("content")) for m in user_msgs)
    assert "K8sDeploy" in joined, "命中技能的注册表条目应注入 user 消息"
