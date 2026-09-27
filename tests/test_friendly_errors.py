"""友好错误提示测试 (qingxiaotuan/core/error_handler.py)。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qingxiaotuan.core.error_handler import friendly_error, handle_exception, FriendlyError


def test_auth_error_message():
    exc = Exception("Error code: 401 - invalid_api_key")
    fe = friendly_error(exc, {"provider": "deepseek"})
    assert fe.kind == "auth"
    assert "API Key" in fe.title
    assert "qxt login" in fe.suggestion or "qxt config" in fe.suggestion


def test_rate_limit_message():
    exc = Exception("Rate limit exceeded (429)")
    fe = friendly_error(exc, {"provider": "deepseek"})
    assert fe.kind == "rate_limit"
    assert "限流" in fe.title or "429" in fe.title


def test_timeout_message():
    exc = TimeoutError("Request timed out after 60s")
    fe = friendly_error(exc, {"provider": "deepseek"})
    assert fe.kind == "timeout"
    assert "超时" in fe.title


def test_file_not_found():
    exc = FileNotFoundError(2, "No such file", "missing.py")
    fe = friendly_error(exc)
    assert fe.kind == "not_found"
    assert "missing.py" in fe.reason


def test_permission_denied():
    exc = PermissionError(13, "Permission denied", "secret.key")
    fe = friendly_error(exc)
    assert fe.kind == "permission"
    assert "权限" in fe.title


def test_network_unreachable():
    exc = ConnectionError("getaddrinfo failed: nodename nor servname")
    fe = friendly_error(exc)
    assert fe.kind == "network"


def test_config_syntax_error():
    import yaml
    try:
        yaml.safe_load("model:\n  provider: [unclosed")
    except yaml.YAMLError as exc:
        fe = friendly_error(exc)
        assert fe.kind == "config"
        assert "config.yaml" in fe.suggestion or "qxt doctor" in fe.suggestion


def test_render_format():
    fe = FriendlyError(title="出错了", reason="r", suggestion="s")
    out = fe.render()
    assert out.startswith("❌ 出错了")
    assert "原因: r" in out
    assert "建议: s" in out


def test_verbose_includes_traceback():
    fe = friendly_error(RuntimeError("boom"))
    out = fe.render(verbose=True, tb="Traceback (most recent call last):\n  ...")
    assert "完整堆栈" in out
    assert "Traceback" in out


def test_disabled_friendly_errors_reraises():
    """ui.friendly_errors=false 时回退原始异常。"""
    exc = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        handle_exception(exc, enabled=False)


def test_enabled_returns_1(capsys):
    exc = FileNotFoundError(2, "No such file", "x.py")
    code = handle_exception(exc, enabled=True)
    assert code == 1
    err = capsys.readouterr().err
    assert "❌" in err
