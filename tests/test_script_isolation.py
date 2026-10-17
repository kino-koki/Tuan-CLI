"""script_isolation 模块测试: 脚本执行隔离。"""
from __future__ import annotations

import os
import tempfile

import pytest

from tuan_cli.ext.script_isolation import (
    is_script_file,
    extract_script_path,
    resolve_script_path,
    scan_script_for_isolation,
    check_script_isolation,
    should_auto_isolate,
    format_isolation_summary,
)


class TestIsScriptFile:
    """is_script_file 单元测试。"""

    def test_python_files(self):
        assert is_script_file("script.py")
        assert is_script_file("script.PY")
        assert is_script_file("script.pyw")
        assert not is_script_file("script.pyc")
        assert not is_script_file("script.txt")

    def test_shell_files(self):
        assert is_script_file("script.sh")
        assert is_script_file("script.bash")
        assert not is_script_file("script.txt")

    def test_powershell_files(self):
        assert is_script_file("script.ps1")
        assert is_script_file("script.psm1")
        assert is_script_file("script.psd1")
        assert not is_script_file("script.txt")

    def test_batch_files(self):
        assert is_script_file("script.bat")
        assert is_script_file("script.cmd")
        assert not is_script_file("script.txt")

    def test_empty_path(self):
        assert not is_script_file("")
        assert not is_script_file(None)


class TestExtractScriptPath:
    """extract_script_path 单元测试。"""

    def test_python_inline_c(self):
        """python -c 'code' 不应提取脚本路径。"""
        path = extract_script_path("python -c 'print(42)'")
        assert path is None

    def test_python_script(self):
        """python script.py 应提取路径。"""
        path = extract_script_path("python script.py")
        assert path == "script.py"

    def test_python3_script(self):
        """python3 script.py 应提取路径。"""
        path = extract_script_path("python3 script.py")
        assert path == "script.py"

    def test_python_with_flags(self):
        """python -u -O script.py 应提取路径。"""
        path = extract_script_path("python -u -O script.py")
        assert path == "script.py"

    def test_python_quoted_path(self):
        """python "script with spaces.py" 应提取路径。"""
        path = extract_script_path('python "script with spaces.py"')
        assert path == "script with spaces.py"

    def test_python_single_quoted(self):
        """python 'script.py' 应提取路径。"""
        path = extract_script_path("python 'script.py'")
        assert path == "script.py"

    def test_bash_script(self):
        """bash script.sh 应提取路径。"""
        path = extract_script_path("bash script.sh")
        assert path == "script.sh"

    def test_sh_script(self):
        """sh script.sh 应提取路径。"""
        path = extract_script_path("sh script.sh")
        assert path == "script.sh"

    def test_powershell_file_flag(self):
        """powershell -File script.ps1 应提取路径。"""
        path = extract_script_path("powershell -File script.ps1")
        assert path == "script.ps1"

    def test_pwsh_script(self):
        """pwsh script.ps1 应提取路径。"""
        path = extract_script_path("pwsh script.ps1")
        assert path == "script.ps1"

    def test_batch_script(self):
        """script.bat 应提取路径。"""
        path = extract_script_path("script.bat")
        assert path == "script.bat"

    def test_no_script(self):
        """普通命令不应提取路径。"""
        assert extract_script_path("ls -la /tmp") is None
        assert extract_script_path("echo hello") is None

    def test_empty_command(self):
        """空命令不应提取路径。"""
        assert extract_script_path("") is None


class TestResolveScriptPath:
    """resolve_script_path 单元测试。"""

    def test_absolute_path(self):
        """绝对路径应直接解析。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("print('hello')\n")
            f.flush()
            path = f.name

        try:
            resolved = resolve_script_path(path)
            assert resolved == path
        finally:
            os.unlink(path)

    def test_relative_path_with_workspace(self):
        """工作区相对路径应正确解析。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("print('hello')\n")
            f.flush()
            path = f.name

        try:
            dirname = os.path.dirname(path)
            basename = os.path.basename(path)
            resolved = resolve_script_path(basename, workspace=dirname)
            assert resolved == path
        finally:
            os.unlink(path)

    def test_nonexistent_path(self):
        """不存在的文件应返回 None。"""
        resolved = resolve_script_path("/nonexistent/path/script.py")
        assert resolved is None

    def test_empty_path(self):
        """空路径应返回 None。"""
        assert resolve_script_path("") is None
        assert resolve_script_path(None) is None


