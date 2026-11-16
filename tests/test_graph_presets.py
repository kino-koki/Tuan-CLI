# -*- coding: utf-8 -*-
"""阶段 16-17 测试: 预置示例图 (graph_presets) + 前端连边能力。

覆盖:
* PRESETS 三张图结构合法 (节点/边/端口契约与 graph_api._from_dict_with_cache 一致)
* preset_graph 深拷贝隔离 / 未知 id fail-closed
* list_presets 目录字段
* server /api/graph/presets + /api/graph/preset 路由
* 前端 HTML 含「载入示例」按钮 / 端口连边事件 / collectGraph 端口字段名
"""

import copy
import json
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from tuan_cli.web import graph_presets as gp
from tuan_cli.web.graph_presets import (
    PRESETS, list_presets, preset_graph, get_preset_data,
)
from tuan_cli.web.graph_frontend import GRAPH_HTML


# ---------------------------------------------------------------------------
# presets 结构合法性
# ---------------------------------------------------------------------------

def _serialize(data):
    """把 preset data 交给 _from_dict_with_cache 同构重建 (校验契约一致)。"""
    from tuan_cli.web.graph_api import build_runner
    runner = build_runner(copy.deepcopy(data))
    return runner


@pytest.mark.parametrize("pid", list(PRESETS))
def test_preset_structure_valid(pid):
    """每张预置图都能被 GraphRunner 正常重建 (节点/端口/边契约正确)。"""
    data = get_preset_data(pid)
    # 字段存在性
    assert isinstance(data.get("nodes"), list) and data["nodes"]
    assert isinstance(data.get("edges"), list)
    ids = [n["node_id"] for n in data["nodes"]]
    assert len(ids) == len(set(ids)), "节点 id 必须唯一"
    for n in data["nodes"]:
        assert set(n) >= {"node_id", "ntype", "params", "inputs", "outputs"}
        for p in n.get("inputs", []) + n.get("outputs", []):
            assert set(p) >= {"name", "ptype"}
    # 边两端引用存在
    ntypes = {n["node_id"]: n["ntype"] for n in data["nodes"]}
    for e in data["edges"]:
        assert e["src_node"] in ntypes, "边 src 节点不存在"
        assert e["dst_node"] in ntypes, "边 dst 节点不存在"
        assert e["src_port"] and e["dst_port"]
    # 重建成功 (不抛) —— GraphRunner 契约
    _serialize(data)


@pytest.mark.parametrize("pid", ["code_demo", "text_pipeline", "video_gen"])
def test_preset_expected_shape(pid):
    """关键预置图的内容形态断言 (防回归)。"""
    data = get_preset_data(pid)
    ntypes = {n["node_id"]: n["ntype"] for n in data["nodes"]}
    if pid == "code_demo":
        assert "codeanim" in ntypes.values()
        assert data["edges"] == []
    if pid == "text_pipeline":
        assert ntypes.get("a") == "text" and ntypes.get("b") == "identity"
        assert ntypes.get("d") == "concat"
        assert len(data["edges"]) == 3
    if pid == "video_gen":
        assert ntypes.get("llm") == "llm_call" and ntypes.get("anim") == "codeanim"
        assert len(data["edges"]) == 1
        e = data["edges"][0]
        assert e["src_node"] == "llm" and e["src_port"] == "project_json"
        assert e["dst_node"] == "anim" and e["dst_port"] == "project_json"


def test_preset_graph_deepcopy_isolated():
    """preset_graph 返回深拷贝, 改副本不影响原图。"""
    a = preset_graph("code_demo")
    a["data"]["nodes"][0]["params"]["project_json"]["width"] = 999
    b = preset_graph("code_demo")
    assert b["data"]["nodes"][0]["params"]["project_json"]["width"] != 999


def test_preset_graph_unknown_id_fail_closed():
    """未知 preset_id 抛 ValueError (fail-closed, 不静默返回空图)。"""
    with pytest.raises(ValueError):
        preset_graph("nope")


def test_list_presets_directory():
    items = list_presets()
    assert len(items) == len(PRESETS)
    for it in items:
        assert set(it) >= {"id", "name", "desc", "nodes", "edges"}
        assert it["nodes"] > 0


# ---------------------------------------------------------------------------
# server 路由
# ---------------------------------------------------------------------------

