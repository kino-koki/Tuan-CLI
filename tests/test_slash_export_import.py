# -*- coding: utf-8 -*-
"""/export 和 /import 斜杠命令测试。"""
import os

import pytest


@pytest.fixture()
def qxt_home(tmp_path, monkeypatch):
    monkeypatch.setenv("QXT_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture()
def agent(tmp_path, qxt_home):
    """创建一个最小 agent 用于测试。"""
    from qingxiaotuan.config import Config
    from qingxiaotuan.core.kernel import Kernel

    config = Config()
    kernel = Kernel()

    class _Agent:
        def __init__(self):
            self.messages = []
            self.kernel = kernel
            self.config = config
            self.workspace = str(tmp_path)
            self.plan_mode = False
            self.yolo = False
            self.turn_count = 0
            self.total_usage = {}
            self.pending_images = []

            class Ctx:
                workspace = str(tmp_path)
                plan_mode = False
                yolo = False
                confirm = None
                hooks = None
            self.ctx = Ctx()

        def context_stats(self):
            return {"estimated_tokens": 0, "budget_tokens": 128000}

        def compact(self):
            return 0

        def run(self, prompt, stream=False, **kw):
            return "test response"

    return _Agent()


def test_export_creates_markdown_file(agent, tmp_path, monkeypatch):
    """测试 /export 创建 Markdown 文件。"""
    agent.messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    monkeypatch.chdir(tmp_path)

    from qingxiaotuan.cli.cmd_slash import _cmd_export
    _cmd_export(agent, "")

    # 检查创建了文件
    files = list(tmp_path.glob("chat_*.md"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert "## 你" in content
    assert "## 青小团" in content
    assert "Hello" in content
    assert "Hi there!" in content


def test_export_with_custom_filename(agent, tmp_path, monkeypatch):
    """测试 /export 带自定义文件名。"""
    agent.messages = [{"role": "user", "content": "test"}]
    monkeypatch.chdir(tmp_path)

    filepath = str(tmp_path / "my_chat.md")
    from qingxiaotuan.cli.cmd_slash import _cmd_export
    _cmd_export(agent, filepath)

    assert os.path.exists(filepath)
    content = open(filepath, encoding="utf-8").read()
    assert "test" in content


def test_export_empty_session(agent):
    """测试空会话导出。"""
    agent.messages = []

    from qingxiaotuan.cli.cmd_slash import _cmd_export
    _cmd_export(agent, "")

    # 空会话应该不创建文件
    assert len(agent.messages) == 0


def test_import_valid_markdown(agent, tmp_path):
    """测试 /import 导入有效 Markdown。"""
    md_content = """# Test

## 你

Hello from import

## 青小团

Response from import
"""
    filepath = tmp_path / "test_import.md"
    filepath.write_text(md_content, encoding="utf-8")

    from qingxiaotuan.cli.cmd_slash import _cmd_import
    _cmd_import(agent, str(filepath))

    assert len(agent.messages) == 2
    assert agent.messages[0]["role"] == "user"
    assert agent.messages[0]["content"] == "Hello from import"
    assert agent.messages[1]["role"] == "assistant"
    assert agent.messages[1]["content"] == "Response from import"


def test_import_missing_file(agent):
    """测试 /import 不存在的文件。"""
    from qingxiaotuan.cli.cmd_slash import _cmd_import
    _cmd_import(agent, "/nonexistent/path.md")

    # 不存在的文件不应该添加消息
    assert len(agent.messages) == 0


def test_import_empty_arg(agent):
    """测试 /import 无参数。"""
    from qingxiaotuan.cli.cmd_slash import _cmd_import
    _cmd_import(agent, "")

    # 无参数不应该添加消息
    assert len(agent.messages) == 0


def test_import_invalid_format(agent, tmp_path):
    """测试 /import 无效格式的 Markdown。"""
    filepath = tmp_path / "bad.md"
    filepath.write_text("# Just a heading\n\nSome text\n", encoding="utf-8")

    from qingxiaotuan.cli.cmd_slash import _cmd_import
    _cmd_import(agent, str(filepath))

    # 无效格式不会添加消息
    assert len(agent.messages) == 0
