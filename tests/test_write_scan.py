"""write_scan 模块测试: 文件内容危险命令检测。"""
from __future__ import annotations

import pytest

from tuan_cli.ext.write_scan import (
    scan_content_for_danger,
    format_matches_for_user,
)


class TestScanContent:
    """scan_content_for_danger 单元测试。"""

    def test_empty_content_is_safe(self):
        """空内容应视为安全。"""
        safe, matches = scan_content_for_danger("")
        assert safe is False  # 空内容不应被拦截
        assert matches is None

    def test_normal_content_is_safe(self):
        """普通文本内容应通过。"""
        content = """#!/usr/bin/env python3
# 这是一个正常的 Python 脚本
import os
import sys

def main():
    print("Hello, World!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
"""
        safe, matches = scan_content_for_danger(content)
        assert safe is False
        assert matches is None

    def test_dangerous_rm_rf_detected(self):
        """rm -rf / 应被检测。"""
        content = "#!/bin/bash\nrm -rf /\n"
        safe, matches = scan_content_for_danger(content)
        assert safe is True
        assert matches is not None
        assert len(matches) > 0
        assert any("rm" in m["label"].lower() for m in matches)

    def test_dangerous_mkfs_detected(self):
        """mkfs 命令应被检测。"""
        content = "mkfs.ext4 /dev/sda1\n"
        safe, matches = scan_content_for_danger(content)
        assert safe is True
        assert matches is not None
        assert any("mkfs" in m["label"].lower() for m in matches)

    def test_dangerous_dd_raw_disk_detected(self):
        """dd 写裸磁盘应被检测。"""
        content = "dd if=/dev/zero of=/dev/sda bs=1M\n"
        safe, matches = scan_content_for_danger(content)
        assert safe is True
        assert matches is not None
        assert any("dd" in m["label"].lower() for m in matches)

    def test_dangerous_shutdown_detected(self):
        """shutdown 命令应被检测。"""
        content = "shutdown -h now\n"
        safe, matches = scan_content_for_danger(content)
        assert safe is True
        assert matches is not None
        assert any("shutdown" in m["label"].lower() for m in matches)

    def test_dangerous_authorized_keys_detected(self):
        """写入 authorized_keys 应被检测。"""
        content = 'echo "ssh-rsa AAAA..." >> ~/.ssh/authorized_keys\n'
        safe, matches = scan_content_for_danger(content)
        assert safe is True
        assert matches is not None
        assert any("authorized_keys" in m["label"].lower() for m in matches)

    def test_dangerous_fork_bomb_detected(self):
        """fork bomb 应被检测。"""
        content = ":(){ :|:& };:\n"
        safe, matches = scan_content_for_danger(content)
        assert safe is True
        assert matches is not None
        assert any("fork bomb" in m["label"].lower() for m in matches)

    def test_dangerous_chmod_root_detected(self):
        """chmod -R 000 / 应被检测。"""
        content = "chmod -R 000 /\n"
        safe, matches = scan_content_for_danger(content)
        assert safe is True
        assert matches is not None

    def test_dangerous_reg_delete_detected(self):
        """reg delete 应被检测。"""
        content = "reg delete HKLM\\SOFTWARE\\Malware /f\n"
        safe, matches = scan_content_for_danger(content)
        assert safe is True
        assert matches is not None

    def test_dangerous_sql_drop_detected(self):
        """DROP TABLE 应被检测。"""
        content = "DROP TABLE users;\n"
        safe, matches = scan_content_for_danger(content)
        assert safe is True
        assert matches is not None
        assert any("drop" in m["label"].lower() for m in matches)

    def test_dangerous_windows_remove_item(self):
        """PowerShell Remove-Item -Recurse -Force 应被检测。"""
        content = "Remove-Item C:\\ -Recurse -Force\n"
        safe, matches = scan_content_for_danger(content)
        assert safe is True
        assert matches is not None

    def test_dangerous_in_python_script(self):
        """Python 脚本中的危险命令应被检测。"""
        content = """import os
os.system("rm -rf /")
"""
        safe, matches = scan_content_for_danger(content)
        assert safe is True
        assert matches is not None

    def test_dangerous_in_multi_line_content(self):
        """多行内容中的危险命令应被检测。"""
        content = """#!/bin/bash
# Setup script
echo "Starting setup"
apt-get update
rm -rf /tmp/*
echo "Done"
"""
        safe, matches = scan_content_for_danger(content)
        assert safe is True
        assert matches is not None

    def test_normal_code_is_safe(self):
        """正常代码不应被误判。"""
        content = """#!/usr/bin/env python3
import os
import json

def read_config(path):
    with open(path) as f:
        return json.load(f)

def write_data(path, data):
    with open(path, 'w') as f:
        json.dump(data, f)

if __name__ == "__main__":
    config = read_config("config.json")
    write_data("output.json", config)
"""
        safe, matches = scan_content_for_danger(content)
        assert safe is False
        assert matches is None

    def test_line_column_tracking(self):
        """匹配应记录正确的行号和列号。"""
        content = """line1 safe
line2 rm -rf /
line3 safe
"""
        safe, matches = scan_content_for_danger(content)
        assert safe is True
        assert matches is not None
        # rm -rf 在第 2 行
        rm_matches = [m for m in matches if "rm" in m["label"].lower()]
        assert rm_matches
        assert rm_matches[0]["line"] == 2


class TestFormatMatches:
    """format_matches_for_user 单元测试。"""

    def test_empty_matches(self):
        """空匹配应返回空字符串。"""
        assert format_matches_for_user([]) == ""

    def test_formats_matches(self):
        """应格式化匹配结果为可读文本。"""
        matches = [{
            "pattern": r"rm -rf /",
            "label": "rm -rf / (递归强制删除根目录)",
            "match": "rm -rf /",
            "line": 1,
            "column": 1,
            "line_content": "rm -rf /",
        }]
        result = format_matches_for_user(matches)
        assert "危险内容" in result
        assert "行 1" in result
