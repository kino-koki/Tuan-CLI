"""敏感信息脱敏与遮蔽测试: 统一 redact 原语、bus/导出/mcp 审计、config 遮蔽。"""

import json

import pytest

from qingxiaotuan.core.security_utils import (
    REDACT_TAG, is_sensitive_key, mask_sensitive_dict,
    redact_nested, redact_sensitive,
)

_SKEY = "sk-abcdefghijklmnopqrstuvwxyz012345"
_BEARER = "Bearer sk-abcdefghijklmnopqrstuvwxyz012345"


# ---------------------------------------------------------------- 原语

def test_redact_sensitive_masks_common_formats():
    assert REDACT_TAG in redact_sensitive(f"curl -H 'Authorization: {_BEARER}' http://x")
    assert REDACT_TAG in redact_sensitive(f"DEEPSEEK_API_KEY={_SKEY}")
    assert REDACT_TAG in redact_sensitive(f"apikey: {_SKEY}")
    assert REDACT_TAG in redact_sensitive(f"password={_SKEY}")


def test_redact_sensitive_does_not_touch_plain_text():
    plain = "curl -s https://example.com/api/users?page=1"
    out = redact_sensitive(plain)
    assert REDACT_TAG not in out and out == plain
    # 变量名本身 (无取值) 不误伤
    assert redact_sensitive("model.api_key_env = DEEPSEEK_API_KEY") == "model.api_key_env = DEEPSEEK_API_KEY"


def test_redact_extra_secrets_exact():
    assert redact_sensitive("my secret token is abcdefghijkl", ["abcdefghijkl"]) == \
        f"my secret token is {REDACT_TAG}"


def test_redact_nested_preserves_structure():
    data = {"a": {"secret": f"token={_SKEY}"}, "b": [f"Bearer {_SKEY}"], "n": 3, "ok": "hello"}
    out = redact_nested(data)
    assert _SKEY not in json.dumps(out)
    assert out["n"] == 3 and out["ok"] == "hello"
    assert isinstance(out["b"], list)


def test_is_sensitive_and_mask_dict():
    assert is_sensitive_key("model.api_key_env")
    assert is_sensitive_key("credentials.password")
    assert not is_sensitive_key("model.model")
    assert not is_sensitive_key("context.budget_tokens")
    masked = mask_sensitive_dict({"model": {"api_key_env": "X", "base_url": "http://x"}})
    assert masked["model"]["api_key_env"] == REDACT_TAG
    assert masked["model"]["base_url"] == "http://x"


# ---------------------------------------------------------------- bus + 导出

def test_bus_emit_redacts_payload():
    from qingxiaotuan.core.security_bus import SecurityEvent, SecurityEventBus, SecurityEventType
    bus = SecurityEventBus()
    ev = SecurityEvent(
        event_type=SecurityEventType.COMMAND_BLOCKED, timestamp=1.0,
        payload={"command": f"curl -H 'Authorization: {_BEARER}' http://x"},
        source="s", severity="high",
    )
    bus.emit(ev)
    text = json.dumps(ev.payload)
    assert _SKEY not in text and REDACT_TAG in text


def test_export_formatters_redact():
    from qingxiaotuan.core.security_bus import SecurityEvent
    from qingxiaotuan.harden import audit_export as ae
    ev = SecurityEvent(event_type="cmd.blocked", timestamp=1.0,
                       payload={"command": f"echo password={_SKEY}"},
                       source="x", severity="high")
    for fmt in ("jsonl", "cef", "syslog"):
        rendered = ae.format_event(ev, fmt)
        assert _SKEY not in rendered, fmt
        assert REDACT_TAG in rendered, fmt


def test_mcp_audit_redacts(qxt_home):
    from qingxiaotuan.tools.mcp.audit import MCPAuditStore
    store = MCPAuditStore(qxt_home / "mcp-audit.jsonl")
    store.record({"server": "s", "tool": "t", "arguments": {"key": _SKEY}})
    rows = store.read(5)
    assert rows and _SKEY not in json.dumps(rows)


# ---------------------------------------------------------------- config 遮蔽

def test_config_mask_value(qxt_home):
    from qingxiaotuan.cli.cmd_config import _mask_value
    assert _mask_value(_SKEY) != _SKEY and REDACT_TAG in _mask_value(_SKEY)
    assert _mask_value("") == ""
    assert _mask_value({"a": 1}) == REDACT_TAG