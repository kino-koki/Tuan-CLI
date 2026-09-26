# -*- coding: utf-8 -*-
"""codedev.retrieval 增强测试: Rust/Go 解析、增量索引更新。"""
import pytest
from pathlib import Path

from qingxiaotuan.codedev.retrieval import CodeIndex


@pytest.fixture()
def workspace(tmp_path):
    """创建一个包含多种语言文件的测试工作区。"""
    # Python 文件
    (tmp_path / "app.py").write_text(
        'import os\n\ndef main():\n    """Entry point."""\n    os.path.join("a", "b")\n\nclass App:\n    """Main app class."""\n    def run(self):\n        pass\n',
        encoding="utf-8",
    )
    # Rust 文件
    (tmp_path / "lib.rs").write_text(
        '/// A calculator struct\npub struct Calculator {\n    value: f64,\n}\n\nimpl Calculator {\n    /// Create new calculator\n    pub fn new() -> Self {\n        Self { value: 0.0 }\n    }\n    pub fn add(&mut self, x: f64) {\n        self.value += x;\n    }\n}\n\n/// Trait for operations\npub trait Compute {\n    fn compute(&self) -> f64;\n}\n',
        encoding="utf-8",
    )
    # Go 文件
    (tmp_path / "main.go").write_text(
        'package main\n\n// Server holds config\ntype Server struct {\n    addr string\n    port int\n}\n\n// Handler processes requests\nfunc Handler(w http.ResponseWriter, r *http.Request) {\n    fmt.Fprintf(w, "hello")\n}\n\n// StartServer starts the server\nfunc (s *Server) StartServer() error {\n    return nil\n}\n',
        encoding="utf-8",
    )
    # TypeScript 文件
    (tmp_path / "index.ts").write_text(
        'export function greet(name: string) {\n    return `Hello ${name}`;\n}\n\nexport class Router {\n    routes: Map<string, Function>;\n    constructor() {\n        this.routes = new Map();\n    }\n    add(path: string, handler: Function) {\n        this.routes.set(path, handler);\n    }\n}\n',
        encoding="utf-8",
    )
    return tmp_path


def test_index_python(workspace):
    """Python 索引: 函数、类、方法。"""
    idx = CodeIndex().build(workspace)
    names = {s.name for s in idx.symbols}
    assert "main" in names
    assert "App" in names
    assert "App.run" in names


def test_index_rust(workspace):
    """Rust 索引: struct、impl 方法、trait。"""
    idx = CodeIndex().build(workspace)
    names = {s.name for s in idx.symbols}
    assert "Calculator" in names
    assert "Calculator.new" in names
    assert "Calculator.add" in names
    assert "Compute" in names


def test_index_go(workspace):
    """Go 索引: func、type struct、方法。"""
    idx = CodeIndex().build(workspace)
    names = {s.name for s in idx.symbols}
    assert "Handler" in names
    assert "Server" in names
    assert "StartServer" in names


def test_index_typescript(workspace):
    """TypeScript 索引: function、class。"""
    idx = CodeIndex().build(workspace)
    names = {s.name for s in idx.symbols}
    assert "greet" in names
    assert "Router" in names


def test_retrieve_cross_language(workspace):
    """跨语言检索: 中文查询命中英文符号。"""
    idx = CodeIndex().build(workspace)
    # "计算" 应命中 Calculator
    result = idx.retrieve("计算 calculator", top_k=3)
    names = [h.symbol.name for h in result.hits]
    assert any("Calculator" in n for n in names)


def test_incremental_update(workspace):
    """增量更新: 只重新索引变更的文件。"""
    idx = CodeIndex().build(workspace)
    initial_count = len(idx.symbols)
    assert initial_count > 0

    # 修改一个文件
    (workspace / "app.py").write_text(
        'def new_function():\n    """Brand new function."""\n    pass\n',
        encoding="utf-8",
    )
    # 新增一个文件
    (workspace / "extra.py").write_text(
        'def extra_func():\n    pass\n',
        encoding="utf-8",
    )

    updated = idx.update_incremental(workspace)
    assert updated >= 2  # 至少 app.py 和 extra.py 被更新

    # 检查新符号存在
    names = {s.name for s in idx.symbols}
    assert "new_function" in names
    assert "extra_func" in names
    # 旧的符号应该被移除
    assert "main" not in names


def test_incremental_no_change(workspace):
    """增量更新: 无变化时不更新。"""
    idx = CodeIndex().build(workspace)
    updated = idx.update_incremental(workspace)
    assert updated == 0


def test_incremental_delete_file(workspace):
    """增量更新: 删除文件后移除对应符号。"""
    idx = CodeIndex().build(workspace)
    names_before = {s.name for s in idx.symbols}
    assert "Handler" in names_before

    (workspace / "main.go").unlink()
    idx.update_incremental(workspace)

    names_after = {s.name for s in idx.symbols}
    assert "Handler" not in names_after
