"""离线模型探测的回归测试。

重点覆盖 Windows 上的真实事故: ``ollama`` CLI 拉起后台守护进程并继承
stdout/stderr 管道句柄, 导致 ``subprocess.run(..., capture_output=True)``
在超时清理时永久阻塞在管道读线程 join 上 (整条路由决策链路挂死)。
修复手段是把输出重定向到临时文件 (无读线程), 本文件守护该行为。
"""

from __future__ import annotations

import sys
import time

from tuan_cli.models import offline


def test_capture_cmd_does_not_hang_on_inherited_pipe(tmp_path):
    """子进程拉起继承句柄的孙进程时, _capture_cmd 仍能在超时预算内返回。"""
    script = tmp_path / "spawner.py"
    script.write_text(
        "import subprocess, sys, time\n"
        # 孙进程继承父进程的 stdout/stderr, 并存活到父进程退出之后
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(8)'])\n"
        "print('ok', flush=True)\n"
        "time.sleep(3)\n",
        encoding="utf-8",
    )

    started = time.time()
    text, reason = offline._capture_cmd([sys.executable, str(script)], timeout=1.0)
    elapsed = time.time() - started

    assert text is None
    assert reason == "timeout"
    # 超时 1s + 清理开销; 若是管道 join 死锁这里会挂到 120s 以上
    assert elapsed < 2.5, f"_capture_cmd 未按时返回: {elapsed:.2f}s"


def test_capture_cmd_reports_missing():
    """命令不存在时返回 missing, 供上层给出安装指引。"""
    text, reason = offline._capture_cmd(["tuan-cli-definitely-not-exist"], timeout=5)
    assert text is None
    assert reason == "missing"


def test_ollama_status_falls_back_to_cli(monkeypatch):
    """HTTP API 不可达时回退 CLI; CLI 缺失给出安装提示而不抛异常。"""
    mgr = offline.OllamaManager(base_url="http://127.0.0.1:1")
    monkeypatch.setattr(offline, "_capture_cmd", lambda cmd, timeout: (None, "missing"))
    status = mgr.check_status()
    assert status.available is False
    assert "未安装" in (status.error or "")


def test_ollama_status_parses_cli_list(monkeypatch):
    """CLI 输出 (标题行 + 模型行) 被正确解析为模型列表。"""
    mgr = offline.OllamaManager(base_url="http://127.0.0.1:1")
    monkeypatch.setattr(
        offline, "_capture_cmd",
        lambda cmd, timeout: ("NAME  ID  SIZE  MODIFIED\nqwen2.5:7b  abc  4.7GB  2 hours ago\n", ""),
    )
    status = mgr.check_status()
    assert status.available is True
    assert [m.name for m in status.models or []] == ["qwen2.5:7b"]
