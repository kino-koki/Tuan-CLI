"""PathSafety 单元测试 —— 防目录遍历 / 敏感路径 / 工作区越界 / 系统目录写入。

覆盖 `core/path_safety.py` 全部公共 API 与关键分支:
- validate_path: 遍历攻击 / 保留设备名 / 敏感路径 / 工作区边界 / 系统目录 / 合法路径
- is_sensitive / safe_join / find_project_root
- 模块级 get_path_safety / validate_path
- PathViolation 数据类语义
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tuan_cli.core.path_safety import (
    PathSafety,
    PathViolation,
    get_path_safety,
    validate_path,
)


# ------------------------------------------------------------------ PathViolation

def test_path_violation_defaults_safe():
    v = PathViolation()
    assert v.safe is True
    assert v.denied is False
    assert bool(v) is True
    assert v.reason == ""
    assert v.risk_level == "none"
    assert v.violations == []


def test_path_violation_denied_bool_false():
    v = PathViolation(safe=False, denied=True, reason="blocked")
    assert bool(v) is False


# ------------------------------------------------------------------ validate_path 合法路径

def test_validate_relative_path_within_workspace(tmp_path):
    s = PathSafety(workspace=str(tmp_path))
    r = s.validate_path("src/main.py", action="read")
    assert r.safe and not r.denied
    assert r.original_path == "src/main.py"


def test_validate_absolute_path_within_workspace(tmp_path):
    s = PathSafety(workspace=str(tmp_path))
    target = tmp_path / "a.txt"
    target.write_text("x", encoding="utf-8")
    r = s.validate_path(str(target), action="read")
    assert r.safe and not r.denied


def test_validate_write_within_workspace(tmp_path):
    s = PathSafety(workspace=str(tmp_path))
    r = s.validate_path("sub/out.py", action="write")
    assert r.safe and not r.denied


def test_validate_execute_within_workspace(tmp_path):
    s = PathSafety(workspace=str(tmp_path))
    r = s.validate_path("scripts/run.sh", action="execute")
    assert r.safe and not r.denied


# ------------------------------------------------------------------ 遍历攻击

@pytest.mark.parametrize("attack", [
    "../etc/passwd",
    "..\\etc\\passwd",
    "a/../../b",
    "%2e%2e/etc/passwd",
    "%252e%252e/etc/passwd",
    "..%af/etc/passwd",
    "..%c0%af/etc/passwd",
    "..%c1%9c/etc/passwd",
])
def test_validate_traversal_denied(tmp_path, attack):
    s = PathSafety(workspace=str(tmp_path))
    r = s.validate_path(attack, action="read")
    assert r.denied is True
    assert r.safe is False
    assert r.risk_level == "critical"
    assert "traversal_attack" in r.violations


# ------------------------------------------------------------------ 保留设备名

@pytest.mark.parametrize("name", [
    "CON", "con.txt", "PRN", "AUX", "NUL", "NUL.log",
    "COM1", "COM9", "LPT1", "LPT9",
])
def test_validate_reserved_device_denied(tmp_path, name):
    s = PathSafety(workspace=str(tmp_path))
    r = s.validate_path(name, action="write")
    assert r.denied is True
    assert r.risk_level == "high"
    assert "reserved_device_name" in r.violations


# ------------------------------------------------------------------ 敏感路径

def test_validate_env_file_denied(tmp_path):
    s = PathSafety(workspace=str(tmp_path))
    r = s.validate_path(".env", action="read")
    assert r.denied is True
    assert r.risk_level == "critical"
    assert "sensitive_path" in r.violations


def test_validate_ssh_dir_denied(tmp_path):
    s = PathSafety(workspace=str(tmp_path))
    r = s.validate_path(".ssh/id_rsa", action="read")
    assert r.denied is True
    assert "sensitive_path" in r.violations


def test_validate_env_variant_denied(tmp_path):
    s = PathSafety(workspace=str(tmp_path))
    assert s.validate_path(".env.production", action="read").denied is True


def test_validate_passwd_denied(tmp_path):
    s = PathSafety(workspace=str(tmp_path))
    assert s.validate_path("shadow", action="read").denied is True


def test_extra_sensitive_pattern(tmp_path):
    s = PathSafety(workspace=str(tmp_path),
                   extra_sensitive_patterns=[r"secret\.(txt|json)"])
    assert s.validate_path("secret.json", action="read").denied is True
    assert s.validate_path("public.json", action="read").safe is True


def test_extra_sensitive_invalid_pattern_ignored(tmp_path):
    # 非法正则被忽略, 不抛异常
    s = PathSafety(workspace=str(tmp_path), extra_sensitive_patterns=["["])
    assert s.validate_path("a.txt", action="read").safe is True


# ------------------------------------------------------------------ 工作区边界

def test_validate_write_escapes_boundary_denied(tmp_path, monkeypatch):
    s = PathSafety(workspace=str(tmp_path))
    outside = Path(tmp_path).parent / "outside.txt"
    r = s.validate_path(str(outside), action="write")
    assert r.denied is True
    assert r.risk_level == "high"
    assert "boundary_escape" in r.violations


def test_validate_read_outside_boundary_allowed(tmp_path):
    """读操作默认不做边界检查 (只对写/执行), 越界读是允许的。"""
    s = PathSafety(workspace=str(tmp_path))
    outside = Path(tmp_path).parent / "outside.txt"
    r = s.validate_path(str(outside), action="read")
    assert r.safe is True  # 读不做边界约束


def test_validate_execute_outside_boundary_denied(tmp_path):
    s = PathSafety(workspace=str(tmp_path))
    outside = Path(tmp_path).parent / "run.sh"
    r = s.validate_path(str(outside), action="execute")
    assert r.denied is True


# ------------------------------------------------------------------ 系统目录写入

def test_validate_write_etc_denied():
    # /etc 仅 POSIX 有效; Windows 上 resolve() 会盘符化为 E:\etc\...
    if os.name != "posix":
        pytest.skip("POSIX 系统目录")
    # workspace="" → _check_boundary 跳过，单独触发 _check_system_dirs
    s = PathSafety(workspace="")
    r = s.validate_path("/etc/apt.conf", action="write")
    assert r.denied is True
    assert r.risk_level == "critical"
    assert "system_dir_write" in r.violations


def test_validate_write_windows_system_denied():
    # C:\Windows 仅 Windows 有效
    if os.name != "nt":
        pytest.skip("Windows 系统目录")
    s = PathSafety(workspace="")
    r = s.validate_path("C:\\Windows\\System32\\x.dll", action="write")
    assert r.denied is True
    assert r.risk_level == "critical"
    assert "system_dir_write" in r.violations


# ------------------------------------------------------------------ is_sensitive

def test_is_sensitive_true_false(tmp_path):
    s = PathSafety(workspace=str(tmp_path))
    assert s.is_sensitive(".env") is True
    assert s.is_sensitive(".aws/credentials") is True
    assert s.is_sensitive("src/main.py") is False


# ------------------------------------------------------------------ safe_join

def test_safe_join_ok(tmp_path):
    s = PathSafety(workspace=str(tmp_path))
    joined = s.safe_join(str(tmp_path), "src", "main.py")
    assert joined is not None
    assert joined.startswith(str(tmp_path))


def test_safe_join_rejects_traversal(tmp_path):
    s = PathSafety(workspace=str(tmp_path))
    assert s.safe_join(str(tmp_path), "..", "etc") is None
    assert s.safe_join(str(tmp_path), "a", "..", "b") is None


def test_safe_join_empty_base_returns_none():
    s = PathSafety(workspace="")
    assert s.safe_join("", "src") is None


def test_safe_join_skips_empty_parts(tmp_path):
    s = PathSafety(workspace=str(tmp_path))
    joined = s.safe_join(str(tmp_path), "", "src", "", "main.py")
    assert joined is not None


def test_safe_join_escape_via_absolute(tmp_path):
    """绝对路径 part 无法逃逸: 拼接后须仍在 base 下。"""
    s = PathSafety(workspace=str(tmp_path))
    joined = s.safe_join(str(tmp_path), os.sep + "etc")
    # 绝对路径拼到 base 后 os.path.join 会替换 base, 应被前缀检查拒绝
    assert joined is None or joined.startswith(str(tmp_path))


# ------------------------------------------------------------------ find_project_root

def test_find_project_root_from_subdir(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    s = PathSafety(workspace=str(root))
    found = s.find_project_root(str(root / "src"))
    assert found is not None
    assert Path(found) == root


def test_find_project_root_git_marker(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    s = PathSafety(workspace=str(root))
    found = s.find_project_root(str(root))
    assert found is not None


def test_find_project_root_none_when_no_marker():
    """无任何项目标记时返回 None。

    用盘根下不存在的路径构造: 向上搜索到盘根即 break, 不会命中仓库
    自身的项目标记。不用 tempfile (pytest 重定向到项目内 .pytest-tmp)
    也不用 cwd (其他测试可能 chdir 泄漏, 导致 abspath 指向项目内)。
    """
    import uuid
    from pathlib import Path

    anchor = Path.home().anchor  # Windows: "E:\" 盘根, 不依赖 cwd
    outside = str(
        Path(anchor)
        / f"tuan-nomarker-{uuid.uuid4().hex}"
        / "deep"
        / "sub"
    )
    s = PathSafety(workspace=outside)
    assert s.find_project_root(outside) is None


# ------------------------------------------------------------------ 模块级函数

def test_get_path_safety_singleton(tmp_path):
    g1 = get_path_safety(str(tmp_path))
    g2 = get_path_safety(str(tmp_path))
    assert g1 is g2  # 同 workspace 复用
    g3 = get_path_safety(str(tmp_path / "other"))
    assert g3 is not g1  # workspace 变化重建


def test_module_validate_path(tmp_path):
    r = validate_path("src/main.py", "read", str(tmp_path))
    assert r.safe is True
    r2 = validate_path("../etc/passwd", "read", str(tmp_path))
    assert r2.denied is True