def _make_server():
    from tuan_cli.web.server import WebServer
    srv = WebServer(kernel=None, workspace="g:\\Tuan-CLI", port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    for _ in range(200):
        if getattr(srv, "_httpd", None) is not None:
            break
        time.sleep(0.02)
    port = srv.port
    return srv, port, t


def _get(port, path):
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def test_http_presets_routes():
    srv, port, t = _make_server()
    try:
        st, body = _get(port, "/api/graph/presets")
        assert st == 200 and body["ok"]
        ids = {p["id"] for p in body["presets"]}
        assert ids >= {"code_demo", "text_pipeline", "video_gen"}
        st, body = _get(port, "/api/graph/preset?id=code_demo")
        assert st == 200 and body["ok"]
        assert body["preset"]["data"]["nodes"][0]["ntype"] == "codeanim"
        # 未知 id → 404 fail-closed
        st, body = _get(port, "/api/graph/preset?id=nope")
        assert st == 404 and not body["ok"]
    finally:
        if getattr(srv, "_httpd", None) is not None:
            srv._httpd.shutdown()
            srv._httpd.server_close()
        t.join(timeout=5)


# ---------------------------------------------------------------------------
# 前端 HTML 能力
# ---------------------------------------------------------------------------

def test_frontend_has_preset_and_controls():
    """前端含「载入示例」按钮、下拉、连边事件与正确的端口字段名。"""
    assert "presetBtn" in GRAPH_HTML
    assert "presetList" in GRAPH_HTML
    assert "载入示例" in GRAPH_HTML
    assert "refreshPresets" in GRAPH_HTML


def test_frontend_port_wiring_present():
    """前端含端口连边 (mousedown/mouseup/wire) 与删除连线。"""
    assert "bindPorts" in GRAPH_HTML
    assert "mousedown" in GRAPH_HTML and "mouseup" in GRAPH_HTML
    assert "function wire(" in GRAPH_HTML
    assert "edge-x" in GRAPH_HTML  # 删除连线锚点


def test_frontend_collect_graph_edge_field_names():
    """collectGraph 输出的边字段名与后端契约一致 (src_node/src_port/...)。"""
    assert "src_node:e.src" in GRAPH_HTML
    assert "src_port:e.srcPort" in GRAPH_HTML
    assert "dst_node:e.dst" in GRAPH_HTML
    assert "dst_port:e.dstPort" in GRAPH_HTML


def test_frontend_node_meta_params_match_backend():
    """前端节点默认参数名与后端执行器读取的一致 (text:content/concat:separator)。"""
    assert "params:{content:\"hello\"}" in GRAPH_HTML
    assert "params:{separator:\" \"}" in GRAPH_HTML


def test_frontend_media_download_button():
    """阶段18: 媒体预览后出现「下载产物」链接, 且 href 用 /api/media。"""
    assert "downloadBtn" in GRAPH_HTML
    assert "mediaBar" in GRAPH_HTML
    assert "⬇ 下载" in GRAPH_HTML
    assert "updateMediaBar" in GRAPH_HTML
    # lastMedia 只在有产物时填充, 链接指向 /api/media
    assert "lastMedia = {url, name, ctype}" in GRAPH_HTML
    assert 'btn.href = lastMedia.url' in GRAPH_HTML


def test_frontend_preset_auto_save_loop():
    """阶段18: 载入示例后自动落盘为自定义图 (presets→自定义图闭环)。"""
    assert 'api("/api/graph/save"' in GRAPH_HTML
    assert "已同步保存为自定义图" in GRAPH_HTML
    assert "collectGraph()" in GRAPH_HTML
    # 载入示例 handler 里确实在 applyGraph 之后触发 save
    idx_apply = GRAPH_HTML.index("applyGraph(id, {name: pre.name")
    idx_save = GRAPH_HTML.index("已同步保存为自定义图")
    assert idx_apply < idx_save


def test_frontend_export_import_json():
    """阶段21: 图导出/导入 JSON 控件 (工作台图可移植, 与 collectGraph 契约一致)。"""
    assert 'id="exportBtn"' in GRAPH_HTML
    assert 'id="importBtn"' in GRAPH_HTML
    assert 'id="importFile"' in GRAPH_HTML
    assert "导出 JSON" in GRAPH_HTML
    assert "导入 JSON" in GRAPH_HTML
    # 导出: 用 collectGraph() 序列化 → Blob → <a download> 触发下载
    assert 'JSON.stringify(data, null, 2)' in GRAPH_HTML
    assert 'a.download = ($("#gname").value || "graph") + ".json"' in GRAPH_HTML
    # 导入: 文件读取 → JSON.parse → 校验 nodes/edges 数组 → applyGraph 填画布
    assert '$("#importBtn").onclick = () => $("#importFile").click()' in GRAPH_HTML
    assert 'applyGraph(data.name || "imported"' in GRAPH_HTML
    assert 'Array.isArray(data.nodes)' in GRAPH_HTML
    assert 'Array.isArray(data.edges)' in GRAPH_HTML
    assert 'bar("导入失败: "+err.message, false)' in GRAPH_HTML


def test_frontend_provider_dropdown():
    """阶段22: llm_call 的 provider_id 输入挂本地模型下拉提示 (datalist)。"""
    assert 'list="providerOptions"' in GRAPH_HTML
    assert '<datalist id="providerOptions"></datalist>' in GRAPH_HTML
    assert 'api("/api/graph/models")' in GRAPH_HTML
    assert 'function refreshProviders' in GRAPH_HTML
    assert 'res.providers' in GRAPH_HTML
    assert 'refreshProviders();' in GRAPH_HTML


def test_frontend_node_status_coloring():
    """阶段23: 节点运行状态可视化 (按 logs 权威状态上色 ok→绿 / failed→红)。"""
    assert '.node.ok { border-color:#2ecc71' in GRAPH_HTML
    assert '.node.failed { border-color:var(--danger)' in GRAPH_HTML
    assert 'let nodeStatus = {};' in GRAPH_HTML
    # run 回调: 运行前清空 + 按 logs 填充 nodeStatus + 重新 render 上色
    assert 'nodeStatus = {};  // 阶段23: 运行前清空节点状态' in GRAPH_HTML
    assert 'nodeStatus[l.node_id]' in GRAPH_HTML
    assert 'l.status==="ok"||l.status==="completed"' in GRAPH_HTML
    assert 'el.classList.toggle("ok", nodeStatus[n.id] === "ok")' in GRAPH_HTML
    assert 'el.classList.toggle("failed", nodeStatus[n.id] === "failed")' in GRAPH_HTML


def test_frontend_auto_layout():
    """阶段24: 自动布局 — applyGraph 载入后按 DAG 拓扑分层排列 (避免堆叠)。"""
    assert 'function autoLayout' in GRAPH_HTML
    assert 'autoLayout();  // 阶段24: 按 DAG 拓扑分层排列, 避免堆叠' in GRAPH_HTML
    # Kahn 层深计算 + 左→右分层 + 同层纵向排布
    assert 'level[dst] = Math.max(level[dst]||0, (level[id]||0)+1)' in GRAPH_HTML
    assert 'nodes[id].x = padX + (+L)*gapX' in GRAPH_HTML
    assert 'nodes[id].y = padY + i*gapY' in GRAPH_HTML


def test_graph_models_endpoint():
    """阶段22: GET /api/graph/models 检测本地模型网关并组装 provider 列表。"""
    import tempfile
    import urllib.request
    import urllib.error
    # 用一个假 detect_local_models 模拟本机模型
    fake = {
        "ollama": {"available": True, "models": ["qwen2.5:7b"], "error": None},
        "llamacpp": {"available": True, "models": ["tuan-3b-nursery"], "error": None},
    }
    from tuan_cli.models import offline as off
    orig = off.detect_local_models
    off.detect_local_models = lambda: fake
    try:
        from tuan_cli.web.server import WebServer
        ws = tempfile.mkdtemp()
        srv = WebServer(kernel=None, workspace=ws, port=0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        for _ in range(200):
            if getattr(srv, "_httpd", None) is not None:
                break
            time.sleep(0.02)
        port = srv.port
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/graph/models")
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
            assert data.get("ok") is True
            provs = data.get("providers") or []
            got = {p["provider"] for p in provs}
            assert "ollama:qwen2.5:7b" in got
            assert "llamacpp:tuan-3b-nursery" in got
            assert all(p["label"] for p in provs)
        finally:
            srv._httpd.shutdown()
            srv._httpd.server_close()
    finally:
        off.detect_local_models = orig


# ---------------------------------------------------------------------------
# 阶段18: /api/media 下载闭环 (code_demo 渲染 → HTTP 取回)
# ---------------------------------------------------------------------------

def test_media_download_roundtrip():
    """code_demo preset 渲染出 mp4 → /api/media 按 media_rel 取回, 字节一致。"""
    import pathlib
    import urllib.request
    import urllib.parse
    from tuan_cli.web.graph_api import build_runner
    data = get_preset_data("code_demo")
    # GraphRunner 无 workspace 注入 → 产物落 cwd/media/ (测试 cwd=g:\Tuan-CLI)
    runner = build_runner(data)
    results = runner.run()
    vals = [v for v in results.values() if isinstance(v, dict) and v.get("media_rel")]
    assert vals, "codeanim 应产出带 media_rel 的结果"
    media_rel = vals[0]["media_rel"]
    assert media_rel.endswith(".mp4")
    # 落盘文件确实存在于 cwd/media/<rel>
    base = pathlib.Path.cwd() / "media"
    target = (base / media_rel).resolve()
    assert target.is_file(), f"产物应存在于 {target}"
    raw_expected = target.read_bytes()
    assert len(raw_expected) > 100, "mp4 应有实际字节"
    # 经 /api/media 取回 (服务器 workspace=g:\Tuan-CLI, 同 cwd)
    srv, port, t = _make_server()
    try:
        url = f"http://127.0.0.1:{port}/api/media?path={urllib.parse.quote(media_rel)}"
        with urllib.request.urlopen(url, timeout=10) as r:
            assert r.status == 200
            ctype = r.headers.get("Content-Type", "")
            assert "video/mp4" in ctype
            body = r.read()
        assert body == raw_expected, "下载字节应与源文件一致"
    finally:
        if getattr(srv, "_httpd", None) is not None:
            srv._httpd.shutdown()
            srv._httpd.server_close()
        t.join(timeout=5)
    # 清理产物
    try:
        target.unlink()
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
