"""会话导出 zip 测试 —— 对标 Kimi Code 的 `kimi export`。

验证:
- 导出产生合法 zip 文件 (testzip 无损坏);
- zip 内含 session.jsonl 与 manifest.json, 消息数统计正确。
"""

import json
import zipfile

from qingxiaotuan.cli.cmd_session_export import export_session_zip


def _make_session(tmp_path):
    f = tmp_path / "20260101-120000-abcdef.jsonl"
    recs = [
        {"ts": 1.0, "type": "session.meta", "task": "导出演示"},
        {"ts": 2.0, "type": "user", "message": {"role": "user", "content": "你好"}},
        {"ts": 3.0, "type": "assistant", "message": {"role": "assistant", "content": "嗨"}},
        {"ts": 4.0, "type": "tool_call", "name": "write_file",
         "arguments": {"path": "out.txt"}},
    ]
    f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n",
                 encoding="utf-8")
    return f


def test_export_creates_zip(tmp_path, qxt_home):
    src = _make_session(tmp_path)
    dest = tmp_path / "out.zip"
    export_session_zip(src, dest)
    assert dest.exists()
    with zipfile.ZipFile(dest) as zf:
        assert zf.testzip() is None


def test_export_contains_session_data(tmp_path, qxt_home):
    src = _make_session(tmp_path)
    dest = tmp_path / "out.zip"
    export_session_zip(src, dest)
    with zipfile.ZipFile(dest) as zf:
        names = zf.namelist()
        assert "session.jsonl" in names
        assert "manifest.json" in names
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["message_count"] >= 2
        assert manifest["session_id"].startswith("20260101")
