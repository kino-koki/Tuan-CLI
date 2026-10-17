"""ast_scan 模块测试: Python 脚本 AST 静态扫描。"""
from __future__ import annotations

import pytest

from tuan_cli.ext.ast_scan import (
    ScanFinding,
    ScanResult,
    scan_python_source,
    extract_python_sources,
    scan_shell_command,
)


class TestScanPythonSource:
    """scan_python_source 单元测试。"""

    def test_empty_source(self):
        """空源码应返回无发现。"""
        result = scan_python_source("")
        assert result.findings == []
        assert result.parse_error is None
        assert not result.blocked
        assert not result.needs_confirmation

    def test_normal_code_no_findings(self):
        """正常 Python 代码不应有发现。"""
        source = """import os
import json

def main():
    with open("config.json") as f:
        data = json.load(f)
    print(f"Loaded {len(data)} items")

if __name__ == "__main__":
    main()
"""
        result = scan_python_source(source)
        assert result.findings == []
        assert not result.blocked
        assert not result.needs_confirmation

    def test_os_system_detected(self):
        """os.system 应被检测为 critical。"""
        source = """import os
os.system("rm -rf /")
"""
        result = scan_python_source(source)
        assert result.findings
        assert result.blocked
        assert any(f.severity == "critical" and "os.system" in f.label for f in result.findings)

    def test_os_popen_detected(self):
        """os.popen 应被检测为 critical。"""
        source = """import os
p = os.popen("ls -la")
"""
        result = scan_python_source(source)
        assert result.findings
        assert result.blocked
        assert any("os.popen" in f.label for f in result.findings)

    def test_subprocess_run_detected(self):
        """subprocess.run 应被检测为 high。"""
        source = """import subprocess
result = subprocess.run(["ls", "-la"], capture_output=True)
"""
        result = scan_python_source(source)
        assert result.findings
        assert result.needs_confirmation
        assert not result.blocked
        assert any("subprocess.run" in f.label for f in result.findings)

    def test_subprocess_shell_true_detected_critical(self):
        """subprocess.run(shell=True) 应升级为 critical。"""
        source = """import subprocess
result = subprocess.run("rm -rf /", shell=True)
"""
        result = scan_python_source(source)
        assert result.findings
        assert result.blocked
        assert any(
            f.severity == "critical" and "shell=True" in f.label
            for f in result.findings
        )

    def test_subprocess_popen_detected(self):
        """subprocess.Popen 应被检测为 high。"""
        source = """import subprocess
proc = subprocess.Popen(["echo", "hello"])
"""
        result = scan_python_source(source)
        assert result.findings
        assert result.needs_confirmation
        assert not result.blocked
        assert any("Popen" in f.label for f in result.findings)

    def test_eval_detected(self):
        """eval 应被检测为 critical。"""
        source = """x = eval("2 + 2")
"""
        result = scan_python_source(source)
        assert result.findings
        assert result.blocked
        assert any("eval" in f.label for f in result.findings)

    def test_exec_detected(self):
        """exec 应被检测为 critical。"""
        source = """exec("print('hello')")
"""
        result = scan_python_source(source)
        assert result.findings
        assert result.blocked
        assert any("exec" in f.label for f in result.findings)

    def test_socket_detected(self):
        """socket.socket 应被检测为 high。"""
        source = """import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
"""
        result = scan_python_source(source)
        assert result.findings
        assert result.needs_confirmation
        assert not result.blocked
        assert any("socket" in f.label for f in result.findings)

    def test_pickle_loads_detected(self):
        """pickle.loads 应被检测为 high。"""
        source = """import pickle
data = pickle.loads(b"\\x80\\x04...")
"""
        result = scan_python_source(source)
        assert result.findings
        assert result.needs_confirmation
        assert any("pickle" in f.label for f in result.findings)

    def test_ctypes_cdll_detected(self):
        """ctypes.CDLL 应被检测为 high。"""
        source = """import ctypes
lib = ctypes.CDLL("libc.so.6")
"""
        result = scan_python_source(source)
        assert result.findings
        assert result.needs_confirmation
        assert any("CDLL" in f.label for f in result.findings)

    def test_shutil_rmtree_detected(self):
        """shutil.rmtree 应被检测为 high。"""
        source = """import shutil
shutil.rmtree("/tmp/build")
"""
        result = scan_python_source(source)
        assert result.findings
        assert result.needs_confirmation
        assert any("rmtree" in f.label for f in result.findings)

    def test_indirect_call_via_from_import(self):
        """from os import system; system(...) 应被检测。"""
        source = """from os import system
system("rm -rf /")
"""
        result = scan_python_source(source)
        assert result.findings
        assert result.blocked
        assert any("system" in f.label.lower() for f in result.findings)

    def test_indirect_call_via_variable(self):
        """cmd = os.system; cmd(...) 应被检测为间接调用。"""
        source = """import os
cmd = os.system
cmd("rm -rf /")
"""
        result = scan_python_source(source)
        assert result.findings
        assert any("间接调用" in f.label for f in result.findings)

    def test_import_alias_detected(self):
        """import os as o; o.system(...) 应被检测。"""
        source = """import os as o
o.system("rm -rf /")
"""
        result = scan_python_source(source)
        assert result.findings
        assert result.blocked
        assert any("os.system" in f.label for f in result.findings)

    def test_syntax_error_detected(self):
        """语法错误应被标记为 high。"""
        source = "def (broken syntax"
        result = scan_python_source(source)
        assert result.parse_error is not None
        assert result.needs_confirmation
        assert not result.blocked

    def test_syntax_error_line_info(self):
        """语法错误应包含行号信息。"""
        source = "def main():\n    return)\n"
        result = scan_python_source(source)
        assert result.parse_error is not None

    def test_line_number_tracking(self):
        """发现应记录正确的行号。"""
        source = """import os
# line 2
x = 1
os.system("echo hello")
"""
        result = scan_python_source(source)
        assert result.findings
        os_sys_findings = [f for f in result.findings if "os.system" in f.label]
        assert os_sys_findings
        assert os_sys_findings[0].line == 4

    def test_multiple_findings(self):
        """多个危险调用应全部报告。"""
        source = """import os
import subprocess
import socket

os.system("echo 1")
subprocess.run(["echo", "2"])
s = socket.socket()
"""
        result = scan_python_source(source)
        assert len(result.findings) >= 3
        assert result.blocked  # 有 os.system
        assert result.needs_confirmation  # 有 subprocess.run

    def test_max_severity(self):
        """max_severity 应返回最高等级。"""
        source = "eval('1')"
        result = scan_python_source(source)
        assert result.max_severity == "critical"

        source2 = "import socket; socket.socket()"
        result2 = scan_python_source(source2)
        assert result2.max_severity == "high"

    def test_summary_output(self):
        """summary() 应生成可读文本。"""
        source = "import os; os.system('rm -rf /')"
        result = scan_python_source(source)
        summary = result.summary()
        assert "AST 扫描" in summary
        assert "critical" in summary
        assert "os.system" in summary

    def test_normal_os_path_is_safe(self):
        """os.path 操作不应被误判。"""
        source = """import os
os.path.join("a", "b")
os.path.exists("/tmp")
os.path.dirname("/usr/bin")
"""
        result = scan_python_source(source)
        assert result.findings == []

    def test_compile_detected(self):
        """compile() 应被检测为 medium。"""
        source = """code = compile("print('hi')", "<string>", "exec")
"""
        result = scan_python_source(source)
        assert result.findings
        assert any(f.severity == "medium" and "compile" in f.label for f in result.findings)

    def test_deep_nesting(self):
        """嵌套调用中的危险函数应被检测。"""
        source = """import os
def wrapper(cmd):
    return os.system(cmd)

result = wrapper("rm -rf /")
"""
        result = scan_python_source(source)
        assert result.findings
        assert result.blocked

    def test_string_literal_dangerous_detection(self):
        """字符串字面量中的危险调用应被检测。"""
        source = """eval("import os; os.system('rm -rf /')")
"""
        result = scan_python_source(source)
        assert result.findings
        # 应有 eval (critical) 和字符串中的 os.system (high)
        assert any(f.severity == "critical" for f in result.findings)


