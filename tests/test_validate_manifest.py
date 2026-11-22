"""validate.py 的 MANIFEST 引用完整性检查测试。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(r"G:\Tuan-CLI-Official")
_shared_scripts = ROOT / "_shared" / "scripts"
if _shared_scripts.is_dir():
    sys.path.insert(0, str(_shared_scripts))

try:
    import validate  # noqa: E402
except ModuleNotFoundError:  # pragma: no cover - 外部工作区不存在时整体跳过
    pytest.skip("外部工作区 G:\\Tuan-CLI-Official 不存在, 跳过 validate 测试",
                allow_module_level=True)


def test_manifest_references_ok() -> None:
    """真实 MANIFEST.json: 无重复且全部引用真实存在。"""
    ok, errors = validate.check_manifest_references()
    assert ok is True, f"errors={errors}"
    assert errors == []


def test_detects_duplicate(tmp_path, monkeypatch) -> None:
    """重复引用被检出。"""
    root = tmp_path
    (root / "skills" / "a").mkdir(parents=True)
    (root / "skills" / "a" / "SKILL.md").write_text("---\nname: a\ndescription: x\n---\n", encoding="utf-8")
    (root / "plugins" / "p").mkdir(parents=True)
    (root / "plugins" / "p" / "plugin.json").write_text('{"name":"p"}', encoding="utf-8")
    (root / "mcp" / "m").mkdir(parents=True)
    (root / "mcp" / "m" / "mcp.json").write_text('{"name":"m"}', encoding="utf-8")
    manifest = {
        "contents": {
            "skills": ["a", "a"],
            "plugins": ["p", "p"],
            "mcp_servers": ["m", "m"],
        }
    }
    (root / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(validate, "ROOT", root)
    ok, errors = validate.check_manifest_references()
    assert ok is False
    assert any("重复" in e for e in errors)
    assert sum("重复" in e for e in errors) == 3


def test_detects_missing(tmp_path, monkeypatch) -> None:
    """缺失引用被检出。"""
    root = tmp_path
    (root / "skills").mkdir(parents=True)
    (root / "plugins").mkdir()
    (root / "mcp").mkdir()
    manifest = {
        "contents": {
            "skills": ["missing-skill"],
            "plugins": ["missing-plugin"],
            "mcp_servers": ["missing-mcp"],
        }
    }
    (root / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(validate, "ROOT", root)
    ok, errors = validate.check_manifest_references()
    assert ok is False
    assert sum("缺失" in e for e in errors) == 3
