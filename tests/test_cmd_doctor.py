"""``tuan doctor`` CLI 的单元测试 (cmd_doctor.py)。

环境健康诊断。覆盖:
1. _f: finding 结构
2. _exit_code: 无错误=0 / 有错误=2 (warn 不计)
3. _parse_frontmatter: 合法 / 缺fm / 坏YAML / 非dict / 读失败
4. run_checks: 全新安装六子系统可初始化 / 无 error
5. _render_json: 输出结构 + 退出码
6. _render_rich: 不崩溃

通过 tmp_path 做真实文件系统测试 (run_checks 接受 home/workspace 参数)。
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from tuan_cli.cli import cmd_doctor as P


# ============================================================ _f


class TestF:
    def test_defaults(self) -> None:
        f = P._f("config", "ok", "msg")
        assert f["category"] == "config"
        assert f["status"] == "ok"
        assert f["message"] == "msg"
        assert f["detail"] == ""
        assert f["fixable"] is False
        assert f["fixed"] is False
        assert f["path"] == ""

    def test_with_extras(self) -> None:
        f = P._f("env", "error", "fail", detail="d", fixable=True,
                 fixed=False, path="/x")
        assert f["detail"] == "d"
        assert f["fixable"] is True
        assert f["path"] == "/x"


# ============================================================ _exit_code


class TestExitCode:
    def test_no_error(self) -> None:
        findings = [P._f("env", "ok", "x"), P._f("config", "warn", "y")]
        assert P._exit_code(findings) == 0

    def test_error(self) -> None:
        findings = [P._f("env", "ok", "x"), P._f("config", "error", "bad")]
        assert P._exit_code(findings) == 2

    def test_empty(self) -> None:
        assert P._exit_code([]) == 0


# ============================================================ _parse_frontmatter


class TestParseFrontmatter:
    def test_valid(self, tmp_path) -> None:
        p = tmp_path / "skill.md"
        p.write_text("---\nname: X\ndescription: Y\n---\n正文内容", encoding="utf-8")
        meta, body, err = P._parse_frontmatter(p)
        assert err is None
        assert meta["name"] == "X"
        assert "正文" in body

    def test_missing_fm(self, tmp_path) -> None:
        p = tmp_path / "skill.md"
        p.write_text("无 frontmatter", encoding="utf-8")
        _, _, err = P._parse_frontmatter(p)
        assert err is not None
        assert "frontmatter" in err

    def test_bad_yaml(self, tmp_path) -> None:
        p = tmp_path / "skill.md"
        p.write_text("---\nkey: [bad\n---\nbody", encoding="utf-8")
        _, _, err = P._parse_frontmatter(p)
        assert err is not None
        assert "语法" in err or "YAML" in err

    def test_non_dict(self, tmp_path) -> None:
        p = tmp_path / "skill.md"
        p.write_text("---\n- a\n- b\n---\nbody", encoding="utf-8")
        _, _, err = P._parse_frontmatter(p)
        assert err is not None
        assert "映射" in err

    def test_read_failure(self, tmp_path) -> None:
        p = tmp_path / "nonexistent.md"
        _, _, err = P._parse_frontmatter(p)
        assert err is not None
        assert "读取失败" in err


# ============================================================ run_checks


class TestRunChecks:
    def test_fresh_install(self, tmp_path) -> None:
        # 全新安装: 无 config / 无 skills / 无项目文档 / 空工作区
        findings = P.run_checks(tmp_path, home=tmp_path)
        categories = {f["category"] for f in findings}
        assert "config" in categories
        assert "skills" in categories
        assert "project" in categories
        assert "env" in categories
        assert "cache" in categories

    def test_fresh_install_no_errors(self, tmp_path) -> None:
        # 全新安装不应有 error 级别问题 (只有 warn 提示)
        findings = P.run_checks(tmp_path, home=tmp_path)
        errors = [f for f in findings if f["status"] == "error"]
        assert errors == [], f"全新安装不应有 error: {errors}"

    def test_config_missing_warn(self, tmp_path) -> None:
        findings = P.run_checks(tmp_path, home=tmp_path)
        cfg_findings = [f for f in findings if f["category"] == "config"]
        assert any(f["status"] == "warn" for f in cfg_findings)

    def test_config_invalid_yaml(self, tmp_path) -> None:
        (tmp_path / "config.yaml").write_text(
            "key: [bad\n  bad-indent: x\n", encoding="utf-8")
        findings = P.run_checks(tmp_path, home=tmp_path)
        cfg_findings = [f for f in findings if f["category"] == "config"]
        assert any(f["status"] == "error" for f in cfg_findings)

    def test_config_valid(self, tmp_path) -> None:
        (tmp_path / "config.yaml").write_text(
            "model:\n  provider: openai\n  model: gpt-4\n", encoding="utf-8")
        findings = P.run_checks(tmp_path, home=tmp_path)
        cfg_findings = [f for f in findings if f["category"] == "config"]
        assert any("语法合法" in f["message"] for f in cfg_findings)

    def test_config_missing_provider(self, tmp_path) -> None:
        (tmp_path / "config.yaml").write_text("model: {}\n", encoding="utf-8")
        findings = P.run_checks(tmp_path, home=tmp_path)
        cfg_findings = [f for f in findings if f["category"] == "config"]
        assert any("provider" in f["message"] for f in cfg_findings)

    def test_config_unknown_field(self, tmp_path) -> None:
        (tmp_path / "config.yaml").write_text(
            "model:\n  provider: openai\n  model: gpt-4\nbogus_key: 1\n",
            encoding="utf-8")
        findings = P.run_checks(tmp_path, home=tmp_path)
        cfg_findings = [f for f in findings if f["category"] == "config"]
        assert any("未知顶层字段" in f["message"] for f in cfg_findings)

    def test_skill_missing_fields(self, tmp_path) -> None:
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "my_skill.md").write_text(
            "---\ntitle: X\n---\n正文", encoding="utf-8")
        findings = P.run_checks(tmp_path, home=tmp_path)
        skill_findings = [f for f in findings if f["category"] == "skills"]
        assert any("必填字段" in f["message"] for f in skill_findings)

    def test_skill_valid(self, tmp_path) -> None:
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "my_skill.md").write_text(
            "---\nname: MySkill\ndescription: 做某事\n---\n正文内容",
            encoding="utf-8")
        findings = P.run_checks(tmp_path, home=tmp_path)
        skill_findings = [f for f in findings if f["category"] == "skills"]
        assert any("frontmatter 合法" in f["message"] for f in skill_findings)

    def test_project_doc_oversized(self, tmp_path) -> None:
        big = tmp_path / "TUAN.md"
        big.write_bytes(b"x" * (33 * 1024))
        findings = P.run_checks(tmp_path, home=tmp_path)
        proj_findings = [f for f in findings if f["category"] == "project"]
        assert any("超过" in f["message"] for f in proj_findings)

    def test_project_doc_not_utf8(self, tmp_path) -> None:
        big = tmp_path / "TUAN.md"
        big.write_bytes(b"\xff\xfe\x00\x01")  # 非 UTF-8
        findings = P.run_checks(tmp_path, home=tmp_path)
        proj_findings = [f for f in findings if f["category"] == "project"]
        assert any("UTF-8" in f["message"] for f in proj_findings)

    def test_project_doc_ok(self, tmp_path) -> None:
        (tmp_path / "TUAN.md").write_text("# 项目说明", encoding="utf-8")
        findings = P.run_checks(tmp_path, home=tmp_path)
        proj_findings = [f for f in findings if f["category"] == "project"]
        assert any("可读" in f["message"] for f in proj_findings)

    def test_fix_creates_dirs(self, tmp_path) -> None:
        P.run_checks(tmp_path, home=tmp_path, fix=True)
        assert (tmp_path / "skills").is_dir()
        assert (tmp_path / ".agents").is_dir()


# ============================================================ _render_json


class TestRenderJson:
    def test_structure(self, monkeypatch) -> None:
        buf = io.StringIO()
        monkeypatch.setattr(P.sys, "stdout", buf)
        findings = [
            P._f("env", "ok", "x"),
            P._f("config", "warn", "y"),
            P._f("skills", "error", "z"),
        ]
        rc = P._render_json(findings)
        data = json.loads(buf.getvalue())
        assert rc == 2
        assert data["exit_code"] == 2
        assert data["summary"]["ok"] == 1
        assert data["summary"]["warn"] == 1
        assert data["summary"]["error"] == 1
        assert len(data["findings"]) == 3

    def test_empty(self, monkeypatch) -> None:
        buf = io.StringIO()
        monkeypatch.setattr(P.sys, "stdout", buf)
        rc = P._render_json([])
        data = json.loads(buf.getvalue())
        assert rc == 0
        assert data["exit_code"] == 0


# ============================================================ DSH 原生插件


class TestDshPlugins:
    """_check_dsh_plugins: 官方 bundle 存在时全链路自检。"""

    BUNDLE = Path(r"G:\Tuan-CLI-Official\plugins\tuan-skills-bundle")

    @pytest.mark.skipif(not (BUNDLE / "lib" / "index.js").exists(),
                        reason="缺少 tuan-skills-bundle")
    def test_ok_when_bundle_present(self) -> None:
        fs = P._check_dsh_plugins()
        plugins = [f for f in fs if f["category"] == "plugins"]
        assert len(plugins) == 1
        assert plugins[0]["status"] == "ok"
        assert "契约: tuan-skills-bundle" in plugins[0]["message"]
        assert "Config 字段 6" in plugins[0]["message"]
        assert "apply 技能" in plugins[0]["message"]
        # get 契约 (DSH /skill 命令加载路径) 纳入自检
        assert "get 定义" in plugins[0]["message"]
        # observeHostMutation 接线纳入自检
        assert "host mutation" in plugins[0]["message"]

    def test_warn_when_bundle_missing(self, monkeypatch) -> None:
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            return real_import(name, *a, **k)

        # 让 Path 指向不存在 bundle: 通过 monkeypatch 换掉模块级常量不可行,
        # 直接验证缺失分支: 把 bundle 换成不存在路径
        monkeypatch.setattr(
            P.Path, "exists", lambda self: False, raising=False
        )
        # 注意: _check_dsh_plugins 用 bundle/entry 两个 Path; 都 exists=False
        # 但 entry.exists() 是 bundle/lib/index.js, 需 bundle.exists() 也为 False。
        # 这里直接调用即可 (entry.exists 也走 monkeypatch → False)。
        fs = P._check_dsh_plugins()
        plugins = [f for f in fs if f["category"] == "plugins"]
        assert len(plugins) == 1
        assert plugins[0]["status"] == "warn"


# ============================================================ _render_rich


class TestRenderRich:
    def test_no_crash(self) -> None:
        findings = [
            P._f("env", "ok", "x"),
            P._f("config", "warn", "y", detail="详情"),
            P._f("skills", "error", "z", path="/x"),
        ]
        P._render_rich(findings)  # 不崩溃即可