class TestExtractPythonSources:
    """extract_python_sources 单元测试。"""

    def test_no_python_in_command(self):
        """命令中无 Python 应返回空列表。"""
        sources = extract_python_sources("ls -la /tmp")
        assert sources == []

    def test_python_c_inline_double_quotes(self):
        """python -c "code" 应被提取。"""
        sources = extract_python_sources('python -c "print(42)"')
        assert len(sources) == 1
        assert sources[0][0] == "<python -c>"
        assert "print(42)" in sources[0][1]

    def test_python_c_inline_single_quotes(self):
        """python -c 'code' 应被提取。"""
        sources = extract_python_sources("python -c 'print(42)'")
        assert len(sources) == 1
        assert sources[0][0] == "<python -c>"
        assert "print(42)" in sources[0][1]

    def test_python3_script_path(self):
        """python3 script.py 应被提取（需文件存在）。"""
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("print('hello')\n")
            f.flush()
            script_path = f.name

        try:
            sources = extract_python_sources(f"python3 {script_path}")
            assert len(sources) == 1
            assert sources[0][0] == os.path.basename(script_path)
        finally:
            os.unlink(script_path)

    def test_python_with_flags(self):
        """python -u -O script.py 应被提取（需文件存在）。"""
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("print('hello')\n")
            f.flush()
            script_path = f.name

        try:
            sources = extract_python_sources(f"python -u -O {script_path}")
            assert len(sources) == 1
        finally:
            os.unlink(script_path)

    def test_python_c_with_dangerous_code(self):
        """python -c 中的危险代码应可提取。"""
        sources = extract_python_sources('python -c "import os; os.system(\'rm -rf /\')"')
        assert len(sources) == 1
        assert "os.system" in sources[0][1]

    def test_empty_command(self):
        """空命令应返回空列表。"""
        sources = extract_python_sources("")
        assert sources == []


