"""C-2 五类错误 + 固定模板单测 (tuan_cli/core/errors.py)。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.core import errors


def test_five_error_classes():
    """五类异常都存在且可抛出。"""
    for cls in (errors.ProviderError, errors.AuthError, errors.NetworkError,
                errors.ConfigError, errors.ModelError):
        e = cls("boom")
        assert isinstance(e, errors.TuanCliError)
        assert e.kind


def test_auth_template_exact_wording():
    """C-2.3 契约逐字文案。"""
    tmpl = errors.template_for("auth")
    assert "您的 API Key 可能已过期或无效。请运行 tuan setup 重新配置。" in tmpl.suggestion


def test_network_template_exact_wording():
    """C-2.4 契约逐字文案。"""
    tmpl = errors.template_for("network")
    assert "无法连接到模型服务。请检查网络连接，" in tmpl.suggestion
    assert "tuan models local" in tmpl.suggestion


def test_model_template_exact_wording_with_model():
    """C-2.5 契约逐字文案, 模型名填充。"""
    tmpl = errors.template_for("model", model="gpt-nonexist")
    assert "模型 gpt-nonexist 不存在。运行 tuan models 查看可用模型列表。" in tmpl.suggestion
    assert "gpt-nonexist" in tmpl.title


def test_render_format():
    tmpl = errors.template_for("auth")
    out = tmpl.render(detail="401 unauthorized")
    assert out.startswith("❌ ")
    assert "原因:" in out
    assert "建议:" in out
    assert "401 unauthorized" in out


def test_friendly_for_business_exc():
    exc = errors.ModelError("gpt-xyz")
    tmpl = errors.friendly_for(exc)
    assert tmpl is not None
    assert tmpl.kind == "model"


def test_friendly_for_plain_exception_none():
    assert errors.friendly_for(RuntimeError("x")) is None
