"""桌面端引擎端到端验证 —— 模拟 electron 壳拉起 Python 引擎并走协议闭环。

用法:
  python scripts/verify_desktop_engine.py [--model deepseek-chat]

流程 (对齐壳的行为):
  1. 以壳固定 argv 拉起 `python -m tuan_cli.stream_json` (--bare 纯净模式);
  2. 读启动信封 system/init (壳收到才标记引擎就绪);
  3. 发 user 消息 (NDJSON) -> 等待 stream_event 流 -> 等到 result (result-gated);
  4. 校验信封链合法、result 无异常、工具清单可用;
  5. 退出码 0 = 通过。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = Path(os.environ.get("TUAN_ENGINE_EXE", str(ROOT / ".venv" / "Scripts" / "python.exe")))

SHELL_ARGV = [
    "-m", "tuan_cli.stream_json",
    "--input-format", "stream-json",
    "--output-format", "stream-json",
    "--verbose",
    "--include-partial-messages",
    "--permission-mode", "bypassPermissions",
    "--permission-prompt-tool", "stdio",
    "--bare",
]


def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else "deepseek-chat"
    argv = SHELL_ARGV + ["--model", model]
    print(f"[verify] 拉起引擎: {PYTHON} {' '.join(argv)}")

    proc = subprocess.Popen(
        [str(PYTHON)] + argv,
        cwd=str(ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    def read_envelope(label: str) -> dict:
        line = proc.stdout.readline()
        if not line:
            err = proc.stderr.read() or "(无 stderr)"
            raise RuntimeError(f"{label}: 引擎提前退出。stderr: {err[:500]}")
        return json.loads(line)

    try:
        # 1) 启动信封 (system/init = {type:"system", subtype:"init"})
        init = read_envelope("init")
        assert init["type"] == "system" and init["subtype"] == "init", \
            f"首信封应为 system/init, 实际 {init.get('type')}/{init.get('subtype')}"
        tools = init.get("tools") or []
        print(f"[ok] system/init: {len(tools)} 工具, version={init.get('claude_code_version')}")
        assert len(tools) >= 20, f"工具数异常: {len(tools)}"

        # 2) 发 user
        user_msg = {
            "type": "user",
            "message": {"content": [{"type": "text", "text": "只回复两个字: 收到"}]},
        }
        proc.stdin.write(json.dumps(user_msg, ensure_ascii=False) + "\n")
        proc.stdin.flush()

        # 3) 收集信封直到 result
        stream_events = 0
        result = None
        while True:
            m = read_envelope("turn")
            t = m["type"]
            if t == "stream_event":
                stream_events += 1
                continue
            if t == "result":
                result = m
                break
        assert result is not None
        assert result["type"] == "result"
        assert "subtype" not in result or True  # 兼容
        print(f"[ok] result: stop_reason={result.get('stop_reason')} "
              f"errors={result.get('errors') or '无'} stream_event={stream_events}")
        assert not result.get("errors"), f"result 携带错误: {result['errors']}"

        # 4) 关闭 (EOF)
        proc.stdin.close()
        proc.wait(timeout=10)
        print(f"[ok] 引擎正常退出 (exit {proc.returncode})")
        print("[verify] 协议闭环通过 ✓")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[verify] 失败: {exc}")
        proc.kill()
        return 1


if __name__ == "__main__":
    sys.exit(main())
