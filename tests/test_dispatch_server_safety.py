"""dispatch_server 安全与韧性测试。

覆盖:
- 配对码使用 secrets（防暴力枚举）
- _audit 落盘失败写 stderr（不静默丢失安全事件）
- DispatchSession.send 异常时关闭 ws（不留僵尸连接）
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.web.dispatch_server import DispatchSession, _audit, _gen_pair_code


def test_pair_code_format():
    code = _gen_pair_code()
    assert len(code) == 6
    assert code.isdigit()


def test_pair_code_uses_secrets_not_random():
    """secrets 模块应在 dispatch_server 命名空间中（防暴力枚举）。"""
    import tuan_cli.web.dispatch_server as ds
    assert hasattr(ds, "secrets")
    # 不应再 import random 用于配对码
    import random
    # random 仍可能被间接使用（其他非安全场景），但 _gen_pair_code 不应依赖它
    with patch.object(ds.secrets, "randbelow", return_value=12345):
        assert ds._gen_pair_code() == "012345"


def test_audit_stderr_on_failure(tmp_path, capsys):
    """_audit 落盘失败时 stderr 告警，不抛异常。"""
    import tuan_cli.web.dispatch_server as ds
    # 指向一个无法创建的路径
    original = ds.AUDIT_DIR
    try:
        ds.AUDIT_DIR = Path("/dev/null/not_a_dir/cannot_create")
        # Windows 上用不存在的盘符
        if sys.platform == "win32":
            ds.AUDIT_DIR = Path("Z:\\nonexistent\\path")
        # 不应抛异常
        ds._audit({"event": "test"})
        err = capsys.readouterr().err
        assert "audit" in err.lower() or "落盘失败" in err
    finally:
        ds.AUDIT_DIR = original


def test_audit_normal_write(tmp_path, capsys):
    """正常情况下 _audit 写入文件，无 stderr 输出。"""
    import tuan_cli.web.dispatch_server as ds
    original_dir = ds.AUDIT_DIR
    original_file = ds.AUDIT_FILE
    try:
        ds.AUDIT_DIR = tmp_path
        ds.AUDIT_FILE = tmp_path / "test.jsonl"
        ds._audit({"event": "ok", "data": 123})
        err = capsys.readouterr().err
        assert "落盘失败" not in err
        assert (tmp_path / "test.jsonl").exists()
        content = (tmp_path / "test.jsonl").read_text(encoding="utf-8")
        assert '"event": "ok"' in content or '"event":"ok"' in content
    finally:
        ds.AUDIT_DIR = original_dir
        ds.AUDIT_FILE = original_file


@pytest.mark.asyncio
async def test_send_closes_ws_on_exception():
    """send 异常时应关闭 ws，不留僵尸连接。"""
    ws = AsyncMock()
    ws.send.side_effect = ConnectionError("broken pipe")
    session = DispatchSession(ws=ws, pair_code="123456", hostname="test")
    # 不应抛异常
    await session.send({"type": "test"})
    # ws.close 应被调用
    ws.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_success_no_close():
    """send 成功时不关闭连接。"""
    ws = AsyncMock()
    session = DispatchSession(ws=ws, pair_code="123456", hostname="test")
    await session.send({"type": "test"})
    ws.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_close_failure_swallowed():
    """send 失败且 close 也失败时不抛异常（双保险）。"""
    ws = AsyncMock()
    ws.send.side_effect = ConnectionError("broken")
    ws.close.side_effect = RuntimeError("already closed")
    session = DispatchSession(ws=ws, pair_code="123456", hostname="test")
    # 不应抛异常
    await session.send({"type": "test"})
