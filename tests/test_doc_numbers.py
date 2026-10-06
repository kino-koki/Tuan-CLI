"""对外文档数字核对脚本的回归测试。

以子进程方式调用, 与 CI/人工用法完全一致, 避免导入路径耦合。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "verify_doc_numbers.py"


def test_script_exists() -> None:
    assert SCRIPT.is_file(), f"缺少核对脚本: {SCRIPT}"


def test_doc_numbers_are_consistent() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"

    data = json.loads(proc.stdout)
    # 真值由脚本从代码实时计算, 这里与 catalog 交叉核对 (不再硬编码具体数字,
    # 避免每次增删供应商都要改测试)。
    from qingxiaotuan.models.provider_catalog import ALL_PROVIDERS
    assert data["truth"]["providers"] == len(ALL_PROVIDERS)
    assert data["truth"]["providers"] >= 50
    assert data["truth"]["models"] >= 1100
    assert data["problems"] == []