class TestScanShellCommand:
    """scan_shell_command 一站式接口测试。"""

    def test_no_python_returns_none(self):
        """无 Python 的命令应返回 None。"""
        result = scan_shell_command("ls -la /tmp")
        assert result is None

    def test_python_c_dangerous(self):
        """python -c 中的危险代码应被检测。"""
        result = scan_shell_command('python -c "import os; os.system(\'rm -rf /\')"')
        assert result is not None
        assert result.blocked
        assert any("os.system" in f.label for f in result.findings)

    def test_python_c_safe(self):
        """python -c 中的安全代码不应有发现。"""
        result = scan_shell_command('python -c "print(42)"')
        if result is not None:
            assert not result.blocked
            assert not result.needs_confirmation

    def test_python_script_with_dangerous_calls(self):
        """python script.py 中的危险代码应被检测（需文件存在）。"""
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("import os\nos.system('rm -rf /')\n")
            f.flush()
            script_path = f.name

        try:
            workspace = os.path.dirname(script_path)
            result = scan_shell_command(f"python {script_path}", workspace=workspace)
            assert result is not None
            assert result.blocked
        finally:
            os.unlink(script_path)

    def test_python_c_with_subprocess(self):
        """python -c 中的 subprocess 调用应被检测为 high。"""
        result = scan_shell_command('python -c "import subprocess; subprocess.run([\'ls\'])"')
        assert result is not None
        assert result.needs_confirmation
        assert not result.blocked

    def test_python_c_shell_true_escalates(self):
        """python -c 中 shell=True 应升级为 critical。"""
        result = scan_shell_command(
            'python -c "import subprocess; subprocess.run(\'rm -rf /\', shell=True)"'
        )
        assert result is not None
        assert result.blocked