class TestScanScriptForIsolation:
    """scan_script_for_isolation 单元测试。"""

    def test_dangerous_python_script(self):
        """包含危险调用的 Python 脚本应需要隔离。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("import os\nos.system('rm -rf /')\n")
            f.flush()
            path = f.name

        try:
            should_isolate, result, error = scan_script_for_isolation(path)
            assert should_isolate is True
            assert result is not None
            assert result.findings
            assert error == ""
        finally:
            os.unlink(path)

    def test_safe_python_script(self):
        """安全 Python 脚本不需要隔离。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("import json\n\nwith open('data.json') as f:\n    data = json.load(f)\n")
            f.flush()
            path = f.name

        try:
            should_isolate, result, error = scan_script_for_isolation(path)
            assert should_isolate is False
            assert error == ""
        finally:
            os.unlink(path)

    def test_powershell_script_isolated(self):
        """PowerShell 脚本默认隔离。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", delete=False) as f:
            f.write("Write-Host 'hello'\n")
            f.flush()
            path = f.name

        try:
            should_isolate, result, error = scan_script_for_isolation(path)
            assert should_isolate is True
            assert result is None  # 非 Python 无 AST 结果
        finally:
            os.unlink(path)

    def test_safe_shell_script(self):
        """安全 Shell 脚本不需要隔离。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write("#!/bin/bash\necho 'hello'\n")
            f.flush()
            path = f.name

        try:
            should_isolate, result, error = scan_script_for_isolation(path)
            assert should_isolate is False
            assert result is None
        finally:
            os.unlink(path)

    def test_dangerous_shell_script(self):
        """包含危险命令的 Shell 脚本需要隔离。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write("#!/bin/bash\nrm -rf /\n")
            f.flush()
            path = f.name

        try:
            should_isolate, result, error = scan_script_for_isolation(path)
            assert should_isolate is True
            assert result is None
        finally:
            os.unlink(path)

    def test_empty_script(self):
        """空脚本不需要隔离。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("")
            f.flush()
            path = f.name

        try:
            should_isolate, result, error = scan_script_for_isolation(path)
            assert should_isolate is False
        finally:
            os.unlink(path)

    def test_nonexistent_script(self):
        """不存在的文件返回 False。"""
        should_isolate, result, error = scan_script_for_isolation("/nonexistent/script.py")
        assert should_isolate is False
        assert result is None


class TestCheckScriptIsolation:
    """check_script_isolation 单元测试。"""

    def _make_ctx(self, auto_isolate=True, workspace=""):
        """创建模拟上下文。"""
        class MockKernel:
            config = {"sandbox.auto_isolate_scripts": auto_isolate}
        class MockCtx:
            kernel = MockKernel()
            self.workspace = workspace
        ctx = MockCtx()
        ctx.workspace = workspace
        return ctx

    def test_dangerous_script_isolated(self):
        """危险脚本应返回隔离决策。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("import os\nos.system('rm -rf /')\n")
            f.flush()
            path = f.name

        try:
            ctx = self._make_ctx(auto_isolate=True)
            result = check_script_isolation(f"python {path}", ctx)
            assert result is not None
            assert result["isolate"] is True
            assert "隔离" in result["summary"]
        finally:
            os.unlink(path)

    def test_safe_script_not_isolated(self):
        """安全脚本不应返回隔离决策。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("print('hello')\n")
            f.flush()
            path = f.name

        try:
            ctx = self._make_ctx(auto_isolate=True)
            result = check_script_isolation(f"python {path}", ctx)
            assert result is None
        finally:
            os.unlink(path)

    def test_auto_isolate_disabled(self):
        """禁用自动隔离时不返回决策。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("import os\nos.system('rm -rf /')\n")
            f.flush()
            path = f.name

        try:
            ctx = self._make_ctx(auto_isolate=False)
            result = check_script_isolation(f"python {path}", ctx)
            assert result is None
        finally:
            os.unlink(path)

    def test_non_script_command(self):
        """非脚本命令不应返回隔离决策。"""
        ctx = self._make_ctx(auto_isolate=True)
        result = check_script_isolation("ls -la /tmp", ctx)
        assert result is None

    def test_nonexistent_script(self):
        """不存在的脚本不应返回隔离决策。"""
        ctx = self._make_ctx(auto_isolate=True)
        result = check_script_isolation("python /nonexistent/script.py", ctx)
        assert result is None


class TestFormatIsolationSummary:
    """format_isolation_summary 单元测试。"""

    def test_isolation_summary(self):
        """隔离摘要应包含脚本名和发现详情。"""
        from tuan_cli.ext.ast_scan import ScanResult, ScanFinding

        findings = [ScanFinding(
            severity="high",
            label="subprocess.run (子进程调用)",
            line=3,
            col=5,
            snippet="subprocess.run(['ls'])",
        )]
        result = ScanResult(findings=findings)
        summary = format_isolation_summary("/tmp/script.py", result, True)
        assert "script.py" in summary
        assert "隔离" in summary
        assert "subprocess.run" in summary

    def test_no_isolation_summary(self):
        """无隔离摘要应说明直接执行。"""
        summary = format_isolation_summary("/tmp/script.py", None, False)
        assert "script.py" in summary
        assert "直接执行" in summary
