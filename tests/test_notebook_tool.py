"""Notebook (.ipynb) 读写工具测试 (对标 Claude Code NotebookEdit)。"""

import json

from tuan_cli.config import Config
from tuan_cli.core.kernel import Kernel
from tuan_cli.tools import ToolRegistryPlugin, builtin_tool_plugins
from tuan_cli.tools.base import ToolContext


def _kernel():
    k = Kernel()
    k.provide("config", Config(), owner="test")
    k.register(ToolRegistryPlugin())
    for p in builtin_tool_plugins():
        if p.name in ("tools.filesystem", "tools.notebook"):
            k.register(p)
    k.activate_all()
    return k


def _ctx(k, tmp_path):
    return ToolContext(kernel=k, workspace=str(tmp_path), confirm=lambda _p: True)


def _nb(cells):
    return {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}


def _write_nb(tmp_path, cells):
    (tmp_path / "demo.ipynb").write_text(
        json.dumps(_nb(cells)), encoding="utf-8")


def _load(tmp_path):
    return json.loads((tmp_path / "demo.ipynb").read_text(encoding="utf-8"))


def test_tools_registered():
    k = _kernel()
    names = [t.name for t in k.require("tool_registry").tools]
    assert "notebook_read" in names
    assert "notebook_edit" in names


def test_insert_creates_notebook(tmp_path):
    k = _kernel()
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    out = registry.dispatch("notebook_edit", json.dumps({
        "notebook_path": "new.ipynb",
        "new_source": "print('hi')",
        "cell_type": "code",
        "edit_mode": "insert",
    }), ctx)
    assert "插入" in out
    nb = json.loads((tmp_path / "new.ipynb").read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4
    assert len(nb["cells"]) == 1
    assert nb["cells"][0]["cell_type"] == "code"
    assert "".join(nb["cells"][0]["source"]) == "print('hi')"
    assert "id" in nb["cells"][0]


def test_read_lists_cells(tmp_path):
    _write_nb(tmp_path, [
        {"cell_type": "code", "id": "aaa", "metadata": {},
         "source": ["x = 1\n"], "outputs": [], "execution_count": None},
        {"cell_type": "markdown", "id": "bbb", "metadata": {},
         "source": ["# title\n"]},
    ])
    k = _kernel()
    ctx = _ctx(k, tmp_path)
    out = k.require("tool_registry").dispatch(
        "notebook_read", json.dumps({"notebook_path": "demo.ipynb"}), ctx)
    assert "2 个单元格" in out
    assert "id=aaa" in out and "id=bbb" in out
    assert "markdown" in out


def test_replace_clears_outputs(tmp_path):
    _write_nb(tmp_path, [{
        "cell_type": "code", "id": "aaa", "metadata": {},
        "source": ["x = 1\n"], "execution_count": 3,
        "outputs": [{"output_type": "stream", "name": "stdout",
                     "text": ["1\n"]}],
    }])
    k = _kernel()
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    out = registry.dispatch("notebook_read",
                            json.dumps({"notebook_path": "demo.ipynb"}), ctx)
    assert "id=aaa" in out
    out = registry.dispatch("notebook_edit", json.dumps({
        "notebook_path": "demo.ipynb",
        "cell_id": "aaa",
        "new_source": "x = 2",
        "edit_mode": "replace",
    }), ctx)
    assert "替换" in out
    cell = _load(tmp_path)["cells"][0]
    assert "".join(cell["source"]) == "x = 2"
    assert cell["outputs"] == []
    assert cell["execution_count"] is None


def test_insert_after_cell_and_delete(tmp_path):
    _write_nb(tmp_path, [
        {"cell_type": "code", "id": "aaa", "metadata": {}, "source": ["a\n"],
         "outputs": [], "execution_count": None},
    ])
    k = _kernel()
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    registry.dispatch("notebook_read",
                      json.dumps({"notebook_path": "demo.ipynb"}), ctx)
    registry.dispatch("notebook_edit", json.dumps({
        "notebook_path": "demo.ipynb",
        "cell_id": "aaa",
        "new_source": "# 注释",
        "cell_type": "markdown",
        "edit_mode": "insert",
    }), ctx)
    cells = _load(tmp_path)["cells"]
    assert len(cells) == 2
    assert cells[1]["cell_type"] == "markdown"
    assert "".join(cells[1]["source"]) == "# 注释"

    registry.dispatch("notebook_edit", json.dumps({
        "notebook_path": "demo.ipynb",
        "cell_id": "aaa",
        "edit_mode": "delete",
    }), ctx)
    cells = _load(tmp_path)["cells"]
    assert len(cells) == 1
    assert cells[0]["cell_type"] == "markdown"


def test_replace_without_read_blocked(tmp_path):
    _write_nb(tmp_path, [{"cell_type": "code", "id": "aaa", "metadata": {},
                          "source": ["a\n"], "outputs": [],
                          "execution_count": None}])
    k = _kernel()
    ctx = _ctx(k, tmp_path)
    out = k.require("tool_registry").dispatch("notebook_edit", json.dumps({
        "notebook_path": "demo.ipynb",
        "cell_id": "aaa",
        "new_source": "b",
    }), ctx)
    assert "请先 read_file" in out


def test_path_escape_blocked(tmp_path):
    k = _kernel()
    ctx = _ctx(k, tmp_path)
    out = k.require("tool_registry").dispatch("notebook_edit", json.dumps({
        "notebook_path": "../../etc/evil.ipynb",
        "new_source": "x",
        "edit_mode": "insert",
    }), ctx)
    assert "工作区内" in out


def test_rejects_non_nbformat4(tmp_path):
    (tmp_path / "old.ipynb").write_text(json.dumps({
        "cells": [], "metadata": {}, "nbformat": 3, "nbformat_minor": 0,
    }), encoding="utf-8")
    k = _kernel()
    ctx = _ctx(k, tmp_path)
    out = k.require("tool_registry").dispatch(
        "notebook_read", json.dumps({"notebook_path": "old.ipynb"}), ctx)
    assert "nbformat 4" in out


def test_invalid_mode_and_type(tmp_path):
    _write_nb(tmp_path, [])
    k = _kernel()
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    registry.dispatch("notebook_read",
                      json.dumps({"notebook_path": "demo.ipynb"}), ctx)
    out = registry.dispatch("notebook_edit", json.dumps({
        "notebook_path": "demo.ipynb", "new_source": "x",
        "edit_mode": "move"}), ctx)
    assert "edit_mode 须为" in out
    out = registry.dispatch("notebook_edit", json.dumps({
        "notebook_path": "demo.ipynb", "new_source": "x",
        "cell_type": "sql", "edit_mode": "insert"}), ctx)
    assert "cell_type 须为" in out
